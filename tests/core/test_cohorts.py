"""Phase 1 ship gate: all three fixture cohorts produce their intended verdicts,
through the real gate engine, with no demo branch anywhere in the path.
"""
from __future__ import annotations

import pytest

from samvedna.core.verdict import decide
from samvedna.pipeline.replay import (
    EXCLUDED_FIELDS,
    cohort_names,
    expected_verdicts,
    load_cohort,
)

COHORTS = ["escalate", "monitor", "noflag"]


@pytest.mark.parametrize("name", COHORTS)
def test_every_person_in_the_cohort_gets_their_intended_verdict(name):
    cohort = load_cohort(name)
    expected = expected_verdicts(name)
    wrong = []
    for ctx in cohort:
        got = decide(ctx).decision
        if got != expected[ctx.pid]:
            wrong.append(f"{ctx.pid}: expected {expected[ctx.pid]}, got {got}")
    assert not wrong, "\n".join(wrong)


def test_all_three_cohorts_exist():
    assert cohort_names() == COHORTS


def test_the_pipeline_can_never_read_a_fixtures_expected_verdict():
    """Constraint 8: the MONITOR path is produced by the gate engine, not a branch."""
    assert "expected" in EXCLUDED_FIELDS
    ctx = load_cohort("monitor")[0]
    assert not hasattr(ctx, "expected")
    for value in vars(ctx).values() if hasattr(ctx, "__dict__") else ():
        assert value != "MONITOR"


def test_the_demo_monitor_case_lands_on_0_694():
    ctx = next(c for c in load_cohort("monitor") if c.pid == "pid-mon-0001")
    v = decide(ctx)
    assert v.decision == "MONITOR"
    assert v.gates["consistency"].value == pytest.approx(0.694, abs=5e-4)
    assert v.gates["evidence"].passed and v.gates["persistence"].passed
    assert not v.names_a_person


def test_a_fixture_cannot_promote_its_own_tier():
    """Tier comes from config, never from the JSON — PART 6.1."""
    from samvedna.config.weights import tier_of

    for name in COHORTS:
        for ctx in load_cohort(name):
            for dev in ctx.deviations:
                assert dev.tier == tier_of(dev.domain)


@pytest.mark.parametrize("name", COHORTS)
def test_no_monitor_or_no_flag_ever_names_a_person(name):
    for ctx in load_cohort(name):
        v = decide(ctx)
        if v.decision in ("MONITOR", "NO_FLAG"):
            assert not v.names_a_person
            assert v.recommended == ()
