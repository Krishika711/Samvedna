"""What a person did, surviving a restart — and what must not survive it.

REPLAY holds the run in memory, so consent granted at 11:00, a questionnaire
completed at 11:05 and a voice sitting at 11:10 were all gone the moment the
process stopped. The officer's queue went back to whatever the 02:00 batch
produced, which during a demonstration looks exactly like the system having
broken.

The journal fixes that by recording **inputs** and replaying them through the
same gates. These tests defend the three properties that make it safe rather
than merely convenient:

* Verdicts are recomputed, never restored — so a threshold change in `config/`
  applies to somebody already decided.
* Only the minimum is stored: a score and an acute flag, never the nine item
  answers; six medians, never audio and never a transcript.
* It degrades to nothing. No crypto library, no key, or persistence switched
  off means the system runs as it always did rather than refusing to run.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from samvedna.api.app import create_app
from samvedna.api.bootstrap import build_state
from samvedna.db.journal import open_journal

PERSON = {"X-Role": "personnel", "X-Operator": "SELF", "X-Units": ""}
OFFICER = {
    "X-Role": "welfare_officer",
    "X-Operator": "WO-12",
    "X-Units": "CRPF-01,CRPF-02",
}
ALL_DOMAINS = [
    "leave", "deployment", "duty_roster", "transfer", "training",
    "workload", "self_report", "biometric", "voice",
]
MILD_BUT_ACUTE = [1, 1, 2, 1, 2, 1, 1, 2, 1]


def settings_on(target: Path, **overrides):
    """The real settings object, pointed at a temp database.

    Built with `model_copy` rather than a hand-written stub. The first version
    of this fixture declared its own dataclass with the six fields these tests
    care about, and `build_state` promptly asked for `model_dir` — enumerating
    somebody else's configuration is a losing game, and a stub that drifts
    tests a system that does not exist.
    """
    from samvedna.config.flags import settings as real

    return real().model_copy(
        update={
            "database_url": f"sqlite+aiosqlite:///{target}",
            # The suite disables persistence; these tests are the ones that
            # need it. See the note in `tests/conftest.py`.
            "persist_state": True,
            **overrides,
        }
    )


@pytest.fixture
def db(tmp_path: Path, monkeypatch) -> Path:
    """A journal on a temp database, shared by both processes in a restart test."""
    target = tmp_path / "state.db"
    live = settings_on(target)
    import samvedna.api.app as app_mod
    import samvedna.api.bootstrap as bootstrap
    import samvedna.api.voice_routes as voice_mod
    import samvedna.config.flags as flags

    for module in (flags, bootstrap, app_mod, voice_mod):
        monkeypatch.setattr(module, "settings", lambda: live, raising=False)
    return target


def files(db: Path) -> bytes:
    """Every byte SQLite has put on disk, main file and sidecars."""
    blob = b""
    for path in (db, Path(f"{db}-wal"), Path(f"{db}-shm")):
        if path.exists():
            blob += path.read_bytes()
    return blob


# ------------------------------------------------------------- the restart --

def test_consent_an_assessment_and_a_sitting_all_survive(db):
    """The whole point, across two processes sharing one database."""
    # --- first process ---
    first, _ = build_state(units=4, strength=60, seed=26186)
    assert first.journal is not None, "the journal did not open"
    c1 = TestClient(create_app(first))

    pid = c1.get("/api/me/whoami", headers=PERSON).json()["pid"]
    c1.post("/api/consent", headers=PERSON, json={
        "pid": pid, "locale": "en", "scope": ALL_DOMAINS, "welfare_contact": True,
    })
    c1.post(f"/api/me/{pid}/assessment", headers=PERSON,
            json={"items": MILD_BUT_ACUTE})
    sid = c1.post("/api/voice/session", headers=PERSON,
                  json={"pid": pid}).json()["session_id"]
    c1.post(f"/api/voice/{sid}/audio", headers=PERSON,
            json={"pcm16": _voiced_window(), "at_ms": 0})
    c1.post(f"/api/voice/{sid}/close", headers=PERSON, json={})

    before = len(c1.get("/api/caseload", headers=OFFICER).json()["cases"])
    assert len(first.journal) == 3

    # --- second process, same database ---
    second, _ = build_state(units=4, strength=60, seed=26186)
    c2 = TestClient(create_app(second))

    scope = getattr(second.consent.state_for(pid), "scope", ())
    assert "voice" in scope and "self_report" in scope, "consent was lost"

    case = next(c for c in second.run.cases if c.pid == pid)
    assert case.decision == "IMMEDIATE_ESCALATE", "the acute verdict was lost"
    assert len(c2.get("/api/caseload", headers=OFFICER).json()["cases"]) == before

    assert second.voice.history_length(pid) == 1, "the voice baseline was lost"
    reopened = c2.post("/api/voice/session", headers=PERSON, json={"pid": pid})
    assert reopened.status_code == 200
    assert reopened.json()["prior_sittings"] == 1


def test_no_verdict_is_ever_written_to_the_journal(db):
    """You cannot restore what you never stored.

    This is the structural guarantee behind "recomputed, not restored". The
    journal holds the score and the acute flag; a `CaseRecord`'s decision,
    gate values and composite appear nowhere in it, so a startup has no
    alternative to running the gates again. Storing the verdict would mean a
    governance-approved threshold change in `config/` silently failed to apply
    to everybody already decided, which makes the approval meaningless.

    The obvious dynamic test for this — freeze escalation and check the verdict
    moves — does not work, and why is worth recording: `decide()` checks
    `ctx.acute_items` *before* the freeze, so an acute disclosure is
    deliberately not suppressed by model drift. Every degradation in this
    system moves it toward saying less, except the one path that exists for
    somebody at risk today.
    """
    state, _ = build_state(units=4, strength=60, seed=26186)
    client = TestClient(create_app(state))
    pid = client.get("/api/me/whoami", headers=PERSON).json()["pid"]
    client.post("/api/consent", headers=PERSON, json={
        "pid": pid, "locale": "en", "scope": ALL_DOMAINS, "welfare_contact": True,
    })
    client.post(f"/api/me/{pid}/assessment", headers=PERSON,
                json={"items": MILD_BUT_ACUTE})

    forbidden = {"decision", "verdict", "gates", "composite", "escalated",
                 "named_to_an_officer", "failed_gates"}
    for event in state.journal.replay():
        leaked = forbidden & set(event.payload)
        assert not leaked, f"{event.kind} journalled a derived verdict: {leaked}"

    # And the raw file carries no verdict string either.
    raw = files(db)
    for decision in (b"IMMEDIATE_ESCALATE", b"ESCALATE", b"MONITOR", b"NO_FLAG"):
        assert decision not in raw, f"{decision!r} was written to disk"


def test_the_replayed_verdict_comes_from_the_gates(db):
    """The restored decision must match what the gates say about the evidence.

    Not merely "a verdict exists" — the same context, decided again now, must
    produce the same answer. If the replay had restored a stored value, these
    two could differ and nobody would know which one a screen was showing.
    """
    from samvedna.core.verdict import decide

    first, _ = build_state(units=4, strength=60, seed=26186)
    c1 = TestClient(create_app(first))
    pid = c1.get("/api/me/whoami", headers=PERSON).json()["pid"]
    c1.post("/api/consent", headers=PERSON, json={
        "pid": pid, "locale": "en", "scope": ALL_DOMAINS, "welfare_contact": True,
    })
    c1.post(f"/api/me/{pid}/assessment", headers=PERSON,
            json={"items": MILD_BUT_ACUTE})

    second, _ = build_state(units=4, strength=60, seed=26186)
    case = next(c for c in second.run.cases if c.pid == pid)
    assert case.ctx is not None

    recomputed = decide(case.ctx, escalation_frozen=second.run.escalation_frozen)
    assert recomputed.decision == case.verdict.decision
    assert recomputed.composite == pytest.approx(case.verdict.composite)
    # And the self-report the journal restored is in the evidence it decided on.
    assert any(d.domain == "self_report" for d in case.ctx.deviations)


# ----------------------------------------------------- what is not stored --

def test_the_item_answers_never_reach_the_disk(db):
    """An officer may not see raw psychometric responses. Nor may this table."""
    state, _ = build_state(units=4, strength=60, seed=26186)
    client = TestClient(create_app(state))
    pid = client.get("/api/me/whoami", headers=PERSON).json()["pid"]
    client.post("/api/consent", headers=PERSON, json={
        "pid": pid, "locale": "en", "scope": ALL_DOMAINS, "welfare_contact": True,
    })
    client.post(f"/api/me/{pid}/assessment", headers=PERSON,
                json={"items": MILD_BUT_ACUTE})

    events = state.journal.replay()
    submitted = next(e for e in events if e.kind == "assessment.submitted")
    assert set(submitted.payload) == {"instrument", "total", "cutoff", "acute"}
    for key in submitted.payload:
        assert not key.startswith("item"), f"item answers were journalled: {key}"


def test_nothing_sensitive_is_readable_on_disk(db):
    """With the database file, an attacker gets pseudonyms and ciphertext."""
    state, _ = build_state(units=4, strength=60, seed=26186)
    client = TestClient(create_app(state))
    pid = client.get("/api/me/whoami", headers=PERSON).json()["pid"]
    client.post("/api/consent", headers=PERSON, json={
        "pid": pid, "locale": "en", "scope": ALL_DOMAINS, "welfare_contact": True,
    })
    client.post(f"/api/me/{pid}/assessment", headers=PERSON,
                json={"items": MILD_BUT_ACUTE})

    raw = files(db)
    assert raw, "nothing was written, so this test proves nothing"
    for secret in (b'"total"', b"self_report", b"IMMEDIATE", b"jitter"):
        assert secret not in raw, f"{secret!r} is readable in the journal file"
    # The pid is not PII — an HMAC under a rotating salt — and is a primary key.
    assert pid.encode() in raw


def test_a_voice_sitting_journals_medians_and_nothing_else(db):
    """No audio and no transcript, because both are destroyed before this runs."""
    state, _ = build_state(units=4, strength=60, seed=26186)
    client = TestClient(create_app(state))
    pid = client.get("/api/me/whoami", headers=PERSON).json()["pid"]
    client.post("/api/consent", headers=PERSON, json={
        "pid": pid, "locale": "en", "scope": ALL_DOMAINS, "welfare_contact": True,
    })
    sid = client.post("/api/voice/session", headers=PERSON,
                      json={"pid": pid}).json()["session_id"]
    client.post(f"/api/voice/{sid}/audio", headers=PERSON,
                json={"pcm16": _voiced_window(), "at_ms": 0})
    client.post(f"/api/voice/{sid}/utterance", headers=PERSON,
                json={"text": "I am fine, no problems at all", "at_ms": 500,
                      "source": "typed"})
    client.post(f"/api/voice/{sid}/close", headers=PERSON, json={})

    sitting = next(e for e in state.journal.replay() if e.kind == "voice.sitting")
    assert set(sitting.payload) == {"kept", "windows_measured", "produced_deviation"}
    assert sitting.payload["kept"], "no medians were kept"
    blob = json.dumps(sitting.payload)
    assert "I am fine" not in blob, "the transcript was journalled"
    assert "pcm" not in blob and "audio" not in blob


# --------------------------------------------------------------- erasure --

def test_withdrawal_erases_the_journal_not_just_a_flag(db):
    """A withdrawal that leaves a sealed score on disk has erased nothing."""
    state, _ = build_state(units=4, strength=60, seed=26186)
    client = TestClient(create_app(state))
    pid = client.get("/api/me/whoami", headers=PERSON).json()["pid"]
    client.post("/api/consent", headers=PERSON, json={
        "pid": pid, "locale": "en", "scope": ALL_DOMAINS, "welfare_contact": True,
    })
    client.post(f"/api/me/{pid}/assessment", headers=PERSON,
                json={"items": MILD_BUT_ACUTE})
    assert len(state.journal) >= 2

    body = client.post(f"/api/consent/{pid}/withdraw", headers=PERSON).json()
    assert body["journal_events_erased"] >= 2
    assert [e for e in state.journal.replay() if e.pid == pid] == []
    assert pid.encode() not in files(db), "the pid survived erasure on disk"


# ----------------------------------------------------- degrading to nothing --

def test_persistence_can_be_switched_off(tmp_path):
    off = settings_on(tmp_path / "x.db", persist_state=False)
    assert open_journal(off) is None


def test_no_key_means_no_persistence_not_a_refusal_to_run(tmp_path):
    """A welfare run must not stop because a database was unavailable."""
    from samvedna.db.keys import KeyfileProvider

    assert open_journal(
        settings_on(tmp_path / "x.db"),
        provider=KeyfileProvider(tmp_path / "does-not-exist.key"),
    ) is None


def test_a_rotated_salt_epoch_is_not_replayed(db, monkeypatch):
    """A pid from a rotated epoch is not the same pid.

    Replaying its events would attach somebody's questionnaire to a stranger.
    """
    first, _ = build_state(units=4, strength=60, seed=26186)
    c1 = TestClient(create_app(first))
    pid = c1.get("/api/me/whoami", headers=PERSON).json()["pid"]
    c1.post("/api/consent", headers=PERSON, json={
        "pid": pid, "locale": "en", "scope": ALL_DOMAINS, "welfare_contact": True,
    })
    assert len(first.journal.replay()) == 1

    after = open_journal(
        settings_on(db, pseudonym_salt="a-new-epoch-salt")
    )
    assert after is not None
    assert after.replay() == (), "events from a rotated epoch were replayed"


def _voiced_window(seconds: float = 2.0, hz: float = 150.0) -> str:
    import base64

    import numpy as np

    from samvedna.analytics.voice.acoustics import SAMPLE_RATE

    n = int(seconds * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    wave = np.sin(2 * np.pi * hz * t)
    wave = wave / max(1e-9, float(np.abs(wave).max()))
    return base64.b64encode((wave * 32000).astype("<i2").tobytes()).decode()


def test_no_database_file_or_sidecar_ever_ships(tmp_path):
    """The archive must not carry the journal, in any of its three files.

    `EXCLUDE_SUFFIXES` correctly held `".db"` and the write-ahead log shipped
    anyway, because `Path("samvedna.db-wal").suffix` is `".db-wal"`. Both
    sidecars went into an archive — 103 KB of WAL and 32 KB of shm. That one
    happened to be checkpointed and empty, which is luck: a WAL exists to hold
    writes the main file has not taken yet, and here those are sealed
    questionnaire scores and voice medians.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
    import package

    for name in (
        "samvedna.db",
        "samvedna.db-wal",
        "samvedna.db-shm",
        "anything.sqlite",
        "anything.sqlite-wal",
        "state.DB-WAL",
    ):
        lowered = name.lower()
        excluded = (
            name in package.EXCLUDE_NAMES
            or Path(name).suffix.lower() in package.EXCLUDE_SUFFIXES
            or any(m in lowered for m in package.EXCLUDE_CONTAINING)
        )
        assert excluded, f"{name} would ship"

    # And nothing legitimate is caught by the substring rule.
    for keep in ("README.md", "app.py", "package-lock.json", "globals.css"):
        lowered = keep.lower()
        assert not any(m in lowered for m in package.EXCLUDE_CONTAINING), keep
