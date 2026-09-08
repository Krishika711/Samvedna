"""The tabular risk model. An input to the gates, never a decision.

Gradient-boosted trees on aggregated window features, isotonically calibrated,
and selected for **precision rather than F1** — consistent with the gate
philosophy and with the fact that the cost of a false positive here is a soldier
wrongly named.

The backend is scikit-learn rather than LightGBM, and that is a portability
decision rather than a modelling one. LightGBM's wheels link against `libomp`,
which on macOS is a Homebrew install and simply absent on a clean machine — the
first attempt to train here died with `Library not loaded: @rpath/libomp.dylib`.
A system that has to survive being copied onto a pendrive or emailed as an
attachment cannot carry a native dependency the recipient has to go and install.
Gradient boosting from scikit-learn is the same algorithm family, ships
self-contained, and is fully supported by SHAP's TreeExplainer.

Two things about this module matter more than its accuracy:

1. **It degrades rather than failing.** If LightGBM is not installed, or the
   model file is missing, `score` returns `status="unavailable"` and the pipeline
   carries on. The gates do not need a score to reach a verdict — evidence,
   consistency, persistence and actionability are all computed from deviations.
   A system that stops naming people when the model is missing is behaving
   correctly; a system that stops *running* is not.
2. **It cannot emit a verdict.** `RiskAssessment` has no field for one. The
   strongest possible score, 1.000, changes no gate value and no decision. There
   is a test for that, because it is the claim the whole design rests on.

Labels are scarce and sensitive. In this build they come from the synthetic
cohort's latent strain, and everything trained on them is **marked synthetic and
must never be reported as validation** (PART 9).
"""
from __future__ import annotations

import hashlib
import json
import pickle
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from samvedna.analytics.features.store import FeatureStore
from samvedna.config.weights import ALL_DOMAINS
from samvedna.config.windows import WINDOWS_DAYS
from samvedna.core.types import RiskAssessment

__all__ = [
    "FEATURE_NAMES",
    "SURVIVAL_HORIZON_DAYS",
    "TabularModel",
    "features_for",
    "load_model",
]

# The horizon the model is asked about. "Elevated risk within 60 days" is far
# more actionable than "elevated risk", because a welfare officer schedules
# things.
SURVIVAL_HORIZON_DAYS = 60

# Feature names are the vocabulary the intervention matcher reads, so they carry
# the domain in the name on purpose: a SHAP driver called
# `leave_mean_30d` matches the WLF-LEAVE playbook entry without a mapping table.
FEATURE_NAMES: tuple[str, ...] = tuple(
    f"{domain}_mean_{days}d" for domain in ALL_DOMAINS for days in WINDOWS_DAYS
) + tuple(f"{domain}_slope" for domain in ALL_DOMAINS)


def features_for(store: FeatureStore, pid: str, as_of: date) -> dict[str, float]:
    """One row: window means per domain, plus a short-versus-long slope.

    The slope is what turns a level into a trend. Two jawans with the same
    30-day mean are different people if one is climbing and one is settling, and
    a model given only levels cannot tell them apart.
    """
    row: dict[str, float] = dict.fromkeys(FEATURE_NAMES, 0.0)
    for domain in ALL_DOMAINS:
        means = store.window_means(pid, domain, as_of)  # type: ignore[arg-type]
        for days in WINDOWS_DAYS:
            row[f"{domain}_mean_{days}d"] = round(means.get(days, 0.0), 6)
        short, long = means.get(min(WINDOWS_DAYS), 0.0), means.get(max(WINDOWS_DAYS), 0.0)
        row[f"{domain}_slope"] = round(short - long, 6)
    return row


@dataclass(frozen=True, slots=True)
class ModelCard:
    """What was trained, on what, and how well. Published, not buried.

    PART 9 asks for per-subgroup performance to be reported and the gaps
    published. An unusable model that is honest about its blind spots is worth
    more here than an accurate one that quietly under-serves a rank.
    """

    version: str
    trained_on: str
    n_train: int
    n_test: int
    positive_rate: float
    auroc: float
    precision_at_threshold: float
    recall_at_threshold: float
    operating_threshold: float
    calibration_error: float
    subgroup: dict[str, dict[str, float]]
    backend: str = "sklearn"
    # SHA-256 of the persisted estimator, written at train time and verified at
    # load time. Loading an estimator means unpickling it, and an unverified
    # pickle in a nightly batch is a remote-code-execution primitive. The check
    # does not make an untrusted model safe — it makes a *modified* one refuse
    # to load, which is the property that matters for a file that travels.
    digest: str = ""
    synthetic: bool = True

    def to_json(self) -> str:
        from dataclasses import asdict

        return json.dumps(asdict(self), indent=2, sort_keys=True)


