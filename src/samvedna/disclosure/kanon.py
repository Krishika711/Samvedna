"""k-anonymity for the commander's view. Suppress, never round.

Rounding a cell of three to "fewer than five" still tells you it was not zero,
and two rounded views of overlapping cohorts taken a day apart can isolate one
person between them. Suppression removes the cell, and the suppressed cell says
so plainly — "insufficient cohort" is information a commander can act on (raise
welfare capacity) without being information about a person.

The commander view is also where differential privacy is applied, because these
are the only numbers that leave the system in aggregate form.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from samvedna.config.thresholds import K_ANONYMITY_MIN
from samvedna.ingest.dp import Budget, noisy_count, noisy_mean

__all__ = ["Cell", "SUPPRESSED", "aggregate", "k_min"]

SUPPRESSED = "insufficient cohort"


def k_min() -> int:
    return K_ANONYMITY_MIN


@dataclass(frozen=True, slots=True)
class Cell:
    """One number on a commander's screen, or the absence of one."""

    label: str
    n: int
    value: float | None
    suppressed: bool
    reason: str = ""

    @property
    def display(self) -> str:
        return SUPPRESSED if self.suppressed else f"{self.value:.2f}"

    def to_dict(self) -> dict:
        # A suppressed cell must not leak its true n either: "n=3" is the same
        # disclosure as the value would have been.
        if self.suppressed:
            return {"label": self.label, "suppressed": True, "reason": self.reason}
        return {
            "label": self.label,
            "suppressed": False,
            "n": self.n,
            "value": round(self.value or 0.0, 4),
        }


def aggregate(
    label: str,
    values: list[float],
    budget: Budget,
    *,
    differential_privacy: bool = True,
    rng: random.Random | None = None,
) -> Cell:
    """One aggregate cell, k-checked then DP-noised."""
    n = len(values)
    if n < K_ANONYMITY_MIN:
        return Cell(
            label=label,
            n=0,
            value=None,
            suppressed=True,
            reason=f"cohort below k={K_ANONYMITY_MIN}",
        )
    mean = sum(values) / n
    if differential_privacy:
        noisy_n = noisy_count(n, budget, f"{label}:n", rng=rng)
        value = noisy_mean(mean, n, budget, f"{label}:mean", rng=rng)
        # Noise must not push a cell back below k in the eyes of a reader.
        return Cell(label, max(K_ANONYMITY_MIN, noisy_n), value, suppressed=False)
    return Cell(label, n, round(mean, 4), suppressed=False)
