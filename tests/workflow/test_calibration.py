"""Phase 15 / Workflow I: nothing retrains or re-thresholds itself."""
from __future__ import annotations

from datetime import UTC, datetime

from samvedna.config.thresholds import DRIFT_PSI_FREEZE, GATE_THRESHOLDS
from samvedna.disclosure.audit import Ledger
from samvedna.disclosure.rbac import Principal
from samvedna.pipeline.calibration import (
    MAX_THRESHOLD_STEP,
    MIN_OUTCOMES_FOR_A_PROPOSAL,
    PRECISION_FLOOR,
    BoardDecision,
    aggregate_week,
    apply_decision,
    check_drift,
    population_stability_index,
    propose,
)
from samvedna.pipeline.outcomes import CaseBook

AT = datetime(2026, 9, 12, tzinfo=UTC)


def officer():
    return Principal("WO-12", "welfare_officer", frozenset({"UNIT-01"}))


def book_with(supported: int, not_supported: int) -> CaseBook:
    book, ledger = CaseBook(), Ledger()
    for i in range(supported):
        book.close(f"s{i}", "supported", officer(), ledger, at=AT)
    for i in range(not_supported):
        book.close(f"n{i}", "not_supported", officer(), ledger, at=AT)
    return book


# --------------------------------------------- the module cannot apply itself --
def test_there_is_no_function_that_generates_and_applies_a_change():
    """PART 8.9: a system that can quietly lower its own bar for naming people
    is exactly the system the problem statement warns about."""
    import inspect

    from samvedna.pipeline import calibration

    for name, fn in inspect.getmembers(calibration, inspect.isfunction):
        source = inspect.getsource(fn)
        if name == "propose":
            assert "apply_decision" not in source
        if name == "apply_decision":
            assert "propose(" not in source


def test_applying_a_change_requires_a_recorded_human_decision():
    fields = set(BoardDecision.__dataclass_fields__)
    assert {"approved", "board_reference", "reason", "decided_by", "decided_at"} <= fields


# ------------------------------------------------------------- the proposals --
def test_no_proposal_is_generated_from_too_few_outcomes():
    """A threshold change argued from four outcomes is argued from noise."""
    report = aggregate_week(book_with(1, 3))
    assert not report.enough_evidence
    assert propose(report, at=AT) == ()


def test_poor_realised_precision_proposes_tightening():
    report = aggregate_week(book_with(10, 15))
    assert report.judged_cases >= MIN_OUTCOMES_FOR_A_PROPOSAL
    assert report.realised_precision < PRECISION_FLOOR
    proposals = propose(report, at=AT)
    assert proposals
    assert all(p.direction == "tighten" for p in proposals if not p.gate.startswith("subgroup"))


def test_a_good_week_never_proposes_loosening():
    """The asymmetry is intentional: a loop that can relax its own bar every time
    it has a quiet week will eventually relax it into the ground."""
    report = aggregate_week(book_with(24, 1))
    assert report.realised_precision > PRECISION_FLOOR
    assert propose(report, at=AT) == ()


def test_a_proposal_never_moves_a_threshold_more_than_one_step():
    report = aggregate_week(book_with(1, 29))
    for proposal in propose(report, at=AT):
        if proposal.gate.startswith("subgroup"):
            continue
        assert abs(proposal.proposed - proposal.current) <= MAX_THRESHOLD_STEP + 1e-9


def test_a_proposal_carries_its_evidence_and_a_readable_rationale():
    proposals = propose(aggregate_week(book_with(10, 15)), at=AT)
    for proposal in proposals:
        assert proposal.evidence
        assert "realised precision" in proposal.rationale.lower()
        assert str(proposal.evidence["judged_cases"])[:2] in proposal.rationale


def test_a_lagging_subgroup_is_reported_with_no_threshold_change():
    """A threshold applies to everybody. A subgroup gap is a model problem."""
    report = aggregate_week(
        book_with(20, 2),
        subgroup={"rank=Constable": {"precision": 0.4, "positives": 8, "n": 90}},
    )
    proposals = [p for p in propose(report, at=AT) if p.gate.startswith("subgroup:")]
    assert proposals
    assert proposals[0].direction == "none"
    assert "model problem" in proposals[0].rationale


