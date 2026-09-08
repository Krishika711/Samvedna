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
    return state, force
