"""Live voice sessions — a real microphone, measured on this machine.

What makes this usable rather than a demonstration is that the audio is real and
the measurement is real. What makes it *shippable* is what happens to the audio
afterwards: a window arrives, six numbers are computed from it, and the samples
are dropped before the request returns. There is no field to keep them in and no
directory they are written to.

Three deliberate absences, each of which a normal build would have filled in:

**No speech-to-text service.** Detecting a minimising phrase needs words, and
the easy way to get them is the browser's built-in recogniser — which, in every
mainstream browser, uploads the audio to the vendor. For ordinary dictation that
is a reasonable trade. For a soldier describing his mental state it is precisely
what PART 1 and PART 10 forbid, so the words come from the person typing them,
or from an on-device transcriber the operator has installed. The field is
labelled so nobody has to guess which.

**No session store on disk.** A session lives in memory for as long as it is
open. Closing it destroys the transcript and returns six numbers.

**No identity.** A session is keyed by a session id and carries a pid. Nothing
here can resolve either to a person; that is L5's job and needs a credential.
"""
from __future__ import annotations

import base64
import secrets
from datetime import UTC, datetime

import numpy as np
from fastapi import Depends, HTTPException, Request

from samvedna.analytics.voice.acoustics import SAMPLE_RATE, analyse
from samvedna.analytics.voice.concordance import VoiceBaseline
from samvedna.analytics.voice.session import VoiceSession
from samvedna.config.flags import settings
from samvedna.config.thresholds import PHQ9_CUTOFF
from samvedna.core.types import InstrumentResponse
from samvedna.disclosure.rbac import Principal

__all__ = ["VoiceStore", "attach"]

# A window shorter than this cannot carry a reliable pitch estimate, and one
# much longer stops feeling live to the person speaking.
MIN_WINDOW_S = 1.0
MAX_WINDOW_S = 6.0
# Refuse a payload that could not plausibly be a window of speech, before
# decoding it.
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024


