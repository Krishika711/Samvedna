"""False negatives, and the loosening path they unlock.

The problem statement names "minimizing false positives **and false negatives**"
as a key technical challenge, and until `pipeline/missed.py` existed this system
only measured one of them. `calibration.propose` could only ever raise a
threshold, which means that given enough quiet weeks it converges on naming
nobody — a failure mode as real as over-flagging and considerably easier to
mistake for success.

These tests pin the three regimes that matter and the guard rails on each.
"""
from __future__ import annotations

from datetime import date

from samvedna.config.thresholds import GATE_THRESHOLDS
from samvedna.pipeline.calibration import PRECISION_FLOOR, WeeklyReport, propose
from samvedna.pipeline.missed import (
    MISSED_RATE_CEILING,
    MissedCase,
    MissedCaseBook,
)

DAY = date(2026, 9, 1)


def report(precision: float, judged: int = 25) -> WeeklyReport:
    return WeeklyReport(
        outcomes={"supported": judged},
        realised_precision=precision,
        judged_cases=judged,
        annotations_accepted=0,
        annotations_rejected=0,
        corrections_requested=0,
    )


def book(*, caught: int, missed_on: str, missed: int, no_flag: int = 0) -> MissedCaseBook:
    b = MissedCaseBook()
    for i in range(caught):
        b.register(MissedCase(f"c{i}", DAY, "self_referral", "escalated"))
    for i in range(missed):
        b.register(MissedCase(f"m{i}", DAY, "medical", "monitored", missed_on, 0.01))
    for i in range(no_flag):
        b.register(MissedCase(f"n{i}", DAY, "incident", "no_flag"))
    return b


# ----------------------------------------------------------- the measurement --

def test_not_enrolled_is_not_counted_as_a_miss():
    """Enrolment coverage is a different problem with a different owner.

    Counting a person who was never in scope would make the missed rate a
    measure of how many people signed up, not of whether the gates are set
    correctly.
    """
    b = MissedCaseBook()
    b.register(MissedCase("a", DAY, "self_referral", "escalated"))
    b.register(MissedCase("b", DAY, "medical", "not_enrolled"))
    r = b.report()

    assert r.surfaced == 2
    assert r.not_enrolled == 1
    assert r.missed == 0
    assert r.missed_rate == 0.0, "an unenrolled person counted against the gates"
    assert r.surfaced_recall == 1.0


def test_no_flag_miss_is_counted_but_not_recoverable():
    """A miss with no deviation detected cannot be fixed by moving a threshold.

    This distinction is the actionable part of the whole module: a `monitored`
    miss says a gate may be too high, and a `no_flag` miss says the features
    never saw anything. Lowering a gate does nothing for the second.
    """
    r = book(caught=1, missed_on="", missed=0, no_flag=3).report()

    assert r.missed == 3
    assert r.recoverable == 0, "a no_flag miss was offered as threshold-recoverable"
    assert r.by_blocking_gate == {}


def test_dominant_gate_needs_a_majority():
    """Two gates blocking equally is not evidence about either one."""
    b = MissedCaseBook()
    for i in range(4):
        b.register(MissedCase(f"x{i}", DAY, "medical", "monitored", "evidence", 0.01))
    for i in range(4):
        b.register(MissedCase(f"y{i}", DAY, "medical", "monitored", "consistency", 0.01))

    assert b.report().dominant_gate == "", "picked a gate from a tie"


def test_empty_book_is_truthy():
    """`__len__` without `__bool__` is the bug that ate nine audit entries."""
    b = MissedCaseBook()
    assert len(b) == 0
    assert b, "an empty MissedCaseBook is falsy — `book or MissedCaseBook()` will lie"


# ------------------------------------------------------------ the three regimes --

def test_high_miss_rate_with_good_precision_proposes_loosening():
    surfaced = book(caught=10, missed_on="consistency", missed=8).report()
    assert surfaced.missed_rate > MISSED_RATE_CEILING

    proposals = propose(report(0.88), surfaced=surfaced)
    loosen = [p for p in proposals if p.direction == "loosen"]

    assert len(loosen) == 1, "no loosening proposal on clear missed-case evidence"
    assert loosen[0].gate == "consistency"
    assert loosen[0].proposed < GATE_THRESHOLDS["consistency"]
    assert "surfaced-case recall and not recall" in loosen[0].rationale, (
        "the loosening rationale must carry its own limitation"
    )


def test_a_quiet_week_alone_never_loosens():
    """Good precision and no missed-case evidence must produce nothing.

    This is the original asymmetry and it still holds. Absence of complaint is
    not evidence that the bar is too high.
    """
    assert propose(report(0.95)) == ()
    assert propose(report(0.95), surfaced=None) == ()


def test_both_errors_high_never_loosens():
    """Precision below the floor blocks loosening however bad the miss rate.

    Both errors high at once means the model is wrong. Moving a threshold in
    either direction trades one harm for the other rather than fixing anything.
    """
    surfaced = book(caught=10, missed_on="consistency", missed=9).report()
    proposals = propose(report(0.42), surfaced=surfaced)

    assert report(0.42).realised_precision < PRECISION_FLOOR
    assert [p.direction for p in proposals] == ["tighten", "tighten"], (
        "loosened a gate while precision was already failing"
    )


def test_loosening_respects_the_step_cap_and_the_floor():
    """A catastrophic miss rate still may not remove a gate."""
    surfaced = book(caught=1, missed_on="evidence", missed=40).report()
    proposals = propose(report(0.99), surfaced=surfaced)
    loosen = [p for p in proposals if p.direction == "loosen"]

    assert len(loosen) == 1
    moved = GATE_THRESHOLDS["evidence"] - loosen[0].proposed
    assert moved <= 0.05 + 1e-9, f"moved {moved} in a single step"
    assert loosen[0].proposed >= 0.40, "a gate was lowered out of existence"


def test_too_few_surfaced_cases_proposes_nothing():
    surfaced = book(caught=2, missed_on="consistency", missed=3).report()
    assert not surfaced.enough_evidence
    assert [p for p in propose(report(0.9), surfaced=surfaced) if p.direction == "loosen"] == []
