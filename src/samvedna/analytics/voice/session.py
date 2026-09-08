"""A voice session: audio in, measurements and findings out, nothing kept.

The invariant this module exists to hold: **no audio is ever stored, and no
transcript line ever reaches the audit ledger.** Audio is analysed in the window
it arrives in and discarded; the transcript exists for the length of the session
so a clinician can see the sentence a finding is anchored to, and is gone when
the session closes.

That is not a privacy nicety — it is what makes voice capture of psychological
disclosure defensible at all. What survives a session is a `DomainDeviation` for
the `voice` domain, which carries no words and no sound.

**The duty of care is discharged here, not deferred.** The master prompt warns
that inviting unstructured psychological disclosure creates a clinical duty the
system cannot discharge. Capturing speech invites exactly that, so this module
listens for acute disclosure and routes it the same day — the same path a PHQ-9
item 9 endorsement takes. A system that hears somebody say they cannot go on and
files it as a T3 signal has not discharged anything.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from samvedna.analytics.voice.acoustics import AcousticFrame
from samvedna.analytics.voice.concordance import (
    Assessment,
    BaselineShift,
    StrainReading,
    VoiceBaseline,
    assess,
    baseline_shift,
    sustained_strain,
)
from samvedna.analytics.voice.minimisation import CueMatch, detect
from samvedna.config.weights import tier_of, weight_of
from samvedna.core.types import DomainDeviation

__all__ = ["VoiceSession", "Finding", "ACUTE_PHRASES", "acute_in"]

# Phrases that route immediately, in the person's own words.
#
# Deliberately narrow and deliberately literal. This is not sentiment analysis
# and must not become it: a broad net here would route ordinary frustration to a
# mental-health authority and teach the force that speaking plainly gets you
# referred, which would end voluntary disclosure entirely.
ACUTE_PHRASES: tuple[str, ...] = (
    r"\bkill myself\b",
    r"\bend (my life|it all)\b",
    r"\btake my own life\b",
    r"\bbetter off (dead|without me)\b",
    r"\bno (point|reason) (in )?(going on|living)\b",
    r"\bcan'?t go on\b",
    r"\bwant to die\b",
    r"\bhurt myself\b",
)
_ACUTE = tuple(re.compile(p) for p in ACUTE_PHRASES)

# How many windows of speech are needed before a session's voice signal is worth
# reporting at all. A single sentence is an anecdote.
MIN_ASSESSMENTS_FOR_A_DEVIATION = 3


def acute_in(utterance: str) -> tuple[str, ...]:
    """Acute disclosure heard in speech, by phrase. Never by model score."""
    lowered = (utterance or "").lower()
    return tuple(
        source
        for pattern, source in zip(_ACUTE, ACUTE_PHRASES, strict=True)
        if pattern.search(lowered)
    )


@dataclass(frozen=True, slots=True)
class Finding:
    """One concordance gap, for the clinician's screen and nowhere else."""

    at_ms: int
    assessment: Assessment

    @property
    def quote(self) -> str:
        return self.assessment.cue.quote if self.assessment.cue else ""


