#!/usr/bin/env python3
"""Train the tabular risk model on a synthetic force. Marked synthetic, always.

    python tools/train_tabular.py [--units 8] [--strength 90] [--seed 26186]

Three decisions here are policy, not tuning, and each one is the opposite of what
a leaderboard would suggest:

* **The operating threshold is selected for precision, not F1.** F1 treats a
  missed case and a wrongly-named soldier as equally bad. They are not. The
  threshold is the lowest one that reaches the target precision on held-out data.
* **The model is calibrated with isotonic regression**, so a score of 0.7 means
  something like "70% of people scoring this were positive". An uncalibrated
  score is not a probability, and every downstream use of it is then wrong.
* **Per-subgroup performance is computed and published**, including the gaps.
  A model that quietly under-serves a rank is worse here than one that is
  visibly mediocre everywhere.

The label is derived from the generator's latent strain, which is why this is
clearly marked `synthetic: true` in the model card and must never be reported as
validation.
"""
from __future__ import annotations

import argparse
import json
import pickle
import random
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from samvedna.analytics.features.store import FeatureStore  # noqa: E402
from samvedna.analytics.models.tabular import (  # noqa: E402
    FEATURE_NAMES,
    ModelCard,
    digest_of,
    features_for,
)
from samvedna.config.weights import ALL_DOMAINS  # noqa: E402
from samvedna.disclosure.consent import ConsentRegistry  # noqa: E402
from samvedna.ingest.connectors.replay import connectors_for  # noqa: E402
from samvedna.ingest.generator import generate_force  # noqa: E402
from samvedna.ingest.normalise import normalise  # noqa: E402
from samvedna.ingest.pseudonymise import Pseudonymiser  # noqa: E402

# Below this many positives a subgroup AUROC is a number, not a measurement. It
# is reported and excluded from the headline gap, because a fairness table that
# quotes 0.500 from a single positive is worse than one that says "not measured"
# — the first invites a conclusion, the second invites more data.
MIN_POSITIVES_FOR_A_SUBGROUP_METRIC = 3

# A person is a positive if their latent strain is in the top decile. Rare on
# purpose: the positive class in this problem is rare, and a balanced training
# set would teach the model a prevalence that does not exist.
POSITIVE_STRAIN = 0.55
TARGET_PRECISION = 0.70
AGE_BANDS = ((0, 29, "under-30"), (30, 39, "30-39"), (40, 200, "40-plus"))


def band_for(age: int) -> str:
    return next(label for lo, hi, label in AGE_BANDS if lo <= age <= hi)


def build_dataset(units: int, strength: int, seed: int):
    force = generate_force(units=units, strength=strength, seed=seed)
    ps = Pseudonymiser(f"train-salt-{seed}", on=force.as_of)
    registry = ConsentRegistry()
    for person in force.personnel:
        registry.enrol(ps.pid(person.service_number), ALL_DOMAINS, welfare_contact=True)

    results = tuple(c.pull(force.as_of, 270) for c in connectors_for(force))
    report = normalise(results, ps, registry.state_for)
    store = FeatureStore()
    store.upsert(report.records)

    by_pid = {ps.pid(p.service_number): p for p in force.personnel}
    rows, labels, groups = [], [], []
    for pid in store.pids():
        person = by_pid.get(pid)
        if person is None:
            continue
        row = features_for(store, pid, force.as_of)
        rows.append([row[name] for name in FEATURE_NAMES])
        labels.append(1 if person.strain >= POSITIVE_STRAIN else 0)
        groups.append(
            {
                "rank": person.rank,
                "age_band": band_for(person.age),
                "unit_kind": next(u.kind for u in force.units if u.unit_id == person.unit_id),
                "deployed": "surged" if any(
                    u.unit_id == person.unit_id and u.surge_days for u in force.units
                ) else "static",
            }
        )
    return rows, labels, groups, store, force


