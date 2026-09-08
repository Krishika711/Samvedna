"""PART 8.12 — the eight workflow acceptance criteria, one test each, by number.

Every one of these is proved elsewhere too, inside the module that owns the
behaviour. This file exists so that a reviewer holding the master prompt can run
one command and see the eight criteria answered in the order they were written,
rather than trusting that they are covered somewhere across four hundred tests.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from tests.conftest import case, deviation

from samvedna.analytics.reviewers.panel import Panel
from samvedna.analytics.reviewers.risk_advocate import RiskAdvocate
from samvedna.analytics.reviewers.welfare_context import WelfareContext
from samvedna.config.weights import ALL_DOMAINS
from samvedna.core.types import Gate, Verdict
from samvedna.core.verdict import decide
from samvedna.disclosure.audit import Ledger
from samvedna.disclosure.consent import ConsentRegistry
from samvedna.disclosure.kanon import SUPPRESSED, aggregate, k_min
from samvedna.disclosure.rbac import Principal
from samvedna.disclosure.reidentify import DisclosureRefused, Identity, disclose
from samvedna.ingest.connectors.replay import connectors_for
from samvedna.ingest.dp import Budget
from samvedna.ingest.generator import generate_force
from samvedna.ingest.pseudonymise import Pseudonymiser
from samvedna.pipeline.dag import run_nightly
from samvedna.pipeline.outcomes import CaseBook, OutcomeRequired

AT = datetime(2026, 9, 5, 7, 0, tzinfo=UTC)
SUSTAINED = {7: 1.0, 30: 1.0, 90: 0.9}


def officer():
    return Principal("WO-12", "welfare_officer", frozenset({"UNIT-01"}))


@pytest.fixture(scope="module")
def world():
    force = generate_force(units=3, strength=30, seed=8812)
    ps = Pseudonymiser("acceptance-salt", on=force.as_of)
    return force, ps


def registry_for(force, ps):
    registry = ConsentRegistry()
    for person in force.personnel:
        registry.enrol(ps.pid(person.service_number), ALL_DOMAINS, welfare_contact=True)
    return registry


def nightly(force, ps, registry, ledger, panel=None, **kw):
    return run_nightly(
        connectors=connectors_for(force),
        pseudonymiser=ps,
        consent=registry,
        ledger=ledger,
        as_of=force.as_of,
        panel=panel or Panel(),
        model_dir="/nonexistent",
        **kw,
    )


# --- 1 ------------------------------------------------------------------------
def test_criterion_1_revocation_clears_the_watchlist_and_cancels_queued_alerts(world):
    """A revocation in the app removes the pid from the next run's watchlist and
    cancels any queued-but-undelivered alert."""
    force, ps = world
    registry = registry_for(force, ps)
    ledger = Ledger()

    first = nightly(force, ps, registry, ledger)
    watched = {c.pid for c in first.monitored()} | {c.pid for c in first.caseload()}
    assert watched, "the run must put somebody under watch to make this meaningful"

    victim = next(iter(watched))
    registry.revoke(victim, at=AT)

    second = nightly(force, ps, registry, Ledger())
    assert victim not in {c.pid for c in second.cases}

    # And a queued alert for them can no longer be delivered: disclosure refuses.
    with pytest.raises(DisclosureRefused) as excinfo:
        disclose(
            pid=victim,
            verdict=Verdict("ESCALATE", "queued before revocation",
                            {"evidence": Gate("evidence", 1.0, 0.65, True, "", {})},
                            (), (), 0.9),
            principal=officer(), purpose="welfare:contact", unit_id="UNIT-01",
            directory=type("D", (), {"resolve": lambda self, pid: Identity(
                "x", "y", "z", "UNIT-01", "c")})(),
            ledger=Ledger(), consent=registry, at=AT,
        )
    assert "no consent basis" in str(excinfo.value)


# --- 2 ------------------------------------------------------------------------
def test_criterion_2_a_cohort_below_five_is_suppressed_not_rounded():
    cell = aggregate("fatigue index", [0.5] * (k_min() - 1), Budget(total=100))
    assert cell.suppressed
    assert cell.display == SUPPRESSED
    assert cell.value is None
    assert "n" not in cell.to_dict()


# --- 3 ------------------------------------------------------------------------
def test_criterion_3_a_case_cannot_be_closed_without_an_outcome_and_blocks_the_list():
    book, ledger = CaseBook(), Ledger()
    with pytest.raises(OutcomeRequired):
        book.close("pid-1", "", officer(), ledger, at=AT)

    book.record_contact("pid-1", officer(), ledger, at=AT)
    assert book.blocking(("pid-1",)) == ("pid-1",)
    book.close("pid-1", "supported", officer(), ledger, at=AT)
    assert book.blocking(("pid-1",)) == ()


# --- 4 ------------------------------------------------------------------------
def test_criterion_4_an_acute_item_routes_same_day_bypassing_gates_with_an_override_entry():
    from samvedna.core.types import InstrumentResponse
    from samvedna.pipeline.acute import SLA_HOURS, handle_submission

    ledger = Ledger()
    response = InstrumentResponse(
        pid="pid-test", instrument="PHQ9", taken_at=AT,
        items={"item_1": 1, "item_9": 2}, total=9, cutoff=10,
    )
    route = handle_submission(
        response, case(deviation("self_report", breach={7: 1 / 7, 30: 1 / 30, 90: 1 / 90})),
        ledger,
    )
    assert route.verdict.decision == "IMMEDIATE_ESCALATE"
    assert route.routed_to == "mental_health_authority"
    assert not route.routed_to_command
    assert {"evidence", "persistence"} <= set(route.verdict.failed_gates)
    assert (route.acknowledge_by - AT).total_seconds() / 3600 == SLA_HOURS
    assert ledger.for_action("override.applied")[0].detail["reason"]


# --- 5 ------------------------------------------------------------------------
def test_criterion_5_with_the_confounder_check_disabled_the_run_produces_no_escalate(world):
    force, ps = world

    class Broken:
        name = "confounder_check"

        def review(self, ctx):
            raise RuntimeError("forcibly disabled")

    clean = nightly(force, ps, registry_for(force, ps), Ledger())
    frozen = nightly(
        force, ps, registry_for(force, ps), Ledger(),
        panel=Panel((RiskAdvocate(), Broken(), WelfareContext())),
    )
    assert clean.escalated > 0, "the clean run must escalate for this to mean anything"
    assert frozen.escalated == 0
    assert frozen.escalation_frozen
    assert frozen.count("MONITOR") > 0


# --- 6 ------------------------------------------------------------------------
def test_criterion_6_an_accepted_annotation_suppresses_that_driver_next_run():
    book, ledger = CaseBook(), Ledger()
    today = date(2026, 9, 5)
    book.contest(
        "pid-1", "benign_explanation", "leave",
        "the leave was deferred at my own request", officer(), ledger,
        as_of=today, at=AT,
    )
    suppressed = book.suppressed_drivers("pid-1", today)
    assert suppressed == {"leave"}

    before = decide(case(deviation("leave", breach=SUSTAINED)))
    after = decide(case(deviation("leave", breach=SUSTAINED), suppressed=tuple(suppressed)))
    assert before.gates["actionability"].passed
    assert not after.gates["actionability"].passed
    assert after.decision == "NO_FLAG"


# --- 7 ------------------------------------------------------------------------
def test_criterion_7_a_failed_ledger_write_aborts_disclosure_and_releases_no_name():
    class ExplodingDirectory:
        def resolve(self, pid):
            raise AssertionError("the directory must never be reached")

    registry = ConsentRegistry()
    registry.enrol("pid-1", ALL_DOMAINS, welfare_contact=True, at=AT)
    ledger = Ledger()
    ledger.fail_next_write = True

    with pytest.raises(DisclosureRefused) as excinfo:
        disclose(
            pid="pid-1",
            verdict=Verdict("ESCALATE", "all gates passed",
                            {"evidence": Gate("evidence", 1.0, 0.65, True, "", {})},
                            (), (), 0.9),
            principal=officer(), purpose="welfare:contact", unit_id="UNIT-01",
            directory=ExplodingDirectory(), ledger=ledger, consent=registry, at=AT,
        )
    assert "No identity has been released" in str(excinfo.value)
    assert len(ledger) == 0


# --- 8 ------------------------------------------------------------------------
def test_criterion_8_every_workflow_transition_appears_with_actor_timestamp_and_reason(world):
    """Nightly run, officer actions and a contest, all in one ledger."""
    force, ps = world
    ledger = Ledger()
    registry = registry_for(force, ps)
    record = nightly(force, ps, registry, ledger)

    book = CaseBook()
    book.record_contact("pid-x", officer(), ledger, at=AT)
    book.close("pid-x", "supported", officer(), ledger, at=AT, note="rotation adjusted")
    book.defer("pid-y", "on leave until the 14th", officer(), ledger, at=AT)
    book.contest("pid-z", "benign_explanation", "leave", "family function",
                 officer(), ledger, as_of=force.as_of, at=AT)

    actions = {e.action for e in ledger.entries()}
    assert {"run.started", "verdict.recorded", "case.contacted", "case.closed",
            "case.deferred", "annotation.accepted"} <= actions
    assert actions & {"run.completed", "run.partial"}

    for entry in ledger.entries():
        assert entry.actor, f"entry {entry.seq} has no actor"
        assert entry.at is not None
        assert entry.purpose or entry.action.startswith("run.")

    ok, reason = ledger.verify()
    assert ok, reason
    assert record.ledger_head