def test_a_subgroup_with_too_few_positives_produces_no_proposal():
    report = aggregate_week(
        book_with(20, 2),
        subgroup={"rank=SI": {"precision": 0.0, "positives": 1, "n": 40}},
    )
    assert [p for p in propose(report, at=AT) if p.gate.startswith("subgroup:")] == []


# ------------------------------------------------------------- the decision --
def test_an_approved_change_is_logged_and_returns_new_thresholds():
    ledger = Ledger()
    proposal = propose(aggregate_week(book_with(10, 15)), at=AT)[0]
    decision = BoardDecision(proposal, True, "GRB-2026-14", "accepted as proposed",
                             "Brig. Review Board", AT)
    updated = apply_decision(decision, ledger, at=AT)
    assert updated[proposal.gate] == proposal.proposed
    entry = ledger.for_action("config.changed")[0]
    assert entry.detail["board_reference"] == "GRB-2026-14"
    assert entry.detail["approved"] is True


def test_a_rejection_is_logged_with_its_reason_and_changes_nothing():
    ledger = Ledger()
    proposal = propose(aggregate_week(book_with(10, 15)), at=AT)[0]
    decision = BoardDecision(proposal, False, "GRB-2026-14",
                             "insufficient case volume for the quarter",
                             "Brig. Review Board", AT)
    assert apply_decision(decision, ledger, at=AT) is None
    assert ledger.entries()[0].detail["reason"]
    assert ledger.entries()[0].detail["approved"] is False


def test_applying_a_change_does_not_mutate_the_live_config():
    """Prior verdicts must stay reproducible against the version they were made
    under, so a config change is a versioned release, not an assignment."""
    before = dict(GATE_THRESHOLDS)
    proposal = propose(aggregate_week(book_with(10, 15)), at=AT)[0]
    apply_decision(
        BoardDecision(proposal, True, "GRB-1", "ok", "board", AT), Ledger(), at=AT
    )
    assert before == GATE_THRESHOLDS


def test_a_subgroup_proposal_cannot_be_applied_as_a_threshold():
    report = aggregate_week(
        book_with(20, 2),
        subgroup={"rank=Constable": {"precision": 0.4, "positives": 8, "n": 90}},
    )
    proposal = next(p for p in propose(report, at=AT) if p.gate.startswith("subgroup:"))
    assert apply_decision(
        BoardDecision(proposal, True, "GRB-1", "noted", "board", AT), Ledger(), at=AT
    ) is None


# ------------------------------------------------------------------- drift --
def test_an_identical_distribution_has_zero_drift():
    values = [i / 100 for i in range(100)]
    assert population_stability_index(values, values) == 0.0


def test_a_shifted_distribution_registers_drift():
    baseline = [i / 100 for i in range(100)]
    shifted = [min(1.0, v + 0.4) for v in baseline]
    assert population_stability_index(baseline, shifted) > DRIFT_PSI_FREEZE


def test_a_collapsed_distribution_registers_MORE_drift_not_less():
    """Skipping empty bins makes PSI *fall* when a distribution collapses into
    fewer bins, which is exactly the drift it exists to catch."""
    baseline = [i / 100 for i in range(100)]
    collapsed = [0.05] * 100
    shifted = [min(1.0, v + 0.4) for v in baseline]
    assert population_stability_index(baseline, collapsed) > population_stability_index(
        baseline, shifted
    )


def test_drift_beyond_threshold_freezes_escalation_and_logs_it():
    ledger = Ledger()
    baseline = [i / 100 for i in range(100)]
    status, psi, reason = check_drift(baseline, [0.05] * 100, ledger)
    assert status == "frozen"
    assert psi > DRIFT_PSI_FREEZE
    assert "MONITOR records continue" in reason
    assert "stale model must not keep naming people" in reason
    assert ledger.for_action("model.frozen")


def test_drift_within_threshold_does_not_freeze():
    baseline = [i / 100 for i in range(100)]
    status, _, _ = check_drift(baseline, list(baseline), Ledger())
    assert status == "ok"


def test_empty_input_does_not_raise():
    assert population_stability_index([], [0.1]) == 0.0
    assert population_stability_index([0.1], []) == 0.0
