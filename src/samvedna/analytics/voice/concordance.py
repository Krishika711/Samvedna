"""Fusing what was said with how it sounded.

A concordance gap needs both halves: a minimising claim, **and** acoustic
evidence pointing the other way. Neither alone is a finding — cheerful words are
usually just cheerful, and a strained voice while describing a hard week is
exactly what it should sound like.

Three guards keep this from becoming a threshold table that fires:

**Graded, not binary.** Each feature contributes a divergence in 0..1 through an
explicit reference band, so a marginal exceedance stays marginal.

**A corroboration floor.** At least two independent features must diverge. One
twitchy measurement cannot raise a finding on its own — the same principle as
the evidence gate's breadth requirement, one layer down.

**Multiplied by lexical confidence.** No claim, no finding, however strained the
voice. This is what anchors the measurement to a sentence somebody actually said.

And the whole thing is still only a **T3 signal** when it reaches the gates. The
reference bands are not clinically validated, so a concordance gap cannot name
anybody on its own — it corroborates, or it does not.

## Why a cue-anchored gap is not enough on its own

Anchoring to a minimising phrase buys specificity and costs coverage, and the
coverage it costs is the part that matters most. Consider somebody in real
difficulty who says *"the roster has been manageable"* — a claim no cue bank
contains — or who simply answers questions without ever making a claim about
themselves. There is no phrase to anchor to, so a purely cue-driven engine
returns "nothing to measure" about a voice that was audibly strained throughout.
That is the person this system exists to notice, and the design would have
missed them silently.

So a session produces **two independent signals**:

* `assess()` — a **concordance gap**: a minimising claim contradicted by the
  voice underneath it. Specific, and it needs the words.
* `sustained_strain()` — **strain the words never claimed**: acoustic divergence
  holding across the session whatever was being said. It needs no cue at all,
  and therefore has to clear a materially higher bar — more features, sustained
  over more of the sitting — because there is no lexical anchor to make it
  specific.

## The limit, stated plainly

A person who says "I'm fine" and genuinely *sounds* fine produces **no
divergence to measure**. Not a small one — none. Both paths above return
nothing, and they are correct to: there is no signal there. Any system that
claims to detect successfully masked distress from voice is claiming to measure
something that left no trace in the measurement.

Two things follow, and they are the reason this module is one of nine rather
than the product:

**Voice is measured against the person's own baseline, not only against a
population band.** A jawan whose voice has always been flat and clipped is not
deviating; a jawan whose voice flattened over six months is, even if the flatter
version still sits inside the normal band for the force. `baseline_shift()` is
what notices the second case, and it is the only part of this module with any
purchase on a practised mask — a mask is usually a change from how somebody used
to sound, even when it lands inside normal.

**And when the mask holds completely, the system does not rely on voice at
all.** What a person cannot mask in a ten-minute sitting is four denied leave
applications, twenty-three consecutive duty days, three postings in eighteen
months, and a workload sitting above establishment — traces laid down over
months, recorded by other people, that they do not control. That is what the
other eight domains are for, and it is why voice is tiered T3 and can never name
anybody on its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from samvedna.analytics.voice.acoustics import (
    BAND_BY_FEATURE,
    BANDS,
    AcousticFrame,
    Evidence,
)
from samvedna.analytics.voice.minimisation import CueMatch

__all__ = [
    "Assessment",
    "BaselineShift",
    "StrainReading",
    "VoiceBaseline",
    "baseline_shift",
    "assess",
    "sustained_strain",
    "MIN_DIVERGENCE",
    "MIN_CONTRIBUTORS",
    "STRAIN_MIN_CONTRIBUTORS",
    "STRAIN_MIN_DIVERGENCE",
    "STRAIN_MIN_COVERAGE",
]

# Below this, a gap is noise and is not raised at all.
MIN_DIVERGENCE = 0.22
# Independent features that must diverge before a gap can be raised.
MIN_CONTRIBUTORS = 2
# ...and how far one has to have moved to count as one of them.
#
# Without this the floor is nearly free: any non-zero divergence counted, so a
# feature sitting a fifth of the way out of its normal band corroborated as
# loudly as one at the far end. Measured on a window with a single genuinely
# strained feature, an intonation range of 7 against a normal of 8 — barely off
# — supplied the second "independent" contributor and the gap was raised on what
# is really one measurement.
MIN_CONTRIBUTOR_DIVERGENCE = 0.25


@dataclass(frozen=True, slots=True)
class Assessment:
    """The outcome of fusing one claim with the voice around it."""

    divergence: float
    evidence: tuple[Evidence, ...]
    raised: bool
    reason: str
    cue: CueMatch | None = None

    @property
    def severity(self) -> str:
        if self.divergence >= 0.66:
            return "marked"
        if self.divergence >= 0.40:
            return "moderate"
        return "slight"

    def describe(self) -> str:
        """Plain language for a clinician. Never a diagnosis, never a percentage."""
        if not self.raised:
            return self.reason
        drivers = ", ".join(e.describe() for e in self.evidence[:3])
        return (
            f"Said “{self.cue.quote}”. The voice under it diverges "
            f"{self.severity}ly: {drivers}."
        )


def _representative(frames: list[AcousticFrame], feature: str) -> float | None:
    """Median across frames, ignoring frames that lack the feature.

    Median rather than peak: a peak rewards a single glitchy window, which is
    exactly how a threshold table produces confident nonsense.
    """
    values = [
        getattr(f, feature)
        for f in frames
        if f.trustworthy and getattr(f, feature, None) is not None
    ]
    return median(values) if values else None


def assess(cue: CueMatch | None, frames: list[AcousticFrame]) -> Assessment:
    """One claim plus the acoustics around it, in; one assessment, out."""
    if cue is None:
        return Assessment(0.0, (), False, "no minimising claim to anchor a measurement")
    if not cue.strong:
        return Assessment(
            0.0, (), False,
            f"the phrase “{cue.phrase}” is too weak a register marker "
            f"({cue.confidence:.2f}) to anchor a measurement",
            cue=cue,
        )

    usable = [f for f in frames if f.trustworthy]
    if not usable:
        return Assessment(
            0.0, (), False,
            "not enough voiced speech in this window to measure anything",
            cue=cue,
        )

    contributions: list[tuple[Evidence, float]] = []
    for band in BANDS:
        value = _representative(usable, band.feature)
        if value is None:
            continue
        divergence = band.divergence(value)
        if divergence < MIN_CONTRIBUTOR_DIVERGENCE:
            continue
        contributions.append(
            (
                Evidence(
                    feature=band.feature,
                    value=round(value, 4),
                    band_normal=band.normal,
                    band_notable=band.notable,
                    divergence=round(divergence, 3),
                    label=band.label,
                ),
                band.weight,
            )
        )

    if len(contributions) < MIN_CONTRIBUTORS:
        return Assessment(
            0.0,
            tuple(e for e, _ in contributions),
            False,
            f"only {len(contributions)} feature moved meaningfully; a gap needs "
            f"at least {MIN_CONTRIBUTORS} independent ones past "
            f"{MIN_CONTRIBUTOR_DIVERGENCE}, so one twitchy measurement cannot "
            f"raise a finding on its own",
            cue=cue,
        )

    total_weight = sum(w for _, w in contributions)
    weighted = sum(e.divergence * w for e, w in contributions) / total_weight
    divergence = round(weighted * cue.confidence, 4)

    evidence = tuple(
        e for e, _ in sorted(contributions, key=lambda pair: -pair[0].divergence)
    )
    if divergence < MIN_DIVERGENCE:
        return Assessment(
            divergence, evidence, False,
            f"divergence {divergence:.2f} is below the {MIN_DIVERGENCE} floor "
            f"for raising a gap",
            cue=cue,
        )
    return Assessment(divergence, evidence, True, "concordance gap", cue=cue)


# --- strain the words never claimed ------------------------------------------
#
# Unanchored, so the bar is higher in three independent ways at once. Each one
# is doing a specific job:
#
#   * more features must move, because without a claim to anchor to, two
#     correlated measurements are much easier to hit by chance;
#   * they must move further, because there is no lexical confidence multiplier
#     damping the score;
#   * and it must hold across most of the sitting, because a minute of strain
#     while describing something genuinely hard is not a finding about a person.
STRAIN_MIN_CONTRIBUTORS = 4
STRAIN_MIN_DIVERGENCE = 0.45
STRAIN_MIN_COVERAGE = 0.60
# A sitting shorter than this cannot establish that anything held.
STRAIN_MIN_WINDOWS = 5


@dataclass(frozen=True, slots=True)
class StrainReading:
    """Acoustic divergence across a session, with no claim anchoring it.

    Deliberately not called a concordance gap: nothing here is in *dis*cordance
    with anything, because the person made no claim to contradict. It is the
    plainer and weaker statement that the voice sounded strained throughout.
    """

    divergence: float
    coverage: float
    evidence: tuple[Evidence, ...]
    raised: bool
    reason: str
    windows: int = 0

    @property
    def severity(self) -> str:
        if self.divergence >= 0.66:
            return "marked"
        if self.divergence >= 0.50:
            return "moderate"
        return "slight"

    def describe(self) -> str:
        if not self.raised:
            return self.reason
        drivers = ", ".join(e.describe() for e in self.evidence[:3])
        return (
            f"No minimising claim was made, and the voice was {self.severity}ly "
            f"strained across {self.coverage:.0%} of the sitting regardless: "
            f"{drivers}."
        )


def sustained_strain(frames: list[AcousticFrame]) -> StrainReading:
    """Was the voice strained throughout, whatever the person was saying?

    This is the path for somebody in difficulty who never says they are fine —
    who answers the questions, describes the roster, and gives the cue bank
    nothing to catch. A cue-anchored engine reports nothing about them, which is
    the wrong kind of silence.
    """
    usable = [f for f in frames if f.trustworthy]
    if len(usable) < STRAIN_MIN_WINDOWS:
        return StrainReading(
            0.0, 0.0, (), False,
            f"only {len(usable)} usable window(s); {STRAIN_MIN_WINDOWS} are needed "
            f"before anything can be said to have held across a sitting",
            windows=len(usable),
        )

    contributions: list[tuple[Evidence, float, float]] = []
    for band in BANDS:
        per_window = [
            band.divergence(getattr(f, band.feature))
            for f in usable
            if getattr(f, band.feature, None) is not None
        ]
        if not per_window:
            continue
        typical = median(per_window)
        if typical < MIN_CONTRIBUTOR_DIVERGENCE:
            continue
        held = sum(1 for d in per_window if d >= MIN_CONTRIBUTOR_DIVERGENCE) / len(
            per_window
        )
        value = median(
            [
                getattr(f, band.feature)
                for f in usable
                if getattr(f, band.feature, None) is not None
            ]
        )
        contributions.append(
            (
                Evidence(
                    feature=band.feature,
                    value=round(value, 4),
                    band_normal=band.normal,
                    band_notable=band.notable,
                    divergence=round(typical, 3),
                    label=band.label,
                ),
                band.weight,
                held,
            )
        )

    if len(contributions) < STRAIN_MIN_CONTRIBUTORS:
        return StrainReading(
            0.0, 0.0, tuple(e for e, _, _ in contributions), False,
            f"{len(contributions)} feature(s) diverged; without a claim to anchor "
            f"to, {STRAIN_MIN_CONTRIBUTORS} are needed before the voice alone says "
            f"anything",
            windows=len(usable),
        )

    total = sum(w for _, w, _ in contributions)
    divergence = round(sum(e.divergence * w for e, w, _ in contributions) / total, 4)
    coverage = round(sum(h * w for _, w, h in contributions) / total, 4)
    evidence = tuple(
        e for e, _, _ in sorted(contributions, key=lambda c: -c[0].divergence)
    )

    if divergence < STRAIN_MIN_DIVERGENCE:
        return StrainReading(
            divergence, coverage, evidence, False,
            f"divergence {divergence:.2f} is below the {STRAIN_MIN_DIVERGENCE} "
            f"floor that an unanchored reading has to clear",
            windows=len(usable),
        )
    if coverage < STRAIN_MIN_COVERAGE:
        return StrainReading(
            divergence, coverage, evidence, False,
            f"the strain held across only {coverage:.0%} of the sitting; "
            f"{STRAIN_MIN_COVERAGE:.0%} is needed. A hard stretch inside a "
            f"conversation is not a finding about a person",
            windows=len(usable),
        )
    return StrainReading(
        divergence, coverage, evidence, True, "sustained vocal strain",
        windows=len(usable),
    )


# --- change from the person's own voice --------------------------------------
#
# The only part of this module with any purchase on a practised mask.
#
# Population reference bands answer "does this sound strained compared with
# people in general". They cannot answer "does this sound strained compared with
# how *you* sounded in March", and the second question is the one that survives
# somebody who is good at sounding fine — because a mask is usually a change
# from how they used to sound, even when it lands inside the normal band.
#
# It is a partial answer and not a solution. A mask maintained consistently from
# the first session onward leaves nothing to compare against, and this returns
# nothing, correctly.

# Sessions of a person's own history needed before a baseline means anything.
BASELINE_MIN_SESSIONS = 3
# Shift, in within-person standard deviations, before it is worth reporting.
BASELINE_SHIFT_Z = 1.5
# Features that must have shifted together.
BASELINE_MIN_FEATURES = 3


@dataclass(frozen=True, slots=True)
class VoiceBaseline:
    """A person's own voice, from their prior sessions. Never anybody else's."""

    pid: str
    sessions: int
    medians: dict[str, float]
    spreads: dict[str, float]

    @property
    def usable(self) -> bool:
        return self.sessions >= BASELINE_MIN_SESSIONS

    @classmethod
    def from_sessions(
        cls, pid: str, per_session: list[dict[str, float]]
    ) -> VoiceBaseline:
        medians: dict[str, float] = {}
        spreads: dict[str, float] = {}
        for band in BANDS:
            values = [
                s[band.feature] for s in per_session if s.get(band.feature) is not None
            ]
            if len(values) < 2:
                continue
            centre = median(values)
            # Median absolute deviation, scaled to a standard-deviation
            # equivalent. Robust: one bad session must not widen somebody's
            # baseline until nothing can ever look like a change again.
            mad = median([abs(v - centre) for v in values]) * 1.4826
            medians[band.feature] = centre
            spreads[band.feature] = max(mad, abs(centre) * 0.05, 1e-6)
        return cls(pid=pid, sessions=len(per_session), medians=medians, spreads=spreads)


@dataclass(frozen=True, slots=True)
class BaselineShift:
    """How far this sitting has moved from how this person usually sounds."""

    raised: bool
    reason: str
    shifted: tuple[tuple[str, float, float, float], ...] = ()  # feature, was, now, z

    def describe(self) -> str:
        if not self.raised:
            return self.reason
        parts = [
            f"{BAND_BY_FEATURE[f].label} {was:.3g} → {now:.3g}"
            for f, was, now, _ in self.shifted[:3]
        ]
        return (
            "Compared with how this person has sounded before: "
            + "; ".join(parts)
            + ". Each still sits inside the normal band for the force, which is "
            "why a population comparison alone would report nothing."
        )


def baseline_shift(
    frames: list[AcousticFrame], baseline: VoiceBaseline | None
) -> BaselineShift:
    """Has this person's voice changed from their own history?

    Answers a question the population bands cannot, and is silent when it has no
    history to answer it with — which is the correct output, not a failure.
    """
    if baseline is None or not baseline.usable:
        return BaselineShift(
            False,
            f"no usable voice history for this person "
            f"({baseline.sessions if baseline else 0} of "
            f"{BASELINE_MIN_SESSIONS} sessions); there is nothing to compare against",
        )

    usable = [f for f in frames if f.trustworthy]
    if not usable:
        return BaselineShift(False, "not enough voiced speech in this sitting")

    shifted: list[tuple[str, float, float, float]] = []
    for band in BANDS:
        if band.feature not in baseline.medians:
            continue
        values = [
            getattr(f, band.feature)
            for f in usable
            if getattr(f, band.feature, None) is not None
        ]
        if not values:
            continue
        now = median(values)
        was = baseline.medians[band.feature]
        z = (now - was) / baseline.spreads[band.feature]
        # Only shifts *toward* the notable end count. A voice becoming warmer,
        # steadier or more expressive than usual is not a welfare signal, and
        # counting any change would make recovery look like deterioration.
        toward = (band.notable - band.normal)
        if z * (1 if toward > 0 else -1) >= BASELINE_SHIFT_Z:
            shifted.append((band.feature, round(was, 4), round(now, 4), round(z, 2)))

    if len(shifted) < BASELINE_MIN_FEATURES:
        return BaselineShift(
            False,
            f"{len(shifted)} feature(s) moved from this person's own baseline; "
            f"{BASELINE_MIN_FEATURES} are needed before a change is worth reporting",
            tuple(shifted),
        )
    return BaselineShift(True, "shift from this person's own voice", tuple(shifted))
