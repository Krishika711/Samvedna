"""Differential privacy for anything aggregate that leaves the system.

Every number on a commander's screen has passed through here. The guarantee is
the ordinary one — an individual's contribution to a released statistic is not
inferable from the statistic — and the reason it is needed even after
k-anonymity is subtraction: two k-anonymous views of overlapping cohorts, taken a
day apart, can isolate one person between them. Noise is what stops that.

The budget is finite and accounted. A dashboard that can be refreshed without
limit is a dashboard with no privacy guarantee at all, so `Budget.spend` raises
when the epsilon for a period is exhausted rather than quietly serving one more.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from samvedna.config.thresholds import DP_EPSILON_PER_QUERY, DP_TOTAL_BUDGET

__all__ = ["Budget", "BudgetExhausted", "laplace", "noisy_count", "noisy_mean"]


class BudgetExhausted(RuntimeError):
    """Refusing to release another statistic under this period's budget."""


@dataclass
class Budget:
    """Per-period privacy budget accounting, in epsilon.

    Deliberately not resettable by the caller: a caller who can reset the budget
    has no budget. Rotation happens on the period boundary, in the orchestrator.
    """

    total: float = DP_TOTAL_BUDGET
    spent: float = 0.0
    log: list[tuple[str, float]] = field(default_factory=list)

    @property
    def remaining(self) -> float:
        return max(0.0, self.total - self.spent)

    def spend(self, label: str, epsilon: float = DP_EPSILON_PER_QUERY) -> float:
        if epsilon > self.remaining:
            raise BudgetExhausted(
                f"{label}: needs eps={epsilon:.3f}, only {self.remaining:.3f} remains "
                f"of {self.total:.3f} for this period"
            )
        self.spent += epsilon
        self.log.append((label, epsilon))
        return epsilon


def laplace(scale: float, rng: random.Random | None = None) -> float:
    """One Laplace sample. `rng` is injectable so tests are deterministic."""
    r = rng or random
    u = r.random() - 0.5
    return -scale * math.copysign(1.0, u) * math.log(1 - 2 * abs(u))


def noisy_count(
    true_count: int,
    budget: Budget,
    label: str,
    *,
    epsilon: float = DP_EPSILON_PER_QUERY,
    rng: random.Random | None = None,
) -> int:
    """A count with Laplace noise. Sensitivity 1: one person changes it by one.

    Clamped at zero because a negative headcount on a commander's screen invites
    exactly the wrong question — "why does this say minus two?" — and the answer
    would require explaining the noise, which defeats the purpose.
    """
    budget.spend(label, epsilon)
    return max(0, round(true_count + laplace(1.0 / epsilon, rng)))


def noisy_mean(
    true_mean: float,
    n: int,
    budget: Budget,
    label: str,
    *,
    value_range: float = 1.0,
    epsilon: float = DP_EPSILON_PER_QUERY,
    rng: random.Random | None = None,
) -> float:
    """A mean with noise scaled to how much one person could move it."""
    if n <= 0:
        return 0.0
    budget.spend(label, epsilon)
    sensitivity = value_range / n
    return round(true_mean + laplace(sensitivity / epsilon, rng), 4)
