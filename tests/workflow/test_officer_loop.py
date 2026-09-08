"""Workflows C, G and I — the officer's daily loop and the dignity path.

§8.12 criteria 3 and 6 live here: a case cannot be closed without an outcome
category, and an accepted confounder annotation suppresses that driver next run.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from samvedna.config.windows import CONFOUNDER_ANNOTATION_DAYS
from samvedna.disclosure.audit import Ledger
from samvedna.disclosure.rbac import Principal
from samvedna.pipeline.outcomes import OUTCOMES, CaseBook, OutcomeRequired

AT = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
TODAY = date(2026, 9, 5)


def officer():
    return Principal("WO-12", "welfare_officer", frozenset({"UNIT-01"}))


# ------------------------------------------------------------- Workflow C --
def test_a_case_cannot_be_closed_without_an_outcome_category():
    """§8.12 criterion 3."""
    book, ledger = CaseBook(), Ledger()
    for bad in ("", "done", "ok", "resolved", "SUPPORTED "):
        with pytest.raises(OutcomeRequired):
            book.close("pid-1", bad, officer(), ledger, at=AT)
    assert len(ledger) == 0


def test_an_unrecognised_outcome_is_refused_not_coerced():
    book, ledger = CaseBook(), Ledger()
    with pytest.raises(OutcomeRequired) as excinfo:
        book.close("pid-1", "supported_maybe", officer(), ledger, at=AT)
    assert "is not an outcome category" in str(excinfo.value)
    assert "blocks until one is given" in str(excinfo.value)


@pytest.mark.parametrize("outcome", OUTCOMES)
def test_every_valid_outcome_closes_the_case_and_is_logged(outcome):
    book, ledger = CaseBook(), Ledger()
    book.close("pid-1", outcome, officer(), ledger, at=AT)
    assert book.closed["pid-1"].outcome == outcome
    entry = ledger.for_action("case.closed")[0]
    assert entry.detail["outcome"] == outcome
    assert entry.actor == "welfare_officer:WO-12"


def test_the_case_list_blocks_on_a_contacted_but_unclosed_case():
    book, ledger = CaseBook(), Ledger()
    book.record_contact("pid-1", officer(), ledger, at=AT)
    book.record_contact("pid-2", officer(), ledger, at=AT)
    book.close("pid-2", "supported", officer(), ledger, at=AT)
    assert book.blocking(("pid-1", "pid-2", "pid-3")) == ("pid-1",)


def test_only_the_fact_of_contact_is_stored_never_the_conversation():
    book, ledger = CaseBook(), Ledger()
    book.record_contact("pid-1", officer(), ledger, at=AT)
    entry = ledger.for_action("case.contacted")[0]
    assert entry.detail == {}
    assert isinstance(book.contacted["pid-1"], datetime)


def test_a_deferral_requires_a_reason_and_is_logged():
    book, ledger = CaseBook(), Ledger()
    with pytest.raises(OutcomeRequired):
        book.defer("pid-1", "   ", officer(), ledger, at=AT)
    book.defer("pid-1", "on leave until the 14th", officer(), ledger, at=AT)
    assert ledger.for_action("case.deferred")[0].detail["reason"]


# ------------------------------------------------------------- Workflow G --
def test_an_accepted_annotation_suppresses_that_driver_on_the_next_run():
    """§8.12 criterion 6."""
    book, ledger = CaseBook(), Ledger()
    book.contest(
        "pid-1", "benign_explanation", "leave",
        "leave was deferred at my own request for a family function",
        officer(), ledger, as_of=TODAY, at=AT,
    )
    assert book.suppressed_drivers("pid-1", TODAY) == {"leave"}
    assert ledger.for_action("annotation.accepted")[0].detail["driver"] == "leave"


def test_a_rejected_annotation_suppresses_nothing_but_is_still_logged():
    book, ledger = CaseBook(), Ledger()
    book.contest("pid-1", "benign_explanation", "leave", "disputed",
                 officer(), ledger, accepted=False, as_of=TODAY, at=AT)
    assert book.suppressed_drivers("pid-1", TODAY) == frozenset()
    assert ledger.for_action("annotation.rejected")


def test_an_annotation_expires_after_its_configured_window():
    """It suppresses a driver for a window, not forever. A benign explanation
    that was true in September is not evidence about March."""
    book, ledger = CaseBook(), Ledger()
    book.contest("pid-1", "benign_explanation", "leave", "family function",
                 officer(), ledger, as_of=TODAY, at=AT)
    still = TODAY + timedelta(days=CONFOUNDER_ANNOTATION_DAYS)
    expired = still + timedelta(days=1)
    assert book.suppressed_drivers("pid-1", still) == {"leave"}
    assert book.suppressed_drivers("pid-1", expired) == frozenset()


def test_an_annotation_is_scoped_to_one_person():
    book, ledger = CaseBook(), Ledger()
    book.contest("pid-1", "benign_explanation", "leave", "r", officer(), ledger,
                 as_of=TODAY, at=AT)
    assert book.suppressed_drivers("pid-2", TODAY) == frozenset()


def test_a_factual_error_becomes_a_correction_request_not_an_annotation():
    book, ledger = CaseBook(), Ledger()
    result = book.contest("pid-1", "factual_error", "leave",
                          "that leave was sanctioned, the record is wrong",
                          officer(), ledger, as_of=TODAY, at=AT)
    assert result is None
    assert book.corrections and book.corrections[0][1] == "leave"
    assert ledger.for_action("correction.requested")
    assert book.suppressed_drivers("pid-1", TODAY) == frozenset()


def test_objecting_to_analysis_narrows_consent_and_is_not_punished():
    book, ledger = CaseBook(), Ledger()
    book.contest("pid-1", "objects_to_analysis", "", "I do not want this",
                 officer(), ledger, as_of=TODAY, at=AT)
    entry = ledger.for_action("consent.narrowed")[0]
    assert entry.detail["via"] == "contest"
    assert not ledger.for_action("case.dismissed")


def test_a_suppressed_driver_actually_changes_the_verdict():
    """End to end: the annotation must reach the gates, not just a table."""
    from tests.conftest import case, deviation

    from samvedna.core.verdict import decide

    SUSTAINED = {7: 1.0, 30: 1.0, 90: 0.9}
    before = case(deviation("leave", breach=SUSTAINED))
    after = case(deviation("leave", breach=SUSTAINED), suppressed=("leave",))

    assert decide(before).gates["actionability"].passed
    assert not decide(after).gates["actionability"].passed
    assert decide(after).decision == "NO_FLAG"


# ------------------------------------------------------------- Workflow I --
def test_realised_precision_is_measured_from_officer_outcomes():
    book, ledger = CaseBook(), Ledger()
    for pid, outcome in [("a", "supported"), ("b", "supported"),
                         ("c", "not_supported"), ("d", "supported")]:
        book.close(pid, outcome, officer(), ledger, at=AT)
    precision, n = book.realised_precision()
    assert n == 4
    assert precision == pytest.approx(0.75)


def test_already_known_counts_as_neither_success_nor_failure():
    """Counting it as a success flatters the model; counting it as a failure
    punishes it for being right about somebody already being helped."""
    book, ledger = CaseBook(), Ledger()
    book.close("a", "supported", officer(), ledger, at=AT)
    book.close("b", "already_known", officer(), ledger, at=AT)
    book.close("c", "declined_contact", officer(), ledger, at=AT)
    precision, n = book.realised_precision()
    assert n == 1, "only supported/not_supported are judged"
    assert precision == 1.0


def test_no_outcomes_yet_reports_zero_rather_than_dividing_by_zero():
    assert CaseBook().realised_precision() == (0.0, 0)


def test_outcome_counts_cover_every_category():
    book, ledger = CaseBook(), Ledger()
    book.close("a", "supported", officer(), ledger, at=AT)
    counts = book.outcome_counts()
    assert set(counts) == set(OUTCOMES)
    assert counts["supported"] == 1


def test_every_officer_action_appears_in_the_ledger_with_actor_and_reason():
    """§8.12 criterion 8."""
    book, ledger = CaseBook(), Ledger()
    book.record_contact("pid-1", officer(), ledger, at=AT)
    book.close("pid-1", "supported", officer(), ledger, at=AT, note="rotation adjusted")
    book.defer("pid-2", "on leave", officer(), ledger, at=AT)
    book.contest("pid-3", "benign_explanation", "leave", "family", officer(), ledger,
                 as_of=TODAY, at=AT)

    actions = [e.action for e in ledger.entries()]
    assert actions == [
        "case.contacted", "case.closed", "case.deferred", "annotation.accepted",
    ]
    for entry in ledger.entries():
        assert entry.actor == "welfare_officer:WO-12"
        assert entry.at == AT
    assert ledger.verify()[0]
