"""Phase 5 ship gate: calibrated, subgroup metrics reported — and structurally
incapable of deciding anything.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from tests.conftest import case, deviation

from samvedna.analytics.features.store import FeatureStore
from samvedna.analytics.models.tabular import (
    FEATURE_NAMES,
    SURVIVAL_HORIZON_DAYS,
    ModelCard,
    features_for,
    load_model,
    unavailable,
)
from samvedna.core.types import RiskAssessment
from samvedna.core.verdict import decide

ROOT = Path(__file__).resolve().parent.parent.parent
MODEL_DIR = ROOT / "artefacts" / "models"
AS_OF = date(2026, 9, 5)
SUSTAINED = {7: 1.0, 30: 1.0, 90: 0.9}
BLIP = {7: 1.0, 30: 7 / 30, 90: 7 / 90}


# ------------------------------------------------ the claim the design rests on --
def test_the_strongest_possible_score_changes_no_gate_and_no_verdict():
    """A model output of 1.000 must move nothing. This is the whole thesis:
    the model raises the concern, the arithmetic makes the decision."""
    plain = case(deviation("leave", breach=BLIP), deviation("transfer", breach=BLIP))
    terrifying = RiskAssessment(
        pid="pid-test", score=1.0, horizon_days=60,
        drivers=(("leave_mean_30d", 9.9),), model_version="v-max",
    )
    loud = case(
        deviation("leave", breach=BLIP),
        deviation("transfer", breach=BLIP),
        risk=terrifying,
    )
    a, b = decide(plain), decide(loud)
    assert a.decision == b.decision
    for name in a.gates:
        assert a.gates[name].value == b.gates[name].value, f"{name} moved on a score"


def test_a_risk_assessment_has_nowhere_to_put_a_verdict_or_a_confidence():
    fields = set(RiskAssessment.__dataclass_fields__)
    for forbidden in ("verdict", "decision", "confidence", "escalate", "flag"):
        assert forbidden not in fields


def test_a_zero_score_does_not_suppress_an_otherwise_sound_case():
    """The converse, which matters just as much: a quiet model cannot veto."""
    silent = RiskAssessment(
        pid="pid-test", score=0.0, horizon_days=60, drivers=(), model_version="v0",
    )
    v = decide(
        case(
            deviation("self_report", breach=SUSTAINED),
            deviation("leave", breach=SUSTAINED),
            deviation("duty_roster", breach=SUSTAINED),
            risk=silent,
        )
    )
    assert v.decision == "ESCALATE"


# ------------------------------------------------------------- degradation --
def test_a_missing_model_directory_returns_none_rather_than_raising():
    assert load_model(ROOT / "does" / "not" / "exist") is None


def test_the_pipeline_reaches_a_verdict_with_no_model_at_all():
    v = decide(
        case(
            deviation("self_report", breach=SUSTAINED),
            deviation("leave", breach=SUSTAINED),
            deviation("duty_roster", breach=SUSTAINED),
            risk=unavailable("pid-test"),
        )
    )
    assert v.decision == "ESCALATE"
    assert v.recommended


def test_an_unavailable_assessment_is_labelled_not_faked():
    assessment = unavailable("pid-x")
    assert assessment.status == "unavailable"
    assert assessment.score == 0.0
    assert assessment.drivers == ()


def test_a_tampered_estimator_refuses_to_load(tmp_path):
    """Loading an estimator means unpickling it. An unverified pickle in a
    nightly batch is a remote-code-execution primitive."""
    pytest.importorskip("sklearn")
    if not (MODEL_DIR / "tabular.pkl").exists():
        pytest.skip("no trained model; run tools/train_tabular.py")

    import shutil

    shutil.copytree(MODEL_DIR, tmp_path / "models")
    target = tmp_path / "models" / "tabular.pkl"
    target.write_bytes(target.read_bytes() + b"\x00tampered")
    assert load_model(tmp_path / "models") is None


# ------------------------------------------------------------------ features --
def test_the_feature_vocabulary_carries_the_domain_in_the_name():
    """So a SHAP driver matches the intervention playbook without a mapping."""
    from samvedna.core.interventions import PLAYBOOK

    tokens = {token for item in PLAYBOOK for token in item.addresses}
    matched = [name for name in FEATURE_NAMES if any(t in name for t in tokens)]
    assert len(matched) > len(FEATURE_NAMES) // 2


def test_features_include_a_slope_not_just_levels():
    """Two jawans with the same 30-day mean are different people if one is
    climbing and one is settling."""
    assert any(name.endswith("_slope") for name in FEATURE_NAMES)

    store = FeatureStore()
    from tests.pipeline.test_features import flat_then_spike

    store.upsert(flat_then_spike("rising", "workload"))
    store.upsert(flat_then_spike("steady", "workload", spike=0.2, spike_days=0))
    rising = features_for(store, "rising", AS_OF)
    steady = features_for(store, "steady", AS_OF)
    assert rising["workload_slope"] > steady["workload_slope"]


def test_every_feature_name_is_produced_for_every_pid():
    store = FeatureStore()
    from tests.pipeline.test_features import flat_then_spike

    store.upsert(flat_then_spike("p1", "leave"))
    row = features_for(store, "p1", AS_OF)
    assert set(row) == set(FEATURE_NAMES)


# --------------------------------------------------------------- model card --
@pytest.mark.skipif(
    not (MODEL_DIR / "tabular_card.json").exists(), reason="no trained model"
)
def test_the_model_card_is_published_and_marked_synthetic():
    card = ModelCard(**json.loads((MODEL_DIR / "tabular_card.json").read_text()))
    assert card.synthetic is True, "PART 9: synthetic training must never be validation"
    assert "synthetic" in card.trained_on.lower()


@pytest.mark.skipif(
    not (MODEL_DIR / "tabular_card.json").exists(), reason="no trained model"
)
def test_the_operating_threshold_was_selected_for_precision_not_f1():
    card = ModelCard(**json.loads((MODEL_DIR / "tabular_card.json").read_text()))
    assert card.precision_at_threshold >= 0.70
    assert card.precision_at_threshold >= card.recall_at_threshold, (
        "an F1-selected threshold would balance these; this one must favour precision"
    )


@pytest.mark.skipif(
    not (MODEL_DIR / "tabular_card.json").exists(), reason="no trained model"
)
def test_the_model_is_calibrated():
    card = ModelCard(**json.loads((MODEL_DIR / "tabular_card.json").read_text()))
    assert card.calibration_error < 0.10, "an uncalibrated score is not a probability"


@pytest.mark.skipif(
    not (MODEL_DIR / "tabular_card.json").exists(), reason="no trained model"
)
def test_subgroup_performance_is_reported_across_every_required_axis():
    """PART 9 names them: rank, age band, unit type and deployment category."""
    card = ModelCard(**json.loads((MODEL_DIR / "tabular_card.json").read_text()))
    axes = {name.split("=")[0] for name in card.subgroup}
    assert axes == {"rank", "age_band", "unit_kind", "deployed"}


@pytest.mark.skipif(
    not (MODEL_DIR / "tabular_card.json").exists(), reason="no trained model"
)
def test_a_subgroup_with_too_few_positives_is_reported_not_scored_away():
    """A fairness table that quotes AUROC 0.500 from a single positive invites a
    conclusion. One that says 'not measured' invites more data."""
    card = ModelCard(**json.loads((MODEL_DIR / "tabular_card.json").read_text()))
    assert all("positives" in metrics for metrics in card.subgroup.values())


@pytest.mark.skipif(not (MODEL_DIR / "tabular.pkl").exists(), reason="no trained model")
def test_a_trained_model_scores_and_attributes():
    pytest.importorskip("sklearn")
    model = load_model(MODEL_DIR)
    assert model is not None

    store = FeatureStore()
    from tests.pipeline.test_features import flat_then_spike

    store.upsert(flat_then_spike("p1", "workload"))
    assessment = model.score("p1", features_for(store, "p1", AS_OF))
    assert assessment.status == "ok"
    assert 0.0 <= assessment.score <= 1.0
    assert assessment.horizon_days == SURVIVAL_HORIZON_DAYS
    assert assessment.drivers, "a case with no drivers is a case an officer cannot act on"
    assert all(name in FEATURE_NAMES for name, _ in assessment.drivers)
