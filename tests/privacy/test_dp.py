"""Differential privacy on aggregates, and a budget that actually runs out."""
from __future__ import annotations

import random
from statistics import mean

import pytest

from samvedna.ingest.dp import Budget, BudgetExhausted, laplace, noisy_count, noisy_mean


def test_noise_is_centred_on_the_truth():
    rng = random.Random(1)
    budget = Budget(total=10_000)
    samples = [noisy_count(100, budget, "t", rng=rng) for _ in range(3000)]
    assert mean(samples) == pytest.approx(100, abs=2)


def test_noise_is_actually_applied():
    rng = random.Random(2)
    budget = Budget(total=10_000)
    samples = {noisy_count(100, budget, "t", rng=rng) for _ in range(200)}
    assert len(samples) > 5, "a 'DP' function that returns the true value is not DP"


def test_a_count_never_goes_negative():
    rng = random.Random(3)
    budget = Budget(total=10_000)
    assert all(noisy_count(0, budget, "t", rng=rng) >= 0 for _ in range(500))


def test_smaller_epsilon_means_more_noise():
    def spread(eps):
        rng = random.Random(4)
        b = Budget(total=1e9)
        vals = [noisy_count(100, b, "t", epsilon=eps, rng=rng) for _ in range(2000)]
        return max(vals) - min(vals)

    assert spread(0.1) > spread(1.0)


def test_a_mean_is_noised_in_proportion_to_how_much_one_person_could_move_it():
    rng = random.Random(5)

    def spread(n):
        b = Budget(total=1e9)
        vals = [noisy_mean(0.5, n, b, "t", rng=rng) for _ in range(2000)]
        return max(vals) - min(vals)

    assert spread(5) > spread(500), "a small cohort must be noised harder"


def test_the_budget_is_spent_and_logged():
    b = Budget(total=1.0)
    b.spend("unit-fatigue", 0.4)
    b.spend("leave-denial", 0.4)
    assert b.remaining == pytest.approx(0.2)
    assert [label for label, _ in b.log] == ["unit-fatigue", "leave-denial"]


def test_an_exhausted_budget_refuses_rather_than_serving_one_more():
    """A dashboard that can be refreshed without limit has no privacy guarantee."""
    b = Budget(total=1.0)
    b.spend("first", 0.9)
    with pytest.raises(BudgetExhausted) as excinfo:
        noisy_count(10, b, "second", epsilon=0.5)
    assert "remains" in str(excinfo.value)


def test_the_caller_cannot_reset_the_budget():
    b = Budget(total=1.0)
    b.spend("first", 1.0)
    assert not hasattr(b, "reset")
    assert b.remaining == 0.0


def test_laplace_is_deterministic_under_a_seeded_rng():
    assert laplace(1.0, random.Random(9)) == laplace(1.0, random.Random(9))
