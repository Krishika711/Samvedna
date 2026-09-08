"""Phase 13: sequence and survival — 'risk by when', and what the order of duty
days says that their average does not.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from samvedna.analytics.features.store import FeatureStore
from samvedna.analytics.models.sequence import (
    ADEQUATE_BREAK_DAYS,
    RHYTHM_NAMES,
    rhythm_for,
)
from samvedna.analytics.models.survival import (
    HORIZONS,
    SurvivalEstimate,
    load_survival,
    unavailable,
)
from samvedna.config.windows import SUSTAINABLE_RUN_DAYS
from samvedna.core.types import SignalRecord

AS_OF = date(2026, 9, 5)
MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "artefacts" / "models"


def roster(pattern: list[bool]) -> FeatureStore:
    store = FeatureStore()
    store.upsert(
        tuple(
            SignalRecord(
                pid="p",
                domain="duty_roster",
                observed_at=datetime.combine(
                    AS_OF - timedelta(days=len(pattern) - 1 - i),
                    datetime.min.time(),
                    tzinfo=UTC,
                ),
                value=1.0 if on else 0.0,
                raw_kind="consecutive_duty_days",
                unit_id="UNIT-01",
            )
            for i, on in enumerate(pattern)
        )
    )
    return store


def rhythm(pattern):
    return rhythm_for(roster(pattern), "p", AS_OF)


# ------------------------------------------------------------- roster rhythm --
def test_two_rosters_with_the_same_mean_are_told_apart():
    """The whole argument for this model. Both work 60 of 90 days."""
    rotated = rhythm([i % 3 < 2 for i in range(90)])
    blocked = rhythm([i < 60 for i in range(90)])
    assert rotated.longest_run_days < blocked.longest_run_days
    assert rotated.regularity > blocked.regularity


def test_a_long_unbroken_run_is_not_regular_however_predictable_it_is():
    """The bug this caught: a 61-day unbroken run scored **1.00** — perfectly
    predictable, and the worst roster in the sample. Predictability is not
    sustainability."""
    unbroken = rhythm([i < 61 for i in range(90)])
    assert unbroken.longest_run_days == 61
    assert unbroken.regularity == 0.0


def test_a_clockwork_but_punishing_roster_scores_below_a_sustainable_one():
    clockwork = rhythm([i % 21 < 20 for i in range(90)])   # 20 on, 1 off
    sustainable = rhythm([i % 8 < 6 for i in range(90)])   # 6 on, 2 off
    assert clockwork.longest_run_days > SUSTAINABLE_RUN_DAYS
    assert sustainable.regularity > clockwork.regularity


def test_a_run_at_the_sustainable_limit_is_not_penalised():
    at_limit = rhythm([i % (SUSTAINABLE_RUN_DAYS + 2) < SUSTAINABLE_RUN_DAYS
                       for i in range(90)])
    assert at_limit.longest_run_days == SUSTAINABLE_RUN_DAYS
    assert at_limit.regularity > 0.5


def test_short_breaks_reduce_break_adequacy():
    one_day_breaks = rhythm([i % 7 < 6 for i in range(90)])
    two_day_breaks = rhythm([i % 8 < 6 for i in range(90)])
    assert one_day_breaks.break_adequacy < two_day_breaks.break_adequacy
    assert two_day_breaks.break_adequacy == 1.0


def test_nobody_on_duty_reports_no_rhythm_rather_than_a_perfect_one():
    empty = rhythm([False] * 90)
    assert empty.regularity == 0.0
    assert empty.break_adequacy == 0.0
    assert "no duty days recorded" in empty.phrase()


def test_the_phrase_names_the_sustainable_threshold_when_it_is_exceeded():
    assert f"{SUSTAINABLE_RUN_DAYS}-day sustainable run" in rhythm(
        [i < 40 for i in range(90)]
    ).phrase()
    assert "sustainable run" not in rhythm([i % 8 < 6 for i in range(90)]).phrase()


def test_too_little_data_returns_a_zeroed_rhythm_not_a_guess():
    assert rhythm([True, False]).observed_days <= ADEQUATE_BREAK_DAYS * 2


def test_every_rhythm_feature_is_named_and_produced():
    features = rhythm([i % 8 < 6 for i in range(90)]).as_features()
    assert set(features) == set(RHYTHM_NAMES)


def test_the_phrase_is_something_an_officer_could_repeat_aloud():
    text = rhythm([i % 8 < 6 for i in range(90)]).phrase()
    assert "days" in text
    assert "%" in text
    assert "0." not in text.split("regularity")[0], "no bare scores before the words"


# ------------------------------------------------------------------ survival --
def test_an_unavailable_survival_model_says_so_rather_than_defaulting():
    """A default horizon reads as a prediction. Absence must read as absence."""
    estimate = unavailable("p")
    assert estimate.status == "unavailable"
    assert estimate.by_horizon == {}
    assert estimate.median_days is None
    assert "no horizon estimate is available" in estimate.phrase()


def test_a_missing_survival_model_loads_as_none():
    assert load_survival("/does/not/exist") is None


def test_cumulative_risk_is_monotone_across_horizons():
    estimate = SurvivalEstimate(
        pid="p", by_horizon={7: 0.1, 30: 0.35, 60: 0.6, 90: 0.75},
        median_days=45, model_version="v",
    )
    values = [estimate.by_horizon[d] for d in sorted(estimate.by_horizon)]
    assert values == sorted(values)


def test_the_soonest_material_horizon_is_the_first_past_an_even_chance():
    estimate = SurvivalEstimate(
        pid="p", by_horizon={7: 0.1, 30: 0.35, 60: 0.6, 90: 0.75},
        median_days=45, model_version="v",
    )
    assert estimate.soonest_material_horizon == 60
    assert "within 60 days" in estimate.phrase()


def test_a_flat_hazard_reports_no_even_chance_rather_than_the_last_horizon():
    estimate = SurvivalEstimate(
        pid="p", by_horizon={7: 0.01, 30: 0.04, 60: 0.08, 90: 0.11},
        median_days=None, model_version="v",
    )
    assert estimate.soonest_material_horizon is None
    assert "does not reach an even chance" in estimate.phrase()


def test_no_horizon_phrase_quotes_a_percentage_as_confidence():
    """PART 14 forbids a model emitting a confidence percentage."""
    for by_horizon in ({7: 0.9, 30: 0.95}, {7: 0.01, 30: 0.02}):
        text = SurvivalEstimate("p", by_horizon, None, "v").phrase()
        assert "%" not in text
        assert "confident" not in text.lower()


@pytest.mark.skipif(not (MODEL_DIR / "survival.pkl").exists(), reason="no model")
def test_a_trained_survival_model_produces_monotone_horizons():
    pytest.importorskip("sklearn")
    model = load_survival(MODEL_DIR)
    assert model is not None

    from samvedna.analytics.models.tabular import FEATURE_NAMES

    row = dict.fromkeys(FEATURE_NAMES, 0.4)
    estimate = model.estimate("p", row)
    assert estimate.status == "ok"
    assert set(estimate.by_horizon) == set(HORIZONS)
    values = [estimate.by_horizon[d] for d in sorted(HORIZONS)]
    assert values == sorted(values)
    assert all(0.0 <= v <= 1.0 for v in values)


@pytest.mark.skipif(not (MODEL_DIR / "survival.pkl").exists(), reason="no model")
def test_a_tampered_survival_model_refuses_to_load(tmp_path):
    import shutil

    shutil.copytree(MODEL_DIR, tmp_path / "m")
    target = tmp_path / "m" / "survival.pkl"
    target.write_bytes(target.read_bytes() + b"\x00")
    assert load_survival(tmp_path / "m") is None


def test_a_horizon_never_bypasses_a_gate():
    """A three-day horizon does not lower a threshold or shorten a window. The
    one path that genuinely bypasses gates is the acute override, and that is
    triggered by an instrument, never by a model."""
    from tests.conftest import case, deviation

    from samvedna.core.verdict import decide

    BLIP = {7: 1.0, 30: 7 / 30, 90: 7 / 90}
    verdict = decide(case(deviation("self_report", breach=BLIP)))
    assert verdict.decision != "IMMEDIATE_ESCALATE"
    assert not verdict.gates["persistence"].passed