class TabularModel:
    """Wraps a fitted booster and a calibrator. Reports drivers via TreeSHAP."""

    def __init__(self, booster, calibrator, card: ModelCard, top_k: int = 3) -> None:
        self._booster = booster
        self._calibrator = calibrator
        self.card = card
        self.top_k = top_k
        self._explainer = None

    @property
    def version(self) -> str:
        return self.card.version

    def _shap_drivers(self, row: list[float]) -> tuple[tuple[str, float], ...]:
        """Top-k contributions. Falls back to the booster's own contributions if
        SHAP is unavailable — a case with no drivers is a case an officer cannot
        act on, so this degrades to something rather than to nothing."""
        try:
            import numpy as np
            import shap

            if self._explainer is None:
                self._explainer = shap.TreeExplainer(self._booster)
            values = self._explainer.shap_values(np.array([row]))
            contributions = list(np.ravel(values)[: len(FEATURE_NAMES)])
        except Exception:
            importances = getattr(self._booster, "feature_importances_", None)
            if importances is None:
                return ()
            contributions = [
                float(imp) * float(value)
                for imp, value in zip(importances, row, strict=False)
            ]
        ranked = sorted(
            zip(FEATURE_NAMES, contributions, strict=False),
            key=lambda kv: -abs(kv[1]),
        )
        return tuple((name, round(float(v), 5)) for name, v in ranked[: self.top_k])

    def score(self, pid: str, row: dict[str, float]) -> RiskAssessment:
        try:
            import numpy as np

            vector = [row.get(name, 0.0) for name in FEATURE_NAMES]
            matrix = np.array([vector])
            if hasattr(self._booster, "predict_proba"):
                raw = float(self._booster.predict_proba(matrix)[0][1])
            else:
                raw = float(self._booster.predict(matrix)[0])
            calibrated = float(self._calibrator.predict([raw])[0]) if self._calibrator else raw
            return RiskAssessment(
                pid=pid,
                score=max(0.0, min(1.0, calibrated)),
                horizon_days=SURVIVAL_HORIZON_DAYS,
                drivers=self._shap_drivers(vector),
                model_version=self.version,
            )
        except Exception:
            return unavailable(pid)


def unavailable(pid: str, version: str = "unavailable") -> RiskAssessment:
    """The honest answer when there is no model. The pipeline continues."""
    return RiskAssessment(
        pid=pid,
        score=0.0,
        horizon_days=SURVIVAL_HORIZON_DAYS,
        drivers=(),
        model_version=version,
        status="unavailable",
    )


def digest_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_model(model_dir: str | Path) -> TabularModel | None:
    """Load a trained model, or return None. Never raises on a missing model.

    A missing or tampered model is not an error condition for this system. The
    gates do not need a score — evidence, consistency, persistence and
    actionability are all computed from deviations — so the honest response to
    "there is no model" is to carry on and say so, not to stop the nightly run.
    """
    directory = Path(model_dir)
    estimator_path = directory / "tabular.pkl"
    card_path = directory / "tabular_card.json"
    if not estimator_path.exists() or not card_path.exists():
        return None
    try:
        card = ModelCard(**json.loads(card_path.read_text(encoding="utf-8")))
        if card.digest and digest_of(estimator_path) != card.digest:
            # Refuse rather than unpickle something the card did not vouch for.
            return None
        with estimator_path.open("rb") as handle:
            booster = pickle.load(handle)  # noqa: S301 - digest verified above
        calibrator = None
        iso_path = directory / "tabular_isotonic.json"
        if iso_path.exists():
            calibrator = _IsotonicFromJson(json.loads(iso_path.read_text(encoding="utf-8")))
        return TabularModel(booster, calibrator, card)
    except Exception:
        return None


class _IsotonicFromJson:
    """A pickle-free isotonic calibrator.

    Deliberately not `joblib.load`: a model directory that can execute arbitrary
    code on load is a remote-code-execution primitive sitting in the nightly
    batch. Two float arrays and an interpolation are all that is needed.
    """

    __slots__ = ("_x", "_y")

    def __init__(self, payload: dict) -> None:
        self._x = payload["x"]
        self._y = payload["y"]

    def predict(self, values):
        out = []
        for v in values:
            if v <= self._x[0]:
                out.append(self._y[0])
            elif v >= self._x[-1]:
                out.append(self._y[-1])
            else:
                lo = max(i for i, x in enumerate(self._x) if x <= v)
                hi = min(lo + 1, len(self._x) - 1)
                span = self._x[hi] - self._x[lo]
                frac = 0.0 if span == 0 else (v - self._x[lo]) / span
                out.append(self._y[lo] + frac * (self._y[hi] - self._y[lo]))
        return out