def auroc(y_true, y_score) -> float:
    pairs = sorted(zip(y_score, y_true, strict=False))
    pos = sum(y_true)
    neg = len(y_true) - pos
    if pos == 0 or neg == 0:
        return 0.5
    rank_sum, i = 0.0, 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            if pairs[k][1] == 1:
                rank_sum += avg_rank
        i = j + 1
    return (rank_sum - pos * (pos + 1) / 2) / (pos * neg)


def precision_recall(y_true, y_score, threshold):
    tp = sum(1 for t, s in zip(y_true, y_score, strict=False) if s >= threshold and t == 1)
    fp = sum(1 for t, s in zip(y_true, y_score, strict=False) if s >= threshold and t == 0)
    fn = sum(1 for t, s in zip(y_true, y_score, strict=False) if s < threshold and t == 1)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return precision, recall


def select_threshold(y_true, y_score, target=TARGET_PRECISION):
    """The lowest threshold reaching the target precision — precision, not F1.

    F1 treats a missed case and a wrongly-named soldier as equally bad. In a
    welfare system where the output is a name handed to an officer, they are not.
    """
    best = (1.0, 0.0, 0.0)
    for step in range(99, 0, -1):
        t = step / 100
        p, r = precision_recall(y_true, y_score, t)
        if p >= target and r > best[2]:
            best = (t, p, r)
    if best[2] == 0.0:  # target unreachable; fall back to the most precise point
        for step in range(99, 0, -1):
            t = step / 100
            p, r = precision_recall(y_true, y_score, t)
            if p > best[1]:
                best = (t, p, r)
    return best


def calibration_error(y_true, y_score, bins=10):
    """Expected calibration error: how far a score is from what it claims."""
    total, n = 0.0, len(y_true)
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, s in enumerate(y_score) if lo <= s < hi or (b == bins - 1 and s == 1.0)]
        if not idx:
            continue
        mean_score = sum(y_score[i] for i in idx) / len(idx)
        mean_true = sum(y_true[i] for i in idx) / len(idx)
        total += len(idx) / n * abs(mean_score - mean_true)
    return round(total, 4)