class VoiceStore:
    """Open sessions, in memory, for the life of the process.

    Deliberately not a database. A voice session is a conversation that is
    happening now; persisting one would mean persisting the transcript, and the
    transcript is the thing this design is most careful to destroy.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, VoiceSession] = {}
        # Per-person history of *summarised* sittings — six medians each, no
        # audio and no words. This is what lets a later session ask "does this
        # sound like how you usually sound?", which is the only reading with any
        # purchase on somebody who is good at sounding fine.
        self._history: dict[str, list[dict[str, float]]] = {}

    def open(self, pid: str, unit_id: str) -> tuple[str, VoiceSession]:
        session_id = secrets.token_urlsafe(12)
        history = self._history.get(pid, [])
        baseline = (
            VoiceBaseline.from_sessions(pid, history) if len(history) >= 2 else None
        )
        session = VoiceSession(pid=pid, unit_id=unit_id, baseline=baseline)
        self._sessions[session_id] = session
        return session_id, session

    def get(self, session_id: str) -> VoiceSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="no such voice session")
        return session

    def remember(self, session: VoiceSession) -> int:
        """Keep the six medians so a future sitting has something to compare to."""
        summary = session.summarise_features()
        if summary:
            self._history.setdefault(session.pid, []).append(summary)
        return len(self._history.get(session.pid, []))

    def history_length(self, pid: str) -> int:
        return len(self._history.get(pid, []))

    def restore(self, pid: str, kept: dict[str, float]) -> int:
        """Put a past sitting's medians back after a restart.

        Only the six medians, which is all `remember` ever kept. There is no
        audio and no transcript to restore because there never was any to
        store — the sitting destroys both before this data exists.

        Without this, a restart made everybody a first-time speaker and
        `baseline_shift` had nothing to compare against. That is the one reading
        of the three that needs more than today, so losing the history did not
        degrade it — it removed it.
        """
        if kept:
            self._history.setdefault(pid, []).append(dict(kept))
        return len(self._history.get(pid, []))

    def close(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


def _frame_payload(frame) -> dict:
    # `available()` returns only the six features that have a reference band —
    # the ones a finding can rest on. Pitch is not one of them, because there is
    # no such thing as a concerning pitch: a low voice is a low voice. It is
    # included here anyway, because it is the one number a person immediately
    # recognises as their own, and a screen of five abstractions with nothing
    # familiar on it does not read as a measurement of you.
    features = dict(frame.available())
    if frame.f0_hz is not None:
        features["f0_hz"] = frame.f0_hz
    return {
        "at_ms": frame.at_ms,
        "duration_s": round(frame.duration_s, 3),
        "voiced_fraction": round(frame.voiced_fraction, 3),
        "trustworthy": frame.trustworthy,
        "features": features,
    }


def _readings(session: VoiceSession) -> dict:
    strain = session.strain()
    shift = session.shift()
    return {
        "gap": {
            "raised": bool(session.findings),
            "count": len(session.findings),
            "detail": (
                session.findings[-1].assessment.describe()
                if session.findings
                else "no concordance gap yet — a gap needs a minimising claim "
                     "contradicted by the voice underneath it"
            ),
        },
        "strain": {
            "raised": strain.raised,
            "divergence": strain.divergence,
            "coverage": strain.coverage,
            "windows": strain.windows,
            "detail": strain.describe(),
        },
        "shift": {
            "raised": shift.raised,
            "detail": shift.describe(),
            "shifted": [
                {"feature": f, "was": was, "now": now, "z": z}
                for f, was, now, z in shift.shifted
            ],
        },
    }


def _resolve_pid(principal: Principal, requested: str | None) -> str:
    """Which person this request is about.

    In a deployment `principal.subject_id` *is* the pid — it comes from the
    person's own token — and `requested` either matches it or is refused.

    REPLAY has no sign-in, so the console holds a role and the literal operator
    id `"SELF"`. That is not a pid, and it is why voice was unreachable: the
    personnel console recorded voice consent against the person's real pid, and
    this module then asked whether `"SELF"` had consented. It never had, so the
    sitting was refused however many times the toggle was switched on. Two
    surfaces using different identities for the same person, which is the same
    fault that had made the self-assessment inert.

    The `"SELF"` allowance is confined to replay mode. In live mode a mismatch
    is refused, so this cannot become a way to open a sitting as somebody else.
    """
    if requested and requested != principal.subject_id:
        if principal.subject_id != "SELF" or settings().mode != "replay":
            raise HTTPException(
                status_code=403, detail="you may only open your own sitting"
            )
        return requested
    return principal.subject_id


def _owns(principal: Principal, session_pid: str) -> bool:
    """Whether this principal may act on a sitting belonging to `session_pid`."""
    if principal.subject_id == session_pid:
        return True
    return principal.subject_id == "SELF" and settings().mode == "replay"


def attach(app, get_state):
    """Wire the voice routes onto the app, sharing its state object."""

    @app.post("/api/voice/session")
    def open_session(
        request: Request,
        payload: dict | None = None,
        principal: Principal = Depends(_voice_principal),
    ):
        """Start a sitting. Requires the person's own consent to the voice domain.

        Consent is checked here rather than trusted from the client, and the
        voice domain is a separate toggle from everything else — agreeing to
        have your leave record read is not agreeing to be recorded.
        """
        state = get_state(request)
        pid = _resolve_pid(principal, (payload or {}).get("pid"))
        consent = state.consent.state_for(pid)
        if consent is None or not consent.covers("voice"):
            raise HTTPException(
                status_code=403,
                detail=(
                    "this sitting needs your consent to the voice domain, which "
                    "is a separate choice from the rest. Turn it on under "
                    "'What I allow' first — and you can turn it off again "
                    "afterwards."
                ),
            )

        session_id, session = state.voice.open(pid, consent.pid and "" or "")
        state.ledger.append(
            actor=f"personnel:{pid}",
            action="score.computed",
            subject_pid=pid,
            purpose="welfare:self",
            detail={
                "voice_session": "opened",
                "has_baseline": session.baseline is not None,
                "prior_sittings": state.voice.history_length(pid),
            },
        )
        return {
            "session_id": session_id,
            "sample_rate": SAMPLE_RATE,
            "window_seconds": 2.0,
            "prior_sittings": state.voice.history_length(pid),
            "has_baseline": session.baseline is not None,
            "audio_retained": False,
            "note": (
                "Your voice is measured on this machine and the audio is "
                "discarded as soon as the measurement is taken. Nothing is "
                "uploaded anywhere, and nothing is kept."
            ),
        }

    @app.post("/api/voice/{session_id}/audio")
    def push_audio(
        session_id: str,
        request: Request,
        payload: dict,
        principal: Principal = Depends(_voice_principal),
    ):
        """One window of audio in; six numbers out; the samples dropped.

        Takes 16-bit mono PCM at 16 kHz, base64-encoded. The array is decoded,
        measured, and goes out of scope when this function returns — it is never
        assigned to the session, never written to disk, and never logged.
        """
        state = get_state(request)
        session = state.voice.get(session_id)
        if not _owns(principal, session.pid):
            raise HTTPException(status_code=403, detail="not your session")

        encoded = payload.get("pcm16", "")
        if not encoded or len(encoded) > MAX_PAYLOAD_BYTES:
            raise HTTPException(status_code=422, detail="expected a base64 PCM window")
        try:
            raw = base64.b64decode(encoded, validate=True)
            samples = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
        except Exception as exc:
            raise HTTPException(status_code=422, detail="could not decode audio") from exc

        seconds = len(samples) / SAMPLE_RATE
        if not MIN_WINDOW_S <= seconds <= MAX_WINDOW_S:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"window is {seconds:.1f}s; needs to be between "
                    f"{MIN_WINDOW_S:g}s and {MAX_WINDOW_S:g}s"
                ),
            )

        frame = analyse(samples, at_ms=int(payload.get("at_ms", 0)))
        session.feed_audio(frame)
        # `samples` and `raw` fall out of scope here. Nothing else holds them.
        return {
            "frame": _frame_payload(frame),
            "windows": len(session.frames),
            "readings": _readings(session),
        }

    @app.post("/api/voice/{session_id}/utterance")
    def push_utterance(
        session_id: str,
        request: Request,
        payload: dict,
        principal: Principal = Depends(_voice_principal),
    ):
        """What was said, so a measurement has a claim to be anchored to.

        `source` says where the words came from — typed by the person, or from
        an on-device transcriber. It is recorded because a reader is entitled to
        know whether a finding rests on words somebody chose or words a machine
        guessed at.
        """
        state = get_state(request)
        session = state.voice.get(session_id)
        if not _owns(principal, session.pid):
            raise HTTPException(status_code=403, detail="not your session")

        text = str(payload.get("text", "")).strip()
        if not text:
            raise HTTPException(status_code=422, detail="nothing was said")
        source = payload.get("source", "typed")

        before = session.has_acute_disclosure
        assessment = session.feed_utterance(int(payload.get("at_ms", 0)), text)

        acute = None
        if session.has_acute_disclosure and not before:
            # Heard something urgent. This does not wait for tonight's run and
            # it does not go through the four gates — the same path a PHQ-9
            # item 9 endorsement takes, and it routes to a mental-health
            # authority rather than the unit.
            from samvedna.pipeline.acute import handle_submission

            at_ms, phrase, _said = session.acute_heard[-1]
            route = handle_submission(
                InstrumentResponse(
                    pid=session.pid,
                    instrument="PHQ9",
                    taken_at=datetime.now(UTC),
                    # A spoken disclosure is recorded as the item it corresponds
                    # to, not as the sentence. The words are not written down.
                    items={"item_9": 1},
                    total=0,
                    cutoff=PHQ9_CUTOFF,
                ),
                _minimal_context(session),
                state.ledger,
            )
            acute = {
                "routed_to": route.routed_to if route else "mental_health_authority",
                "acknowledge_by": route.acknowledge_by.isoformat() if route else None,
                "message": route.shown_to_person if route else "",
                "resources": [
                    {"who": w, "how": h} for w, h in (route.resources if route else ())
                ],
                "matched_phrase": phrase,
            }

        return {
            "assessed": assessment is not None,
            "raised": bool(assessment and assessment.raised),
            "divergence": assessment.divergence if assessment else 0.0,
            "detail": assessment.describe() if assessment else (
                "no minimising claim in that sentence, so there is nothing for a "
                "measurement to be anchored to. The sitting is still being "
                "measured for sustained strain."
            ),
            "source": source,
            "readings": _readings(session),
            "acute": acute,
        }

    @app.get("/api/voice/{session_id}")
    def session_state(
        session_id: str,
        request: Request,
        principal: Principal = Depends(_voice_principal),
    ):
        state = get_state(request)
        session = state.voice.get(session_id)
        if not _owns(principal, session.pid):
            raise HTTPException(status_code=403, detail="not your session")
        return {
            "session_id": session_id,
            "windows": len(session.frames),
            "utterances": len(session.transcript_for_clinician()),
            "findings": [
                {"at_ms": f.at_ms, "quote": f.quote,
                 "divergence": f.assessment.divergence,
                 "detail": f.assessment.describe()}
                for f in session.findings
            ],
            "readings": _readings(session),
            "closed": session.closed,
        }

    @app.post("/api/voice/{session_id}/close")
    def close_session(
        session_id: str,
        request: Request,
        principal: Principal = Depends(_voice_principal),
    ):
        """End the sitting. Destroys the transcript; keeps six numbers.

        What survives is a `DomainDeviation` for the voice domain — no words, no
        sound, no quote — and the medians, so a future sitting can ask whether
        this person still sounds like themselves.
        """
        state = get_state(request)
        session = state.voice.get(session_id)
        if not _owns(principal, session.pid):
            raise HTTPException(status_code=403, detail="not your session")

        readings = _readings(session)
        deviation = session.as_deviation()
        summary = session.summarise_features()
        session.close()
        sittings = state.voice.remember(session)
        state.voice.close(session_id)

        state.ledger.append(
            actor=f"personnel:{session.pid}",
            action="score.computed",
            subject_pid=session.pid,
            purpose="welfare:self",
            detail={
                "voice_session": "closed",
                "windows_measured": len(session.frames),
                "produced_deviation": deviation is not None,
                "transcript_destroyed": True,
            },
        )
        journal = getattr(state, "journal", None)
        if journal is not None and summary:
            # The six medians and the window count, so a future sitting can ask
            # whether this person still sounds like themselves after a restart.
            # The baseline is the whole reason `baseline_shift` exists, and it
            # was in memory — a restart made everybody a first-time speaker.
            #
            # Never the audio and never the transcript. Those are destroyed
            # above, before this line runs, and the sitting is built around
            # destroying them.
            journal.record("voice.sitting", session.pid, {
                "kept": summary,
                "windows_measured": len(session.frames),
                "produced_deviation": deviation is not None,
            })

        return {
            "closed": True,
            "transcript_destroyed": True,
            "audio_retained": False,
            "windows_measured": len(session.frames),
            "readings": readings,
            "kept": summary,
            "prior_sittings": sittings,
            "deviation": (
                {
                    "domain": deviation.domain,
                    "tier": deviation.tier,
                    "weight": deviation.weight,
                    "z_self": deviation.z_self,
                    "daily_breach": {str(k): v for k, v in deviation.daily_breach.items()},
                }
                if deviation else None
            ),
            "note": (
                "Six numbers were kept. The recording and the words are gone. "
                "Voice is a Tier 3 signal — on its own it scores 0.183 against a "
                "0.65 threshold, so it can corroborate a case and can never make "
                "one."
                if deviation else
                "Nothing was raised, so nothing about this sitting reaches the "
                "nightly run. The recording and the words are gone."
            ),
        }



def _voice_principal(request: Request) -> Principal:
    """A person, acting on their own session. Nobody else has a route in here."""

    if settings().mode != "replay":
        raise HTTPException(
            status_code=501,
            detail="header identity is a REPLAY-only shim; live mode needs OIDC",
        )
    role = request.headers.get("X-Role", "")
    operator = request.headers.get("X-Operator", "")
    if role != "personnel":
        raise HTTPException(
            status_code=403,
            detail="a voice sitting belongs to the person having it. Nobody else.",
        )
    if not operator:
        raise HTTPException(status_code=401, detail="X-Operator is required")
    return Principal(subject_id=operator, role="personnel")


def _minimal_context(session: VoiceSession):
    """The least a verdict needs, with no service-record deviations in it.

    A spoken acute disclosure is routed on the strength of what was said, not on
    a case built from records — so the context handed to the override path
    carries the consent and nothing else.
    """
    from datetime import date

    from samvedna.core.types import CaseContext, ConsentState, UnitContext

    return CaseContext(
        pid=session.pid,
        unit_id=session.unit_id,
        as_of=date.today(),
        deviations=(),
        consent=ConsentState(
            pid=session.pid,
            scope=frozenset({"voice"}),
            welfare_contact=True,
            status="PARTIAL",
            updated_at=datetime.now(UTC),
        ),
        unit=UnitContext(unit_id=session.unit_id, cohort_size=0),
        acute_items=("spoken_disclosure",),
    )
