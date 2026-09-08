"""Actionability gate — multiplicative, and three of its terms are hard vetoes.

The numeric argument in PART 6.5 is reproduced as a test: a weighted-sum version
of this gate lets a person who never consented to being contacted score 0.85 and
clear a 0.50 threshold. The gate would leak in the one direction that matters, so
`test_a_weighted_sum_would_leak` exists to stop anyone "simplifying" it back.
"""
from __future__ import annotations

import pytest
from tests.conftest import case, consent, deviation, unit

from samvedna.core.gates import actionability
from samvedna.core.interventions import BY_CODE


def test_row_all_conditions_met_is_1_000():
    gate = actionability(case(deviation("leave"), deviation("duty_roster")))
    assert gate.value == pytest.approx(1.000, abs=5e-4)
    assert gate.passed


def test_row_capacity_exhausted_only_is_0_750_and_still_passes():
    """The one soft term. A genuine case is queued, never silently dropped."""
    gate = actionability(
        case(deviation("leave"), deviation("duty_roster"), unit_state=unit(capacity=False))
    )
    assert gate.value == pytest.approx(0.750, abs=5e-4)
    assert gate.passed


def test_row_duplicate_active_intervention_is_zero():
    gate = actionability(
        case(deviation("leave"), active=(BY_CODE["WLF-LEAVE"],))
    )
    assert gate.value == 0.0
    assert not gate.passed
    assert gate.inputs["duplicate_of"] == "WLF-LEAVE"


def test_row_consent_absent_is_zero():
    gate = actionability(
        case(deviation("leave"), consent_state=consent(welfare_contact=False))
    )
    assert gate.value == 0.0
    assert not gate.passed


def test_no_matching_intervention_is_zero():
    ctx = case(deviation("leave"), suppressed=("leave",))
    assert actionability(ctx).value == 0.0


def test_a_weighted_sum_would_leak_which_is_why_this_gate_multiplies():
    """The concrete number from PART 6.5, reproduced so nobody re-derives it wrong."""
    match, capacity, not_duplicate, consent_ok = 1, 1, 1, 0  # no consent to contact
    leaky = 0.40 * match + 0.20 * capacity + 0.25 * not_duplicate + 0.15 * consent_ok
    assert leaky == pytest.approx(0.85)
    assert leaky >= 0.50, "a weighted sum clears the threshold with no consent"

    gate = actionability(
        case(deviation("leave"), consent_state=consent(welfare_contact=False))
    )
    assert gate.value == 0.0, "the multiplicative gate vetoes it"


def test_revoked_consent_vetoes_even_if_welfare_contact_flag_is_set():
    gate = actionability(
        case(deviation("leave"), consent_state=consent(status="REVOKED"))
    )
    assert gate.value == 0.0


def test_capacity_lowers_but_never_blocks():
    with_capacity = actionability(case(deviation("leave"))).value
    without = actionability(case(deviation("leave"), unit_state=unit(capacity=False))).value
    assert without < with_capacity
    assert without >= 0.50
