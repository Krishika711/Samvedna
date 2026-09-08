"""Phase 14: federated training and DP-SGD. Privacy budget reported.

PART 10's claim is that raw records never leave the unit. These tests check the
claim rather than the architecture diagram: what a unit sends, whether one
person's contribution is bounded, and whether the budget actually stops a
campaign.
"""
from __future__ import annotations

import random
from statistics import fmean

import pytest

from samvedna.analytics.models.federated import (
    CLIP_NORM,
    Coordinator,
    UnitUpdate,
    clip_to_norm,
    l2,
)


def coordinator(**kw):
    return Coordinator(dimension=5, **kw)


def updates(c, n=4, params=None, rng=None):
    rng = rng or random.Random(7)
    return [
        c.prepare_update(f"UNIT-{i:02d}", params or [0.5] * 5, 50, rng=rng)
        for i in range(n)
    ]


# --------------------------------------------- what leaves the unit, and what does not --
def test_a_unit_update_carries_parameters_and_a_count_and_nothing_else():
    fields = set(UnitUpdate.__dataclass_fields__)
    assert fields == {"unit_id", "parameters", "n_examples", "clipped", "noised"}
    for forbidden in ("records", "rows", "pids", "examples", "data", "features"):
        assert forbidden not in fields


def test_an_update_structurally_cannot_carry_a_record():
    c = coordinator()
    for update in updates(c):
        assert not update.carries_any_record()
        assert all(isinstance(v, float) for v in update.parameters)


def test_no_pid_or_service_number_appears_in_anything_that_is_sent():
    c = coordinator()
    blob = str(list(updates(c)))
    assert "pid" not in blob
    assert "UNIT-00" in blob, "the unit id is sent, and that is intended"


# ------------------------------------------------------------------- clipping --
def test_a_large_update_is_clipped_to_the_configured_norm():
    """Clipping bounds any single person's influence. Without it the noise is
    calibrated to a sensitivity nobody has measured."""
    clipped = clip_to_norm([10.0, 10.0, 10.0], CLIP_NORM)
    assert l2(clipped) == pytest.approx(CLIP_NORM, abs=1e-9)


def test_a_small_update_is_never_scaled_up():
    """Scaling a small update up would let a unit with almost no signal speak as
    loudly as one with a great deal, while the noise calibration stayed correct
    and the model quietly became wrong."""
    small = [0.01, 0.0, 0.0]
    assert clip_to_norm(small, CLIP_NORM) == small


def test_a_zero_update_survives_clipping():
    assert clip_to_norm([0.0, 0.0], CLIP_NORM) == [0.0, 0.0]


def test_the_coordinator_reports_when_an_update_was_clipped():
    c = coordinator()
    big = c.prepare_update("UNIT-01", [99.0] * 5, 50, rng=random.Random(1))
    small = c.prepare_update("UNIT-02", [0.001] * 5, 50, rng=random.Random(1))
    assert big.clipped
    assert not small.clipped


# ---------------------------------------------------------------------- noise --
def test_every_update_is_noised():
    c = coordinator()
    assert all(u.noised for u in updates(c))


def test_the_same_local_parameters_do_not_produce_the_same_update():
    c = coordinator()
    a = c.prepare_update("UNIT-01", [0.5] * 5, 50, rng=random.Random(1))
    b = c.prepare_update("UNIT-01", [0.5] * 5, 50, rng=random.Random(2))
    assert a.parameters != b.parameters


def test_noise_is_centred_so_aggregation_still_converges():
    """Noise that is not centred is a bias, not privacy."""
    c = coordinator()
    rng = random.Random(11)
    samples = [
        c.prepare_update("UNIT-01", [0.5] * 5, 50, rng=rng).parameters[0]
        for _ in range(3000)
    ]
    # The true delta is 0.5, clipped to CLIP_NORM/sqrt(5) per component.
    assert fmean(samples) == pytest.approx(clip_to_norm([0.5] * 5)[0], abs=0.05)


# ------------------------------------------------------------------ the budget --
def test_a_campaign_stops_when_its_budget_is_gone():
    """It does not continue with the noise turned down."""
    c = coordinator(total_epsilon=2.0, epsilon_per_round=1.0)
    assert not c.aggregate(updates(c)).skipped
    assert not c.aggregate(updates(c)).skipped
    third = c.aggregate(updates(c))
    assert third.skipped
    assert "budget exhausted" in third.reason
    assert "noise turned down" in third.reason


def test_a_skipped_round_does_not_change_the_parameters():
    c = coordinator(total_epsilon=1.0, epsilon_per_round=1.0)
    c.aggregate(updates(c))
    before = list(c.parameters)
    c.aggregate(updates(c))
    assert c.parameters == before


def test_the_privacy_budget_is_reported_not_assumed():
    c = coordinator(total_epsilon=3.0, epsilon_per_round=1.0)
    c.aggregate(updates(c))
    report = c.report()
    assert report["epsilon_spent"] == 1.0
    assert report["epsilon_remaining"] == 2.0
    assert report["clip_norm"] == CLIP_NORM
    assert report["noise_multiplier"] > 0
    assert report["participants"] == ["UNIT-00", "UNIT-01", "UNIT-02", "UNIT-03"]


def test_a_round_with_too_few_units_is_not_federation_and_is_refused():
    c = coordinator(min_participants=3)
    result = c.aggregate(updates(c, n=2))
    assert result.skipped
    assert "not federation" in result.reason
    assert c.spent == 0.0, "a refused round must not spend budget"


def test_aggregation_is_weighted_by_local_example_count():
    c = coordinator(total_epsilon=10.0)
    rng = random.Random(3)
    big = c.prepare_update("UNIT-01", [1.0] * 5, 1000, rng=rng)
    small = c.prepare_update("UNIT-02", [-1.0] * 5, 10, rng=rng)
    third = c.prepare_update("UNIT-03", [1.0] * 5, 1000, rng=rng)
    c.aggregate([big, small, third])
    assert c.parameters[0] > 0, "the two large units should dominate"


def test_rounds_are_recorded_so_a_campaign_is_auditable():
    c = coordinator(total_epsilon=2.0, epsilon_per_round=1.0)
    for _ in range(4):
        c.aggregate(updates(c))
    assert len(c.rounds) == 4
    assert [r.skipped for r in c.rounds] == [False, False, True, True]
    assert c.report()["rounds_completed"] == 2
    assert c.report()["rounds_skipped"] == 2
