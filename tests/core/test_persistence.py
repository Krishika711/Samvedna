"""Persistence gate — sustained, not a blip.

PART 6.65 gives outputs without stating the daily-breach inputs behind them, so
each test states the inputs it uses and reproduces the published value exactly.
The "one bad week" row is the strongest confirmation the formula is right: the
natural inputs for a single breaching week (7/7, 7/30, 7/90) land on 0.332 with
no tuning at all.
"""
from __future__ import annotations

import pytest
from tests.conftest import case, deviation

from samvedna.config.weights import (
    PERSISTENCE_W_7D,
    PERSISTENCE_W_30D,
    PERSISTENCE_W_90D,
)
from samvedna.core.gates import persistence


def test_window_weights_sum_to_one():
    assert pytest.approx(1.0) == PERSISTENCE_W_7D + PERSISTENCE_W_30D + PERSISTENCE_W_90D


def test_row_sustained_three_months_is_0_965():
    ctx = case(deviation("leave", breach={7: 1.0, 30: 1.0, 90: 0.9}))
    gate = persistence(ctx)
    assert gate.value == pytest.approx(0.965, abs=5e-4)
    assert gate.passed


def test_row_month_long_breach_is_0_720():
    ctx = case(deviation("leave", breach={7: 1.0, 30: 1.0, 90: 0.2}))
    gate = persistence(ctx)
    assert gate.value == pytest.approx(0.720, abs=5e-4)
    assert gate.passed


def test_row_one_bad_week_is_0_332_and_fails():
    """7 breaching days: 7/7, 7/30, 7/90. No tuning — the formula lands on it."""
    ctx = case(deviation("leave", breach={7: 1.0, 30: 7 / 30, 90: 7 / 90}))
    gate = persistence(ctx)
    assert gate.value == pytest.approx(0.332, abs=5e-4)
    assert not gate.passed


def test_a_single_acute_event_cannot_clear_this_gate():
    """One day. The safety override exists precisely because this is correct."""
    ctx = case(deviation("self_report", breach={7: 1 / 7, 30: 1 / 30, 90: 1 / 90}))
    assert persistence(ctx).value < 0.60


def test_extending_a_breach_never_lowers_persistence():
    short = case(deviation("leave", breach={7: 1.0, 30: 0.3, 90: 0.1}))
    longer = case(deviation("leave", breach={7: 1.0, 30: 0.6, 90: 0.2}))
    assert persistence(longer).value >= persistence(short).value


def test_multi_domain_persistence_is_weighted_by_domain_weight():
    """A sustained T1 breach counts for more than a sustained T3 one."""
    t1_sustained = case(
        deviation("self_report", breach={7: 1.0, 30: 1.0, 90: 1.0}),
        deviation("transfer", breach={7: 0.0, 30: 0.0, 90: 0.0}),
    )
    t3_sustained = case(
        deviation("self_report", breach={7: 0.0, 30: 0.0, 90: 0.0}),
        deviation("transfer", breach={7: 1.0, 30: 1.0, 90: 1.0}),
    )
    assert persistence(t1_sustained).value > persistence(t3_sustained).value


def test_single_domain_reduces_to_that_domains_fractions():
    breach = {7: 0.4, 30: 0.7, 90: 0.55}
    got = persistence(case(deviation("workload", breach=breach))).value
    expected = 0.20 * 0.4 + 0.45 * 0.7 + 0.35 * 0.55
    assert got == pytest.approx(expected)


def test_no_deviations_yields_zero():
    assert persistence(case()).value == 0.0


# ---------------------------------------------------------------------------
# Absent is not zero.
#
# This gate used to read `d.daily_breach.get(days, 0.0)` across every domain,
# so a domain with no history for a window contributed nothing to the numerator
# while still contributing its full weight to the denominator — diluting every
# domain that did have history.
#
# The harm ran in the worst possible direction. A jawan who submitted a severe
# self-assessment, one response old by definition and carrying the highest tier
# weight, pushed their own persistence from 0.650 (passing) to 0.505 (failing).
# Reporting distress made the system less likely to act. Twelve of 125
# monitored cases flipped that way.
#
# The rule is one the ingest layer already stated: a connector returning
# nothing must not read as a low value, and `Series.breach_fraction` divides by
# the window length rather than the row count for the same reason. Persistence
# was the one place it had not been applied.
# ---------------------------------------------------------------------------

def test_a_window_with_no_observations_does_not_dilute_the_others():
    sustained = deviation("deployment", breach={7: 1.0, 30: 1.0, 90: 1.0})
    # A T1 domain with only a short-window reading — a fresh questionnaire.
    fresh = deviation("self_report", breach={7: 1.0})

    alone = persistence(case(sustained))
    with_fresh = persistence(case(sustained, fresh))

    assert with_fresh.value >= alone.value, (
        f"adding a T1 domain lowered persistence: {alone.value:.3f} -> "
        f"{with_fresh.value:.3f}"
    )


def test_an_observed_zero_still_counts_against_persistence():
    """`breach[30] = 0.0` is a measurement. `30 not in breach` is not.

    Conflating them in the other direction would be just as wrong: a domain
    observed across thirty days with no breaches genuinely argues against
    persistence, and must not be quietly excluded for looking inconvenient.
    """
    sustained = deviation("deployment", breach={7: 1.0, 30: 1.0, 90: 1.0})
    observed_quiet = deviation("workload", breach={7: 0.0, 30: 0.0, 90: 0.0})

    alone = persistence(case(sustained))
    with_quiet = persistence(case(sustained, observed_quiet))

    assert with_quiet.value < alone.value, (
        "a domain observed as quiet was excluded instead of counted"
    )


def test_no_window_observed_at_all_is_zero_not_a_crash():
    """Conservative, and it must not divide by zero."""
    assert persistence(case(deviation("self_report", breach={}))).value == 0.0


def test_the_published_rows_are_unaffected_by_the_change():
    """Every domain in a published row carries all three windows.

    So "exclude the unobserved" reduces to the original weighted mean exactly,
    which is why the calibration figures in PART 6.65 did not move. Stated as a
    test because "it happens to still work" is not the same as "it cannot
    change".
    """
    # One bad week: 7/7, 7/30, 7/90 -> the published 0.332.
    week = deviation("workload", breach={7: 1.0, 30: 7 / 30, 90: 7 / 90})
    assert persistence(case(week)).value == pytest.approx(0.332, abs=5e-4)