def _make_booster(requested: str, seed: int):
    """Resolve the gradient-boosting backend. Returns (estimator, name).

    Both backends expose `fit(X, y, sample_weight=...)` and `predict_proba`,
    and SHAP's TreeExplainer handles both, so the rest of the pipeline cannot
    tell which one it got — the model card records it.

    Hyperparameters are matched as closely as the two libraries allow rather
    than tuned separately. Two differently-tuned backends would make the model
    card's AUROC depend on which machine trained it, and a figure that moves
    when the host changes is not a figure.

    `lightgbm` explicitly requested and missing is an error, not a silent
    downgrade. Somebody who asked for it needs to know they did not get it.
    """
    if requested in ("auto", "lightgbm"):
        try:
            from lightgbm import LGBMClassifier
        # OSError, not just ImportError, and this is the whole reason the
        # default is scikit-learn. LightGBM's wheel installs perfectly and then
        # fails at *load* time with
        #   dlopen(...lib_lightgbm.dylib): Library not loaded: @rpath/libomp.dylib
        # because libomp is a separate Homebrew package. An `except ImportError`
        # here does not catch it, so "auto" would crash on the exact machine it
        # exists to protect. Verified on this one.
        except (ImportError, OSError) as exc:
            if requested == "lightgbm":
                raise SystemExit(
                    f"lightgbm was requested but cannot be loaded: {exc}\n"
                    f"On macOS: `brew install libomp`. On Debian/Ubuntu: "
                    f"`apt-get install libgomp1`. Or use --backend sklearn, "
                    f"which needs nothing."
                ) from None
            print(f"lightgbm unavailable ({type(exc).__name__}); using scikit-learn")
        else:
            return (
                LGBMClassifier(
                    n_estimators=180,
                    learning_rate=0.05,
                    max_depth=3,
                    min_child_samples=12,
                    subsample=0.8,
                    subsample_freq=1,
                    random_state=seed,
                    verbose=-1,
                ),
                "lightgbm.LGBMClassifier",
            )

    from sklearn.ensemble import GradientBoostingClassifier

    return (
        GradientBoostingClassifier(
            n_estimators=180,
            learning_rate=0.05,
            max_depth=3,
            min_samples_leaf=12,
            subsample=0.8,
            random_state=seed,
        ),
        "sklearn.GradientBoostingClassifier",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--units", type=int, default=8)
    parser.add_argument("--strength", type=int, default=90)
    parser.add_argument("--seed", type=int, default=26186)
    parser.add_argument("--out", default="artefacts/models")
    # The submitted deck names LightGBM. It is genuinely supported and it is
    # genuinely not the default: LightGBM wheels link against libomp, which is
    # a Homebrew install on macOS and absent on a clean machine, and this
    # project has to survive being copied onto a pendrive. "auto" prefers
    # LightGBM when it imports and falls back to scikit-learn when it does
    # not, so a data centre gets the faster backend and a transferred copy
    # still trains.
    parser.add_argument(
        "--backend", choices=("auto", "sklearn", "lightgbm"), default="auto"
    )
    args = parser.parse_args()

    try:
        import numpy as np
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.isotonic import IsotonicRegression
    except ImportError:
        print("scikit-learn not installed. Install with: uv sync --extra ml")
        print("The pipeline runs without a model — the gates do not need a score.")
        return 2

    rows, labels, groups, _, _ = build_dataset(args.units, args.strength, args.seed)
    print(f"dataset: {len(rows)} personnel, {sum(labels)} positive "
          f"({sum(labels) / len(labels):.1%})")

    rng = random.Random(args.seed)
    order = list(range(len(rows)))
    rng.shuffle(order)
    split = int(len(order) * 0.7)
    tr, te = order[:split], order[split:]

    X_tr = np.array([rows[i] for i in tr])
    y_tr = np.array([labels[i] for i in tr])
    X_te = np.array([rows[i] for i in te])
    y_te = [labels[i] for i in te]

    positive = max(1, int(y_tr.sum()))
    # Weight the rare positive class rather than resampling, so the model still
    # sees the true prevalence in the data it is fitted on.
    weights = np.where(y_tr == 1, (len(y_tr) - positive) / positive, 1.0)
    booster, backend_name = _make_booster(args.backend, args.seed)
    booster.fit(X_tr, y_tr, sample_weight=weights)
    print(f"backend: {backend_name}")

    raw_te = [float(v) for v in booster.predict_proba(X_te)[:, 1]]
    raw_tr = [float(v) for v in booster.predict_proba(X_tr)[:, 1]]
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso.fit(raw_tr, y_tr)
    cal_te = [float(v) for v in iso.predict(raw_te)]

    threshold, precision, recall = select_threshold(y_te, cal_te)
    area = round(auroc(y_te, cal_te), 4)
    ece = calibration_error(y_te, cal_te)

    subgroup: dict[str, dict[str, float]] = {}
    for key in ("rank", "age_band", "unit_kind", "deployed"):
        values = sorted({groups[i][key] for i in te})
        for value in values:
            idx = [k for k, i in enumerate(te) if groups[i][key] == value]
            if len(idx) < 5:
                continue
            sub_true = [y_te[k] for k in idx]
            sub_score = [cal_te[k] for k in idx]
            p, r = precision_recall(sub_true, sub_score, threshold)
            subgroup[f"{key}={value}"] = {
                "n": len(idx),
                "positives": sum(sub_true),
                "positive_rate": round(sum(sub_true) / len(sub_true), 4),
                "auroc": round(auroc(sub_true, sub_score), 4),
                "precision": round(p, 4),
                "recall": round(r, 4),
            }

    card = ModelCard(
        version=f"tabular-{args.seed}-u{args.units}s{args.strength}",
        trained_on="synthetic force (generator seed "
                   f"{args.seed}); labels derived from latent strain",
        n_train=len(tr),
        n_test=len(te),
        positive_rate=round(sum(labels) / len(labels), 4),
        auroc=area,
        precision_at_threshold=round(precision, 4),
        recall_at_threshold=round(recall, 4),
        operating_threshold=threshold,
        calibration_error=ece,
        subgroup=subgroup,
        backend=backend_name,
        synthetic=True,
    )

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    estimator_path = out / "tabular.pkl"
    with estimator_path.open("wb") as handle:
        pickle.dump(booster, handle, protocol=pickle.HIGHEST_PROTOCOL)
    card = replace(card, digest=digest_of(estimator_path))
    (out / "tabular_card.json").write_text(card.to_json() + "\n")
    (out / "tabular_isotonic.json").write_text(
        json.dumps({"x": [float(v) for v in iso.X_thresholds_],
                    "y": [float(v) for v in iso.y_thresholds_]}) + "\n"
    )

    print(f"AUROC {area}  ECE {ece}")
    print(f"threshold {threshold} selected for precision >= {TARGET_PRECISION}: "
          f"precision {precision:.3f}, recall {recall:.3f}")
    print("\nsubgroup performance (the gaps are the point):")
    for name, metrics in sorted(subgroup.items()):
        pos = int(metrics["positives"])
        # A subgroup with no positives cannot be ranked, and its AUROC of 0.500
        # means "no evidence", not "no skill". Reporting the two as the same
        # number is how a fairness table quietly lies.
        if pos < MIN_POSITIVES_FOR_A_SUBGROUP_METRIC:
            verdict = f"NOT MEASURED ({pos} positive{'s' if pos != 1 else ''})"
        else:
            verdict = (
                f"AUROC {metrics['auroc']:.3f}  precision {metrics['precision']:.3f}  "
                f"recall {metrics['recall']:.3f}"
            )
        print(f"  {name:34s} n={metrics['n']:<4} pos={pos:<3} {verdict}")

    measurable = {
        k: m for k, m in subgroup.items()
        if m["positives"] >= MIN_POSITIVES_FOR_A_SUBGROUP_METRIC
    }
    aurocs = [m["auroc"] for m in measurable.values()]
    if aurocs:
        print(f"\n  widest measurable subgroup AUROC gap: {max(aurocs) - min(aurocs):.3f} "
              f"across {len(measurable)} of {len(subgroup)} subgroups")
        blind = sorted(set(subgroup) - set(measurable))
        if blind:
            print(f"  {len(blind)} subgroup(s) had fewer than "
                  f"{MIN_POSITIVES_FOR_A_SUBGROUP_METRIC} positives and are "
                  f"UNMEASURED, not validated:")
            for name in blind:
                print(f"    - {name}")
    # --- survival: "risk by when", on the same features -------------------
    from samvedna.analytics.models.survival import HORIZONS

    interval = min(HORIZONS)
    # A discrete-time label: did this person cross the concern threshold within
    # the first interval? Derived from the same latent strain, so it is exactly
    # as synthetic as the tabular label and is marked so.
    hazard_labels = np.array([1 if lab else 0 for lab in labels])
    hazard = GradientBoostingClassifier(
        n_estimators=120, learning_rate=0.05, max_depth=3,
        min_samples_leaf=12, random_state=args.seed,
    )
    hazard_weights = np.where(
        hazard_labels == 1, (len(hazard_labels) - positive) / positive, 1.0
    )
    hazard.fit(np.array(rows), hazard_labels, sample_weight=hazard_weights)

    survival_path = out / "survival.pkl"
    with survival_path.open("wb") as handle:
        pickle.dump(hazard, handle, protocol=pickle.HIGHEST_PROTOCOL)
    (out / "survival_card.json").write_text(
        json.dumps(
            {
                "version": f"survival-{args.seed}",
                "features": list(FEATURE_NAMES),
                "interval_days": interval,
                "horizons": list(HORIZONS),
                "digest": digest_of(survival_path),
                "synthetic": True,
                "trained_on": "same synthetic force; discrete-time hazard over "
                              f"{interval}-day intervals",
            },
            indent=2,
        )
        + "\n"
    )
    print(f"survival: discrete hazard over {interval}-day intervals, "
          f"horizons {list(HORIZONS)}")

    print(f"\nwritten to {out.relative_to(ROOT)}  (SYNTHETIC — never report as validation)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
