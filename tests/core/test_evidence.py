"""Evidence gate — every calibration row in PART 6.65 reproduced exactly.

These are not regression snapshots. They are the numbers the design was published
with, and if one of them moves, the published design moved with it.
"""
from __future__ import annotations

import pytest
from tests.conftest import case, consent, deviation

from samvedna.core.gates import evidence


def value(*domains: str, **kw) -> float:
    return evidence(case(*[deviation(d) for d in domains], **kw)).value


def test_row_t1_plus_leave_plus_roster_is_1_000():
    assert value("self_report", "leave", "duty_roster") == pytest.approx(1.000, abs=5e-4)


def test_row_three_t2_plus_t3_is_0_800():
    assert value("leave", "duty_roster", "workload", "transfer") == pytest.approx(
        0.800, abs=5e-4
    )


def test_row_t2_t2_t3_is_0_675_just_clears():
    got = value("leave", "duty_roster", "transfer")
    assert got == pytest.approx(0.675, abs=5e-4)
    assert got >= 0.65, "this row is documented as clearing the gate"


def test_row_t2_alone_is_0_246_and_fails():
    got = value("leave")
    assert got == pytest.approx(0.246, abs=5e-4)
    assert got < 0.65


def test_row_t3_alone_is_0_183_and_fails():
    got = value("transfer")
    assert got == pytest.approx(0.183, abs=5e-4)
    assert got < 0.65


def test_one_domain_can_never_clear_the_gate():
    """No single domain, at any tier, reaches 0.65. This is structural."""
    from samvedna.config.weights import ALL_DOMAINS

    for domain in ALL_DOMAINS:
        assert value(domain) < 0.65, f"{domain} alone cleared the evidence gate"


def test_t1_outweighs_t3():
    assert value("self_report") > value("transfer")


def test_breadth_is_required_not_optional():
    """Three T3 domains beat one T2, because breadth is 30% of the gate."""
    assert value("transfer", "training", "biometric") > value("leave")


def test_a_self_assessment_is_worth_one_fifth_of_the_gate():
    with_t1 = value("self_report", "leave", "duty_roster")
    without = value("biometric", "leave", "duty_roster")
    # Same breadth (3), different volume and T1 presence.
    assert with_t1 - without == pytest.approx(0.20 + 0.50 * (2.4 - 1.8) / 2.4, abs=1e-9)


def test_unconsented_domains_do_not_count_toward_evidence():
    ctx = case(
        deviation("self_report"),
        deviation("leave"),
        deviation("duty_roster"),
        consent_state=consent(scope=("leave",)),
    )
    assert evidence(ctx).value == pytest.approx(0.246, abs=5e-4)


def test_formula_string_carries_the_actual_numbers():
    gate = evidence(case(deviation("leave"), deviation("duty_roster"), deviation("transfer")))
    assert "0.50x0.750" in gate.formula
    assert "0.30x1.000" in gate.formula
    assert "= 0.675" in gate.formula
    assert gate.inputs["weighted_volume"] == pytest.approx(1.8)
