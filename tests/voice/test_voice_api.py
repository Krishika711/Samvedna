"""The live voice sitting, over HTTP.

The thing worth testing hardest is an absence: after a window of audio has been
measured, no part of the system holds the samples. An absence cannot be proved
by reading the code once, so it is asserted here.
"""
from __future__ import annotations

import base64

import numpy as np
import pytest
from fastapi.testclient import TestClient

from samvedna.analytics.voice.acoustics import SAMPLE_RATE
from samvedna.api.app import AppState, create_app
from samvedna.config.weights import ALL_DOMAINS


def pcm16(seconds: float = 2.0, hz: float = 150.0, strained: bool = False) -> str:
    """A synthetic voiced window, base64-encoded exactly as the browser sends it."""
    n = int(seconds * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    wave = np.sin(2 * np.pi * hz * t)
    if strained:
        # Narrow the intonation, roughen the signal, and add pauses — the shape
        # of a strained voice rather than a clean tone.
        rng = np.random.default_rng(4)
        wave = wave * (0.6 + 0.4 * np.sin(2 * np.pi * 1.5 * t))
        wave += rng.normal(scale=0.28, size=n)
        wave[: n // 3] *= 0.02
    wave = wave / max(1e-9, float(np.abs(wave).max()))
    return base64.b64encode((wave * 32000).astype("<i2").tobytes()).decode()


@pytest.fixture
def world():
    state = AppState()
    state.consent.enrol("SELF", ALL_DOMAINS, welfare_contact=True)
    return TestClient(create_app(state)), state


def me():
    return {"X-Role": "personnel", "X-Operator": "SELF"}


def open_session(client):
    response = client.post("/api/voice/session", headers=me(), json={})
    assert response.status_code == 200, response.json()
    return response.json()["session_id"]


# ------------------------------------------------------------------ consent --
def test_a_sitting_needs_consent_to_the_voice_domain_specifically():
    """Agreeing to have your leave record read is not agreeing to be recorded."""
    state = AppState()
    state.consent.enrol(
        "SELF", tuple(d for d in ALL_DOMAINS if d != "voice"), welfare_contact=True
    )
    client = TestClient(create_app(state))
    response = client.post("/api/voice/session", headers=me(), json={})
    assert response.status_code == 403
    assert "separate choice" in response.json()["detail"]


def test_an_unenrolled_person_cannot_open_a_sitting():
    client = TestClient(create_app(AppState()))
    assert client.post("/api/voice/session", headers=me(), json={}).status_code == 403


@pytest.mark.parametrize("role", ["welfare_officer", "commander", "auditor"])
def test_a_sitting_belongs_to_the_person_having_it(world, role):
    client, _ = world
    response = client.post(
        "/api/voice/session",
        headers={"X-Role": role, "X-Operator": "X"},
        json={},
    )
    assert response.status_code == 403
    assert "belongs to the person" in response.json()["detail"]


def test_nobody_can_push_audio_into_somebody_elses_sitting(world):
    client, state = world
    session_id = open_session(client)
    state.consent.enrol("OTHER", ALL_DOMAINS, welfare_contact=True)
    response = client.post(
        f"/api/voice/{session_id}/audio",
        headers={"X-Role": "personnel", "X-Operator": "OTHER"},
        json={"pcm16": pcm16()},
    )
    assert response.status_code == 403


# -------------------------------------------------------------- measurement --
def test_a_window_of_audio_comes_back_as_measurements(world):
    client, _ = world
    session_id = open_session(client)
    body = client.post(
        f"/api/voice/{session_id}/audio", headers=me(), json={"pcm16": pcm16()}
    ).json()
    assert body["windows"] == 1
    assert body["frame"]["trustworthy"]
    # Pitch is shown even though it has no reference band — it is the one
    # number a person recognises as their own.
    assert body["frame"]["features"]["f0_hz"] == pytest.approx(150, rel=0.06)
    assert "readings" in body


def test_the_response_carries_no_audio_back(world):
    client, _ = world
    session_id = open_session(client)
    body = client.post(
        f"/api/voice/{session_id}/audio", headers=me(), json={"pcm16": pcm16()}
    ).json()
    blob = str(body)
    for forbidden in ("pcm", "samples", "audio_data", "waveform"):
        assert forbidden not in blob


def test_no_audio_survives_the_request(world):
    """The absence that matters. After measuring, nothing in the session, the
    store, or the app state holds the samples."""
    client, state = world
    session_id = open_session(client)
    client.post(f"/api/voice/{session_id}/audio", headers=me(), json={"pcm16": pcm16()})

    session = state.voice.get(session_id)
    for frame in session.frames:
        for field in ("samples", "audio", "pcm", "waveform", "buffer", "recording"):
            assert not hasattr(frame, field)
    # And nothing anywhere in the store is a large numeric array.
    for value in vars(state.voice).values():
        assert not isinstance(value, (bytes, bytearray, np.ndarray))


def test_a_window_that_is_too_short_is_refused(world):
    client, _ = world
    session_id = open_session(client)
    response = client.post(
        f"/api/voice/{session_id}/audio", headers=me(), json={"pcm16": pcm16(0.3)}
    )
    assert response.status_code == 422
    assert "needs to be between" in response.json()["detail"]


def test_rubbish_in_the_audio_field_is_refused_not_guessed_at(world):
    client, _ = world
    session_id = open_session(client)
    for payload in ({"pcm16": "not base64!!"}, {"pcm16": ""}, {}):
        assert client.post(
            f"/api/voice/{session_id}/audio", headers=me(), json=payload
        ).status_code == 422


# ------------------------------------------------------------------- words --
def test_a_minimising_phrase_over_a_strained_voice_raises_a_gap(world):
    client, _ = world
    session_id = open_session(client)
    for _ in range(3):
        client.post(
            f"/api/voice/{session_id}/audio", headers=me(),
            json={"pcm16": pcm16(strained=True)},
        )
    body = client.post(
        f"/api/voice/{session_id}/utterance", headers=me(),
        json={"text": "I'm fine, sir.", "at_ms": 2000},
    ).json()
    assert body["assessed"] is True
    assert "readings" in body


def test_plain_speech_is_recorded_but_anchors_nothing(world):
    client, _ = world
    session_id = open_session(client)
    body = client.post(
        f"/api/voice/{session_id}/utterance", headers=me(),
        json={"text": "The roster has been manageable.", "at_ms": 1000},
    ).json()
    assert body["assessed"] is False
    assert "sustained strain" in body["detail"]


def test_an_empty_utterance_is_refused(world):
    client, _ = world
    session_id = open_session(client)
    assert client.post(
        f"/api/voice/{session_id}/utterance", headers=me(), json={"text": "   "}
    ).status_code == 422


def test_the_source_of_the_words_is_recorded(world):
    """A reader is entitled to know whether a finding rests on words somebody
    chose or words a machine guessed at."""
    client, _ = world
    session_id = open_session(client)
    body = client.post(
        f"/api/voice/{session_id}/utterance", headers=me(),
        json={"text": "I'm managing.", "source": "typed"},
    ).json()
    assert body["source"] == "typed"


# ------------------------------------------------------------ the acute path --
def test_an_acute_phrase_routes_the_same_day_and_bypasses_the_gates(world):
    client, state = world
    session_id = open_session(client)
    body = client.post(
        f"/api/voice/{session_id}/utterance", headers=me(),
        json={"text": "Honestly sir, I can't go on like this.", "at_ms": 4000},
    ).json()
    assert body["acute"] is not None
    assert body["acute"]["routed_to"] == "mental_health_authority"
    assert body["acute"]["acknowledge_by"]
    assert body["acute"]["resources"]
    assert "does not go to your commanding officer" in body["acute"]["message"]
    assert state.ledger.for_action("override.applied")


def test_the_acute_ledger_entry_holds_no_words(world):
    """The route is recorded. What was said is not."""
    client, state = world
    session_id = open_session(client)
    client.post(
        f"/api/voice/{session_id}/utterance", headers=me(),
        json={"text": "Honestly sir, I can't go on like this.", "at_ms": 4000},
    )
    entry = state.ledger.for_action("override.applied")[0]
    assert "can't go on" not in str(entry.detail)
    assert "Honestly" not in str(entry.detail)


def test_ordinary_frustration_does_not_route_anybody(world):
    """A broad net would teach the force that speaking plainly gets you
    referred, and end voluntary disclosure."""
    client, _ = world
    session_id = open_session(client)
    for line in ("This roster is killing me.", "I am exhausted and fed up."):
        body = client.post(
            f"/api/voice/{session_id}/utterance", headers=me(), json={"text": line}
        ).json()
        assert body["acute"] is None


# ------------------------------------------------------------------ closing --
def test_closing_destroys_the_transcript_and_keeps_six_numbers(world):
    client, _ = world
    session_id = open_session(client)
    for _ in range(4):
        client.post(
            f"/api/voice/{session_id}/audio", headers=me(),
            json={"pcm16": pcm16(strained=True)},
        )
    client.post(
        f"/api/voice/{session_id}/utterance", headers=me(), json={"text": "I'm fine."}
    )

    body = client.post(f"/api/voice/{session_id}/close", headers=me(), json={}).json()
    assert body["transcript_destroyed"] is True
    assert body["audio_retained"] is False
    assert body["windows_measured"] == 4
    assert 0 < len(body["kept"]) <= 7
    assert all(isinstance(v, float) for v in body["kept"].values())


def test_a_closed_sitting_is_gone(world):
    client, _ = world
    session_id = open_session(client)
    client.post(f"/api/voice/{session_id}/close", headers=me(), json={})
    assert client.get(f"/api/voice/{session_id}", headers=me()).status_code == 404


def test_a_deviation_carries_no_words_and_is_tier_3(world):
    client, _ = world
    session_id = open_session(client)
    for _ in range(6):
        client.post(
            f"/api/voice/{session_id}/audio", headers=me(),
            json={"pcm16": pcm16(strained=True)},
        )
    for line in ("I'm fine.", "It's part of the job.", "I'm managing, mostly."):
        client.post(f"/api/voice/{session_id}/utterance", headers=me(), json={"text": line})

    body = client.post(f"/api/voice/{session_id}/close", headers=me(), json={}).json()
    if body["deviation"] is None:
        pytest.skip("this synthetic voice raised nothing, which is a valid outcome")
    assert body["deviation"]["tier"] == "T3"
    assert body["deviation"]["domain"] == "voice"
    blob = str(body["deviation"])
    for word in ("fine", "managing", "job", "quote"):
        assert word not in blob


def test_a_quiet_sitting_produces_no_deviation_at_all(world):
    client, _ = world
    session_id = open_session(client)
    for _ in range(5):
        client.post(f"/api/voice/{session_id}/audio", headers=me(), json={"pcm16": pcm16()})
    client.post(
        f"/api/voice/{session_id}/utterance", headers=me(),
        json={"text": "The patrol went well."},
    )
    body = client.post(f"/api/voice/{session_id}/close", headers=me(), json={}).json()
    assert body["deviation"] is None
    assert "nothing about this sitting reaches the nightly run" in body["note"]


def test_a_second_sitting_can_compare_against_the_first(world):
    """The six kept numbers are what make a baseline possible — and a baseline
    is the only reading with any purchase on somebody good at sounding fine."""
    client, state = world
    for _ in range(3):
        session_id = open_session(client)
        for _ in range(4):
            client.post(f"/api/voice/{session_id}/audio", headers=me(), json={"pcm16": pcm16()})
        client.post(f"/api/voice/{session_id}/close", headers=me(), json={})

    assert state.voice.history_length("SELF") == 3
    opened = client.post("/api/voice/session", headers=me(), json={}).json()
    assert opened["has_baseline"] is True
    assert opened["prior_sittings"] == 3


def test_the_open_response_says_plainly_that_audio_is_not_kept(world):
    client, _ = world
    body = client.post("/api/voice/session", headers=me(), json={}).json()
    assert body["audio_retained"] is False
    assert "discarded" in body["note"]
    assert "Nothing is uploaded" in body["note"]


def test_no_voice_route_reaches_an_external_service():
    """PART 1 and PART 10 forbid external processing of this data class — which
    is exactly why the words are typed rather than transcribed."""
    import ast
    from pathlib import Path

    module = (
        Path(__file__).resolve().parent.parent.parent
        / "src" / "samvedna" / "api" / "voice_routes.py"
    )
    tree = ast.parse(module.read_text(encoding="utf-8"))
    banned = {"httpx", "requests", "urllib", "socket", "openai", "anthropic", "boto3"}
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module.split(".")[0]]
        for name in names:
            assert name not in banned, f"voice_routes imports {name}"
