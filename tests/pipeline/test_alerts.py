"""Alert dispatch, the cancellation window, and Phase 1 shadow mode.

The submitted roadmap's Phase 1 is "shadow mode: gates run, no alerts issued",
which is only a real property if the dispatcher enforces it rather than the
operators remembering to.
"""
from __future__ import annotations

from datetime import UTC, datetime

from samvedna.core.interventions import BY_CODE
from samvedna.core.types import Gate, Verdict
from samvedna.disclosure.audit import Ledger
from samvedna.pipeline.alerts import OFFICER_CONSOLE_HOUR, AlertQueue
from samvedna.pipeline.record import CaseRecord

AT = datetime(2026, 9, 5, 2, 0, tzinfo=UTC)


def verdict(decision="ESCALATE", override=False):
    gates = {
        n: Gate(n, 0.9, 0.5, True, "", {})
        for n in ("evidence", "consistency", "persistence", "actionability")
    }
    return Verdict(
        decision=decision, reason="test", gates=gates, failed_gates=(),
        mind_change=(), composite=0.9,
        recommended=(BY_CODE["WLF-REST"],), override=override,
    )


def case(pid="pid-1", decision="ESCALATE", override=False):
    return CaseRecord(
        pid=pid, unit_id="UNIT-01", state="ESCALATED", verdict=verdict(decision, override)
    )


# ------------------------------------------------------------- dispatching --
def test_an_escalated_case_is_queued_not_sent():
    """A verdict reached at 02:00 does not wake anybody."""
    queue, ledger = AlertQueue(), Ledger()
    alert = queue.enqueue(case(), ledger, at=AT)
    assert alert is not None
    assert not alert.delivered
    assert alert.cancellable
    assert OFFICER_CONSOLE_HOUR.hour == 7


def test_an_alert_carries_a_pid_and_never_a_name():
    from samvedna.pipeline.alerts import Alert

    fields = set(Alert.__dataclass_fields__)
    for forbidden in ("name", "service_number", "rank", "identity", "contact"):
        assert forbidden not in fields


def test_a_monitor_verdict_queues_nothing():
    queue, ledger = AlertQueue(), Ledger()
    assert queue.enqueue(case(decision="MONITOR"), ledger, at=AT) is None
    assert queue.pending() == ()


def test_a_no_flag_verdict_queues_nothing():
    queue, ledger = AlertQueue(), Ledger()
    assert queue.enqueue(case(decision="NO_FLAG"), ledger, at=AT) is None


def test_an_acute_override_routes_same_day_to_the_mental_health_authority():
    queue, ledger = AlertQueue(), Ledger()
    alert = queue.enqueue(
        case(decision="IMMEDIATE_ESCALATE", override=True), ledger, at=AT
    )
    assert alert.priority == "same_day"
    assert alert.route_to == "mental_health_authority"


def test_a_routine_escalation_routes_to_the_welfare_officer():
    queue, ledger = AlertQueue(), Ledger()
    assert queue.enqueue(case(), ledger, at=AT).route_to == "welfare_officer"


def test_every_dispatch_is_logged():
    queue, ledger = AlertQueue(), Ledger()
    queue.enqueue(case(), ledger, at=AT)
    entry = ledger.for_action("disclosure.requested")[0]
    assert entry.subject_pid == "pid-1"
    assert entry.detail["route_to"] == "welfare_officer"
    assert ledger.verify()[0]


# ---------------------------------------------- the cancellation window --
def test_an_undelivered_alert_can_be_withdrawn():
    """§8.12 criterion 1. Only possible because dispatch is deferred."""
    queue, ledger = AlertQueue(), Ledger()
    queue.enqueue(case(), ledger, at=AT)
    assert queue.cancel_for("pid-1", ledger, at=AT) == 1
    assert queue.pending() == ()


def test_a_delivered_alert_cannot_be_withdrawn():
    """A person has seen it. Pretending otherwise would be a lie to the officer."""
    queue, ledger = AlertQueue(), Ledger()
    queue.enqueue(case(), ledger, at=AT)
    queue.deliver("pid-1", ledger, at=AT)
    assert queue.cancel_for("pid-1", ledger, at=AT) == 0


def test_cancellation_removes_rather_than_marks():
    """A cancelled-alerts list is a list of people who withdrew consent, and
    PART 14 forbids that existing anywhere a report could read it."""
    queue, ledger = AlertQueue(), Ledger()
    queue.enqueue(case(), ledger, at=AT)
    queue.cancel_for("pid-1", ledger, at=AT)
    assert queue.for_pid("pid-1") == ()
    assert len(queue) == 0


def test_cancelling_one_person_leaves_everybody_else_queued():
    queue, ledger = AlertQueue(), Ledger()
    queue.enqueue(case("pid-1"), ledger, at=AT)
    queue.enqueue(case("pid-2"), ledger, at=AT)
    queue.cancel_for("pid-1", ledger, at=AT)
    assert {a.pid for a in queue.pending()} == {"pid-2"}


def test_cancelling_for_somebody_with_no_alert_is_silent():
    queue, ledger = AlertQueue(), Ledger()
    assert queue.cancel_for("nobody", ledger, at=AT) == 0
    assert len(ledger) == 0, "no event means no ledger entry"


# ------------------------------------------------ Phase 1: shadow mode --
def test_shadow_mode_runs_the_gates_and_issues_no_alerts():
    """The submitted roadmap's Phase 1, enforced by the dispatcher rather than
    by operators remembering."""
    queue, ledger = AlertQueue(mode="shadow"), Ledger()
    for i in range(3):
        assert queue.enqueue(case(f"pid-{i}"), ledger, at=AT) is None

    assert queue.pending() == ()
    assert queue.suppressed_in_shadow == 3
    assert len(ledger.for_action("verdict.recorded")) == 3


def test_a_shadow_run_records_what_it_would_have_done():
    """Otherwise there is nothing to calibrate thresholds against."""
    queue, ledger = AlertQueue(mode="shadow"), Ledger()
    queue.enqueue(case(), ledger, at=AT)
    entry = ledger.for_action("verdict.recorded")[0]
    assert entry.detail["shadow_mode"] is True
    assert entry.detail["would_have_alerted"] == "ESCALATE"


def test_shadow_mode_suppresses_acute_alerts_too_and_that_is_deliberate():
    """A shadow deployment is running on retrospective data. Routing a same-day
    alert about a historical record would send somebody to a person about
    something that happened months ago."""
    queue, ledger = AlertQueue(mode="shadow"), Ledger()
    assert queue.enqueue(
        case(decision="IMMEDIATE_ESCALATE", override=True), ledger, at=AT
    ) is None
    assert queue.pending() == ()


def test_the_live_default_is_live_not_shadow():
    """A deployment that forgets to set the mode should alert, not go silent."""
    assert AlertQueue().mode == "live"
    assert not AlertQueue().shadow


def test_an_empty_queue_is_still_a_queue():
    assert bool(AlertQueue()) is True
