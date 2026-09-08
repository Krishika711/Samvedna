"""Consistency gate — do the domains agree, or is one anomaly shouting?

Row 7 of PART 6.65 is the row this whole system exists to produce: a person with
a strong, sustained, multi-domain deviation who is NOT named, because 40% of
their unit shows the same pattern and the unit is deployed. Consistency lands at
0.694 against a 0.700 threshold and the verdict flips to MONITOR.
"""
from __future__ import annotations

import pytest
from tests.conftest import case, deviation, unit

from samvedna.core.confounders import detect
from samvedna.core.gates import consistency


def test_row_three_agreeing_domains_no_confounder_is_1_000():
    ctx = case(deviation("self_report"), deviation("leave"), deviation("duty_roster"))
    assert consistency(ctx).value == pytest.approx(1.000, abs=5e-4)


def test_row_unit_wide_op_tempo_drops_consistency_to_0_694():
    """THE demo case. 0.694 against a 0.700 threshold — no name is produced."""
    ctx = case(
        deviation("self_report"),
        deviation("leave"),
        deviation("duty_roster"),
        unit_state=unit(
            deviating={"self_report": 0.45, "leave": 0.52, "duty_roster": 0.61}
        ),
    )
    gate = consistency(ctx)
    assert gate.value == pytest.approx(0.694, abs=5e-4)
    assert not gate.passed
    assert gate.value < 0.700
    # And the officer can see why, mechanically.
    assert "unit_op_tempo" in gate.inputs["confounders"]


def test_row_single_domain_plus_data_gap_fails():
    """PART 6.65 prints 0.467 here; this build computes 0.000. Same outcome, and
    the difference is deliberate — see the docstring in `gates.consistency`.

    0.467 is w/(w+0.8) with the domain's own weight in the numerator, i.e. the
    domain corroborating itself. Under that rule the demo case in row 7 computes
    to 0.774 and *passes* the 0.700 threshold, which would destroy the single
    most defensible moment in the design. Excluding self reproduces row 7 exactly
    (25/36 = 0.6944) and makes a lone confounded domain score 0, which is the
    honest answer: one domain has no corroboration at all.
    """
    ctx = case(deviation("leave", missing=0.35))
    gate = consistency(ctx)
    assert gate.value == pytest.approx(0.000, abs=5e-4)
    assert not gate.passed
    assert "data_gap" in gate.inputs["confounders"]


def test_a_lone_domain_is_never_consistent_with_anything():
    for domain in ("self_report", "leave", "transfer"):
        assert consistency(case(deviation(domain))).value == 0.0


def test_confounder_mass_reduces_the_score():
    clean = case(deviation("leave"), deviation("duty_roster"), deviation("workload"))
    confounded = case(
        deviation("leave"),
        deviation("duty_roster"),
        deviation("workload"),
        unit_state=unit(deviating={"leave": 0.9}),
    )
    assert consistency(confounded).value < consistency(clean).value


def test_contradicting_direction_reduces_agreement():
    agreeing = case(
        deviation("leave"), deviation("duty_roster"), deviation("workload")
    )
    mixed = case(
        deviation("leave"),
        deviation("duty_roster"),
        deviation("workload", direction="reduced"),
    )
    assert consistency(mixed).value < consistency(agreeing).value


def test_zero_denominator_yields_zero_not_an_exception():
    ctx = case()
    gate = consistency(ctx)
    assert gate.value == 0.0
    assert not gate.passed


def test_data_gap_is_the_heaviest_rule_in_the_book():
    """Mass 0.80 — heavier than op tempo. Missingness is never treated as signal."""
    from samvedna.config.thresholds import CONFOUNDER_MASS

    assert CONFOUNDER_MASS["data_gap"] == max(CONFOUNDER_MASS.values())


def test_a_window_wide_data_gap_collapses_consistency():
    """A connector failure affects the whole window, not one domain, so this is
    the shape a real data gap takes — and it takes the case below threshold."""
    ctx = case(
        deviation("leave", missing=0.5),
        deviation("duty_roster", missing=0.5),
        deviation("workload", missing=0.5),
    )
    gate = consistency(ctx)
    assert gate.value == pytest.approx(0.636, abs=5e-4)
    assert not gate.passed


def test_a_gapped_domain_corroborates_its_neighbours_only_weakly():
    """You cannot corroborate with data you do not have.

    `leave` is missing 34% of its records, so it keeps only 20% of its normal
    corroborative strength when supporting duty_roster and workload — and it is
    not discarded, which would be the other error. The case lands at 0.612 and
    fails, correctly: three domains that lean on one unreliable one are not three
    independent witnesses.
    """
    ctx = case(
        deviation("leave", missing=0.5),
        deviation("duty_roster"),
        deviation("workload"),
    )
    hits = detect(ctx)
    assert [h.rule for h in hits] == ["data_gap"]
    gate = consistency(ctx)
    assert gate.value == pytest.approx(0.612, abs=5e-4)
    assert not gate.passed
    assert "0.84/(1.40+0.00)" in gate.inputs["per_domain"], (
        "the officer must be able to see the discount, not just its effect"
    )


def test_domains_sharing_a_confounder_are_not_discounted_against_each_other():
    """Row 7 is preserved precisely because of this. When every domain shares the
    same benign explanation, nothing is unshared and the mass alone does the work
    — which is what the published 0.694 was computed with."""
    ctx = case(
        deviation("self_report"),
        deviation("leave"),
        deviation("duty_roster"),
        unit_state=unit(
            deviating={"self_report": 0.45, "leave": 0.52, "duty_roster": 0.61}
        ),
    )
    gate = consistency(ctx)
    assert gate.value == pytest.approx(0.694, abs=5e-4)
    assert "1.40/(1.40+0.70)" in gate.inputs["per_domain"], "no discount applied"


def test_an_unconfounded_domain_cannot_score_1_000_on_confounded_support():
    """The flaw this fix exists for. A jawan in a surged unit deviating in
    deployment plus three surge-explained domains scored deployment at
    2.10/(2.10+0) = 1.000 under the naive formula — full marks for being
    corroborated by three domains that agree only because they share a cause."""
    ctx = case(
        deviation("deployment"),
        deviation("duty_roster"),
        deviation("leave"),
        deviation("workload"),
        unit_state=unit(deviating={"duty_roster": 0.60, "leave": 0.48, "workload": 0.68}),
    )
    gate = consistency(ctx)
    per_domain = gate.inputs["per_domain"]
    deployment_term = next(t for t in per_domain.split(" | ") if t.startswith("deployment"))
    assert not deployment_term.endswith("1.000"), deployment_term
    assert gate.value < 0.70, "the whole case must fail, not just the one domain"


def test_unit_tempo_below_threshold_does_not_fire():
    ctx = case(
        deviation("leave"),
        deviation("duty_roster"),
        deviation("workload"),
        unit_state=unit(deviating={"leave": 0.39}),
    )
    assert consistency(ctx).value == pytest.approx(1.000, abs=5e-4)


def test_unit_tempo_at_threshold_fires():
    ctx = case(
        deviation("leave"),
        deviation("duty_roster"),
        deviation("workload"),
        unit_state=unit(deviating={"leave": 0.40}),
    )
    assert consistency(ctx).value < 1.0