@dataclass
class VoiceSession:
    """One consented voice session. Holds measurements, never sound."""

    pid: str
    unit_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # This person's own prior sessions. Without it the session can only compare
    # against the force in general, which is blind to somebody who has always
    # sounded one way and no longer does.
    baseline: VoiceBaseline | None = None
    frames: list[AcousticFrame] = field(default_factory=list)
    assessments: list[Assessment] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    acute_heard: list[tuple[int, str, str]] = field(default_factory=list)
    closed: bool = False

    # A transcript is held only while the session is open, so a clinician can
    # see the sentence a finding is anchored to. `close()` destroys it.
    _transcript: list[tuple[int, str]] = field(default_factory=list, repr=False)

    def feed_audio(self, frame: AcousticFrame) -> None:
        """Take a window's measurements. The audio never arrives here."""
        if self.closed:
            raise RuntimeError("session is closed")
        self.frames.append(frame)

    def feed_utterance(self, at_ms: int, text: str) -> Assessment | None:
        """Take one settled utterance and assess it against recent acoustics.

        Returns the assessment, or None when there was no minimising claim to
        anchor a measurement to.
        """
        if self.closed:
            raise RuntimeError("session is closed")
        self._transcript.append((at_ms, text))

        for phrase in acute_in(text):
            self.acute_heard.append((at_ms, phrase, text))

        cues: tuple[CueMatch, ...] = detect(text)
        if not cues:
            return None

        # Only acoustics from around the claim. A strained voice ninety seconds
        # earlier, while describing something difficult, says nothing about this
        # sentence.
        window = [f for f in self.frames if abs(f.at_ms - at_ms) <= 45_000]
        assessment = assess(cues[0], window)
        self.assessments.append(assessment)
        if assessment.raised:
            self.findings.append(Finding(at_ms, assessment))
        return assessment

    @property
    def has_acute_disclosure(self) -> bool:
        return bool(self.acute_heard)

    def transcript_for_clinician(self) -> tuple[tuple[int, str], ...]:
        """Readable while the session is open. Gone once it closes."""
        return tuple(self._transcript)

    def close(self) -> None:
        """Destroy the transcript. Measurements and findings survive."""
        self._transcript.clear()
        self.closed = True

    # ------------------------------------------------- into the gate engine --
    def strain(self) -> StrainReading:
        """Was the voice strained throughout, whatever was being said?

        The path for somebody in difficulty who never claims to be fine. A
        cue-anchored engine reports nothing about them, which is the wrong kind
        of silence.
        """
        return sustained_strain(self.frames)

    def shift(self) -> BaselineShift:
        """Has this person's voice changed from their own history?

        The only reading here with any purchase on a practised mask, and it is
        silent when there is no history to compare against.
        """
        return baseline_shift(self.frames, self.baseline)

    def summarise_features(self) -> dict[str, float]:
        """This sitting's median per feature, for building a future baseline.

        Six numbers. No audio, no words, nothing that could reconstruct either.
        """
        from statistics import median

        from samvedna.analytics.voice.acoustics import BANDS

        usable = [f for f in self.frames if f.trustworthy]
        out: dict[str, float] = {}
        for band in BANDS:
            values = [
                getattr(f, band.feature)
                for f in usable
                if getattr(f, band.feature, None) is not None
            ]
            if values:
                out[band.feature] = round(median(values), 5)
        return out

    def as_deviation(self, unit_mean: float = 0.0, unit_stdev: float = 0.15):
        """The voice session as a `DomainDeviation`, or None if there is not
        enough of it to say anything.

        Two routes in, and either is enough: a concordance gap where the words
        were contradicted, or sustained strain where no claim was made at all.
        A session that produces neither produces nothing.

        This is the only thing that leaves a session. It carries no words, no
        sound, and no quote — a domain, a pair of z-scores, and breach fractions.
        """
        raised = [a for a in self.assessments if a.raised]
        strain = self.strain()
        shift = self.shift()

        if not raised and not strain.raised and not shift.raised:
            return None

        if raised and len(self.assessments) >= MIN_ASSESSMENTS_FOR_A_DEVIATION:
            gap_rate = len(raised) / len(self.assessments)
            severity = sum(a.divergence for a in raised) / len(raised)
            value = min(1.0, gap_rate * severity * 2.0)
        elif strain.raised:
            # Unanchored, so it is reported at a discount even after clearing a
            # higher bar. The words could have corroborated it and did not, and
            # that absence is information rather than nothing.
            gap_rate = strain.coverage
            value = min(1.0, strain.divergence * strain.coverage)
        else:
            # Only a shift from the person's own baseline. The weakest of the
            # three, reported weakest: nothing about this sitting was outside
            # normal for the force, and the whole claim is that it was outside
            # normal *for them*.
            gap_rate = 0.5
            value = min(1.0, 0.10 * len(shift.shifted))

        z_self = (value - unit_mean) / unit_stdev if unit_stdev else 0.0
        return DomainDeviation(
            domain="voice",
            z_self=round(z_self, 4),
            z_unit=round(z_self * 0.8, 4),
            direction="elevated",
            windows_breached=1,
            tier=tier_of("voice"),
            weight=weight_of("voice"),
            # A session is a point in time, not a sustained pattern. Reporting a
            # single sitting as if it breached every day of a 90-day window would
            # let one conversation clear the persistence gate, which is exactly
            # what that gate exists to prevent.
            daily_breach={7: round(gap_rate, 4), 30: 0.0, 90: 0.0},
            missing_fraction=0.0,
        )
