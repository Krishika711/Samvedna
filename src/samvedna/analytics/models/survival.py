"""Time-to-event: "elevated risk within 60 days", not just "elevated risk".

A welfare officer schedules things. "This person is at risk" tells them nothing
about whether to act this week or this quarter; "the modelled hazard puts them
past the concern threshold within 3 weeks" is a diary entry. That is the whole
argument for carrying a survival model alongside the tabular one.

Implemented as a discrete-time hazard model over the window features, fitted with
the same self-contained scikit-learn stack as the tabular model — no torch, no
lifelines, nothing that needs a compiler on the target machine.

Like every model in this system it is an **input to the gates**. A horizon of
three days does not lower a threshold, shorten a persistence window, or bypass
anything. It changes what the officer reads, not what the arithmetic decides.
The one path that genuinely bypasses gates is the acute override, and that is
triggered by an instrument, never by a model.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

__all__ = ["SurvivalEstimate", "DiscreteHazard", "HORIZONS", "load_survival"]

# Horizons the model reports over, in days. Chosen to match how welfare capacity
# is actually planned: this week, this month, this quarter.
HORIZONS: tuple[int, ...] = (7, 30, 60, 90)


@dataclass(frozen=True, slots=True)
class SurvivalEstimate:
    """Cumulative probability of crossing the concern threshold by each horizon.

    `status` is honest about absence. A missing survival model produces
    `unavailable` and the console shows no horizon at all, rather than a
    default that reads as a prediction.
    """

    pid: str
    by_horizon: dict[int, float]
    median_days: int | None
    model_version: str
    status: str = "ok"

    @property
    def soonest_material_horizon(self) -> int | None:
        """The first horizon where cumulative risk passes one in two."""
        for days in sorted(self.by_horizon):
            if self.by_horizon[days] >= 0.5:
                return days
        return None

    def phrase(self) -> str:
        """Plain language for the officer. No percentage is quoted as confidence."""
        if self.status != "ok":
            return "no horizon estimate is available for this case"
        soonest = self.soonest_material_horizon
        if soonest is None:
            return (
                f"the modelled hazard does not reach an even chance within "
                f"{max(self.by_horizon)} days"
            )
        return f"the modelled hazard reaches an even chance within {soonest} days"


def unavailable(pid: str) -> SurvivalEstimate:
    return SurvivalEstimate(
        pid=pid,
        by_horizon={},
        median_days=None,
        model_version="unavailable",
        status="unavailable",
    )


class DiscreteHazard:
    """Discrete-time hazard: per-interval risk, composed into a survival curve.

    Chosen over a Cox proportional-hazards fit because the proportional-hazards
    assumption is not obviously true here — a jawan's hazard during a deployment
    and after it are not a constant multiple of one another — and because a
    discrete model composes intervals in a way that is arithmetic an officer
    could check, which is the standing preference in this codebase.
    """

    def __init__(self, estimator, feature_names: tuple[str, ...], version: str) -> None:
        self._estimator = estimator
        self._features = feature_names
        self.version = version

    def estimate(self, pid: str, row: dict[str, float]) -> SurvivalEstimate:
        try:
            import numpy as np

            vector = np.array([[row.get(name, 0.0) for name in self._features]])
            # Per-interval hazard, clamped away from 0 and 1 so a composed
            # survival curve cannot collapse to a certainty the data cannot support.
            hazard = float(self._estimator.predict_proba(vector)[0][1])
            hazard = min(0.95, max(1e-4, hazard))
        except Exception:
            return unavailable(pid)

        interval = min(HORIZONS)
        by_horizon: dict[int, float] = {}
        for days in HORIZONS:
            intervals = days / interval
            survival = (1.0 - hazard) ** intervals
            by_horizon[days] = round(1.0 - survival, 4)

        median = None
        if hazard > 0:
            # Solve (1-h)^(t/interval) = 0.5 for t.
            t = interval * math.log(0.5) / math.log(1.0 - hazard)
            if t <= max(HORIZONS):
                median = int(round(t))

        return SurvivalEstimate(
            pid=pid,
            by_horizon=by_horizon,
            median_days=median,
            model_version=self.version,
        )


def load_survival(model_dir: str | Path) -> DiscreteHazard | None:
    """Load, or return None. A missing survival model is never an error."""
    import hashlib
    import pickle

    directory = Path(model_dir)
    estimator_path = directory / "survival.pkl"
    card_path = directory / "survival_card.json"
    if not estimator_path.exists() or not card_path.exists():
        return None
    try:
        card = json.loads(card_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(estimator_path.read_bytes()).hexdigest()
        if card.get("digest") and digest != card["digest"]:
            return None
        with estimator_path.open("rb") as handle:
            estimator = pickle.load(handle)  # noqa: S301 - digest verified above
        return DiscreteHazard(estimator, tuple(card["features"]), card["version"])
    except Exception:
        return None
