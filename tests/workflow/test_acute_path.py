"""Phase 7 / Workflow E: an acute item escalates the same cycle, bypassing gates.

The two rules PART 6.7 says must not be traded away are the first two tests here:
the path is triggered by the instrument rather than by a model score, and it
never routes to the chain of command.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from tests.conftest import case, consent, deviation

from samvedna.core.types import InstrumentResponse, RiskAssessment
from samvedna.disclosure.audit import Ledger, LedgerWriteFailed
from samvedna.pipeline.acute import (
    HELP_RESOURCES,
    SLA_HOURS,
    handle_submission,
    submit,
)

SUBMITTED = datetime(2026, 9, 5, 14, 20, tzinfo=UTC)
BLIP = {7: 1.0, 30: 7 / 30, 90: 7 / 90}


def response(**items):
    base = {"item_1": 1, "item_9": 0}
    base.update(items)
    return InstrumentResponse(
        pid="pid-test", instrument="PHQ9", taken_at=SUBMITTED,
        items=base, total=sum(base.values()), cutoff=10,
    )


def ctx():
    return case(deviation("self_report", breach=BLIP))


# ------------------------------------------------- the two untradeable rules --
def test_the_path_is_triggered_by_the_instrument_not_by_a_model_score():
    terrifying = RiskAssessment(
        pid="pid-test", score=1.0, horizon_days=60,
        drivers=(("self_report_mean_7d", 9.9),), model_version="v-max",
    )
    route = handle_submission(response(item_9=0), case(
        deviation("self_report", breach=BLIP), risk=terrifying), Ledger())
    assert route is None, "a model score must never trigger the acute path"

    route = handle_submission(response(item_9=1), ctx(), Ledger())
    assert route is not None, "an endorsed instrument item must always trigger it"


def test_an_acute_disclosure_never_routes_to_the_commanding_officer():
    route = handle_submission(response(item_9=1), ctx(), Ledger())
    assert route.routed_to == "mental_health_authority"
    assert not route.routed_to_command
    assert all(i.authority == "mental_health" for i in route.verdict.recommended[:1])
    assert "does not go to your commanding officer" in route.shown_to_person


# ------------------------------------------------------------- the bypass --
def test_it_bypasses_persistence_and_evidence():
    route = handle_submission(response(item_9=1), ctx(), Ledger())
    assert route.verdict.decision == "IMMEDIATE_ESCALATE"
    assert "persistence" in route.verdict.failed_gates
    assert "evidence" in route.verdict.failed_gates


def test_the_gates_it_bypassed_are_still_computed_and_recorded():
    """An officer must be able to see afterwards what the arithmetic would have
    said about a case the override carried."""
    route = handle_submission(response(item_9=1), ctx(), Ledger())
    assert set(route.verdict.gates) == {
        "evidence", "consistency", "persistence", "actionability"
    }
    assert all(g.formula for g in route.verdict.gates.values())


def test_a_single_bad_day_cannot_clear_persistence_which_is_why_this_path_exists():
    from samvedna.core.verdict import decide

    one_day = case(deviation("self_report", breach={7: 1 / 7, 30: 1 / 30, 90: 1 / 90}))
    assert decide(one_day).decision == "MONITOR"
    assert handle_submission(
        response(item_9=1), one_day, Ledger()
    ).verdict.decision == "IMMEDIATE_ESCALATE"


def test_it_fires_even_when_consent_to_welfare_contact_was_withheld():
    """Submitting the disclosure is itself the consent to act on it."""
    withheld = case(
        deviation("self_report", breach=BLIP),
        consent_state=consent(welfare_contact=False),
    )
    route = handle_submission(response(item_9=1), withheld, Ledger())
    assert route.verdict.decision == "IMMEDIATE_ESCALATE"


def test_a_zero_on_the_acute_item_joins_the_ordinary_pipeline():
    assert handle_submission(response(item_1=3, item_9=0), ctx(), Ledger()) is None


def test_a_high_total_without_the_acute_item_does_not_override():
    """Severity is not acuity. A high PHQ-9 total is a case for the gates."""
    assert handle_submission(
        response(item_1=3, item_2=3, item_3=3, item_9=0), ctx(), Ledger()
    ) is None


# ------------------------------------------------------- what the person sees --
def test_the_person_is_shown_help_immediately_not_a_submission_receipt():
    route, shown = submit(response(item_9=1), ctx(), Ledger())
    assert shown == route.shown_to_person
    assert route.resources == HELP_RESOURCES
    assert len(route.resources) >= 3
    assert "You do not have to wait" in shown


def test_the_message_promises_no_consequence_to_posting_or_acr():
    route = handle_submission(response(item_9=1), ctx(), Ledger())
    text = route.shown_to_person.lower()
    assert "record" in text and "posting" in text and "acr" in text


# ------------------------------------------------------------------- the SLA --
def test_the_sla_clock_starts_when_the_person_submitted_not_when_we_processed_it():
    """Measuring from processing time lets a queue delay silently consume the
    window a person is waiting inside — the first run of this path produced an
    acknowledge-by timestamp in the past."""
    route = handle_submission(response(item_9=1), ctx(), Ledger())
    assert route.acknowledge_by == SUBMITTED + timedelta(hours=SLA_HOURS)
    assert route.acknowledge_by > SUBMITTED


# ---------------------------------------------------------------- the ledger --
def test_the_override_is_logged_with_its_reason_and_the_gates_it_bypassed():
    ledger = Ledger()
    handle_submission(response(item_9=1), ctx(), ledger)
    entry = ledger.for_action("override.applied")[0]
    assert entry.subject_pid == "pid-test"
    assert entry.detail["acute_items"] == "item_9"
    assert entry.detail["routed_to"] == "mental_health_authority"
    assert entry.detail["reason"]
    assert "persistence" in entry.detail["bypassed_gates"]
    assert ledger.verify()[0]


def test_the_ledger_records_which_item_fired_never_the_answers():
    ledger = Ledger()
    handle_submission(response(item_1=3, item_2=2, item_9=1), ctx(), ledger)
    blob = str(ledger.for_action("override.applied")[0].detail)
    assert "item_9" in blob
    assert "item_1" not in blob, "the ledger must hold the fact, not the content"


def test_a_failed_ledger_write_still_shows_the_person_help_but_dispatches_nothing():
    """Withholding help because a database was unavailable would be the worst
    possible reading of 'fail closed'. Dispatching without a record would be the
    second worst. Do the first, refuse the second, and say so."""
    ledger = Ledger()
    ledger.fail_next_write = True
    route, shown = submit(response(item_9=1), ctx(), ledger)

    assert route is None, "nothing may be dispatched without an audit record"
    assert "Thank you for telling us" in shown
    assert "NOT been routed automatically" in shown
    assert "contact the designated mental-health authority directly" in shown.lower()
    assert len(ledger) == 0


def test_handle_submission_propagates_a_ledger_failure_rather_than_swallowing_it():
    ledger = Ledger()
    ledger.fail_next_write = True
    with pytest.raises(LedgerWriteFailed):
        handle_submission(response(item_9=1), ctx(), ledger)


def test_gad7_and_mbi_have_no_acute_item_configured_and_do_not_override():
    """Only PHQ-9 carries a validated acute-risk item. Inventing one for the
    others would be a clinical judgement this system has no standing to make."""
    for instrument in ("GAD7", "MBI_GS9"):
        r = InstrumentResponse(
            pid="pid-test", instrument=instrument, taken_at=SUBMITTED,
            items={"item_1": 3, "item_9": 3}, total=21, cutoff=10,
        )
        assert handle_submission(r, ctx(), Ledger()) is None
