"""Assemble a complete, running console from a REPLAY night.

`samvedna serve` calls this. It generates a synthetic force, runs the real
nightly pipeline over it, and builds the directory that L5 will resolve pids
against — so every console screen is rendered from an actual run record rather
than from a fixture of what a run record might look like.

The directory built here is the *only* place a pid maps to a person, and it is
constructed after the pipeline has finished, from the generator's own roster. In
production this is a service inside the unit's records boundary; the shape is the
same and nothing downstream can tell the difference.
"""
from __future__ import annotations

from samvedna.analytics.reviewers.panel import Panel
from samvedna.api.app import AppState
from samvedna.config.flags import settings
from samvedna.config.weights import ALL_DOMAINS
from samvedna.db.journal import open_journal
from samvedna.disclosure.reidentify import Identity
from samvedna.ingest.connectors.replay import connectors_for
from samvedna.ingest.generator import Force, generate_force
from samvedna.ingest.pseudonymise import Pseudonymiser
from samvedna.pipeline.dag import run_nightly

__all__ = ["build_state"]

# Placeholder roster names for the REPLAY directory. Obviously synthetic, and
# never drawn from any real roll.
GIVEN = ("Arjun", "Bikram", "Chetan", "Devendra", "Farhan", "Gurpreet", "Harish",
         "Imran", "Jaswant", "Kiran", "Lalit", "Manoj", "Naveen", "Omkar",
         "Pravin", "Rajesh", "Sunil", "Tejinder", "Umesh", "Vikram")
FAMILY = ("Bhat", "Chauhan", "Deshmukh", "Gill", "Iyer", "Joshi", "Kaur", "Lal",
          "Mehta", "Nair", "Pillai", "Rao", "Sharma", "Thakur", "Verma", "Yadav")


def _identity_for(index: int, person) -> Identity:
    return Identity(
        service_number=person.service_number,
        name=f"{GIVEN[index % len(GIVEN)]} {FAMILY[(index // len(GIVEN)) % len(FAMILY)]}",
        rank=person.rank,
        unit_id=person.unit_id,
        contact=f"{person.unit_id} exchange, ext {4000 + (index % 900)}",
    )


def _replay_journal(state: AppState) -> dict[str, int]:
    """Re-apply what people did, through the same code paths as the first time.

    Order matters and is the reason this is a loop over events rather than three
    passes: a person may grant consent, submit an assessment, then narrow their
    consent again, and applying all the consents before all the assessments
    would decide their case under permissions they had since withdrawn.

    Verdicts are **recomputed, not restored**. The journal holds the score and
    the acute flag; the gates run again here against whatever `config/` now
    says. Storing the verdict instead would mean a governance-approved
    threshold change silently failed to apply to anybody already decided.
    """
    journal = state.journal
    if journal is None:
        return {}

    applied: dict[str, int] = {}

    def bump(kind: str) -> None:
        applied[kind] = applied.get(kind, 0) + 1

    for event in journal.replay():
        pid, payload = event.pid, event.payload
        try:
            if event.kind == "consent.granted":
                state.consent.enrol_with_receipt(
                    pid,
                    tuple(payload.get("scope", ())),
                    welfare_contact=bool(payload.get("welfare_contact", False)),
                    locale=str(payload.get("locale", "en")),
                    pilot_mode=settings().consent_pilot_mode,
                )
                bump(event.kind)

            elif event.kind == "consent.withdrawn":
                state.consent.revoke(pid)
                bump(event.kind)

            elif event.kind == "assessment.submitted":
                if _reapply_assessment(state, pid, payload):
                    bump(event.kind)

            elif event.kind == "voice.sitting":
                kept = payload.get("kept") or {}
                if kept:
                    # Straight into the history the next sitting compares
                    # against. Without this a restart made everybody a
                    # first-time speaker and `baseline_shift` had nothing to
                    # work with — the one reading that needs more than today.
                    state.voice.restore(pid, kept)
                    bump(event.kind)
        except Exception:
            # One unreplayable event must not stop the process from starting.
            # It stays on disk for an auditor; the rest of the journal applies.
            continue

    return applied


def _reapply_assessment(state: AppState, pid: str, payload: dict) -> bool:
    """Re-decide one case with a recorded self-report folded back in."""
    from samvedna.api.app import rebuild_with_assessment

    if state.run is None:
        return False
    return rebuild_with_assessment(
        state,
        pid,
        total=int(payload.get("total", 0)),
        cutoff=int(payload.get("cutoff", 10)),
        acute=bool(payload.get("acute", False)),
    )


def build_state(
    *,
    units: int = 4,
    strength: int = 60,
    seed: int = 26186,
    model_dir: str | None = None,
    degrade: str | None = None,
    break_reviewer: str | None = None,
    drift: bool = False,
) -> tuple[AppState, Force]:
    force = generate_force(units=units, strength=strength, seed=seed)
    state = AppState()
    pseudonymiser = Pseudonymiser(settings().pseudonym_salt, on=force.as_of)

    # Which domains does each person actually have records in? Built in one
    # pass over the records rather than by asking that question once per person
    # per domain.
    #
    # The obvious version of this loop scanned `force.records` inside a
    # comprehension over personnel and domains, which is O(people x domains x
    # records) — and because the generator emits records in proportion to
    # headcount, that is quadratic in cohort size. It cost 69 ms per person at
    # 240 people and 117 ms at 480, which made the whole system look
    # superlinear when the nightly pipeline itself is not. Startup for a
    # brigade-sized cohort was minutes of a nested scan nobody had noticed.
    domains_by_service_number: dict[str, set[str]] = {}
    for record in force.records:
        domains_by_service_number.setdefault(record.pid, set()).add(record.domain)

    for index, person in enumerate(force.personnel):
        pid = pseudonymiser.pid(person.service_number)
        present = domains_by_service_number.get(person.service_number, set())
        # Kept ordered by ALL_DOMAINS rather than by set iteration order, so the
        # enrolled scope is deterministic across runs.
        scope = tuple(d for d in ALL_DOMAINS if d in present)
        state.consent.enrol(pid, scope, welfare_contact=True)
        state.directory[pid] = _identity_for(index, person)

    panel = Panel()
    if break_reviewer:
        class _Broken:
            name = break_reviewer

            def review(self, ctx):
                raise RuntimeError(f"{break_reviewer} disabled")

        from samvedna.analytics.reviewers.panel import default_panel

        panel = Panel(tuple(
            _Broken() if r.name == break_reviewer else r for r in default_panel()
        ))

    state.run = run_nightly(
        connectors=connectors_for(force, drop={degrade: 0.45} if degrade else None),
        pseudonymiser=pseudonymiser,
        consent=state.consent,
        ledger=state.ledger,
        as_of=force.as_of,
        mode="replay",
        panel=panel,
        model_dir=model_dir or settings().model_dir,
        drift_exceeded=drift,
    )
    # Persistence last, and after the run, deliberately. The journal replays
    # onto cases that already have a screening context, so the nightly run has
    # to have happened first — an assessment cannot be re-decided against a
    # baseline that does not exist yet.
    state.journal = open_journal(settings())
    if state.journal is not None:
        applied = _replay_journal(state)
        if applied:
            print(
                "  restored: "
                + ", ".join(f"{n} {kind}" for kind, n in sorted(applied.items()))
            )

    return state, force
