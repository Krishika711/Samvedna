"""Phase 4 ship gate: deviations match hand-computed fixtures.

The store and the deviation detector are the last place arithmetic can go wrong
before the gates, and unlike the gates they are not pure — they read windows off
a clock-shaped `as_of`. So the tests build tiny series by hand and check the
numbers against values worked out on paper.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from samvedna.analytics.features.deviation import (
    candidate_pids,
    deviations_for,
    unit_deviating_fractions,
)
from samvedna.analytics.features.store import MIN_STDEV, FeatureStore
from samvedna.config.windows import BASELINE_LAG_DAYS, BASELINE_WINDOW_DAYS
from samvedna.core.types import SignalRecord

AS_OF = date(2026, 9, 5)


def records(pid, domain, values_by_offset, unit_id="UNIT-01"):
    from datetime import UTC, datetime

    return tuple(
        SignalRecord(
            pid=pid,
            domain=domain,
            observed_at=datetime.combine(
                AS_OF - timedelta(days=offset), datetime.min.time(), tzinfo=UTC
            ),
            value=value,
            raw_kind="test",
            unit_id=unit_id,
        )
        for offset, value in values_by_offset.items()
    )


def flat_then_spike(pid, domain, *, base=0.2, spike=0.9, spike_days=7, unit_id="UNIT-01"):
    """A person who was steady for their whole baseline and then jumped."""
    values = {}
    for offset in range(BASELINE_LAG_DAYS, BASELINE_LAG_DAYS + BASELINE_WINDOW_DAYS):
        values[offset] = base + (0.02 if offset % 2 else -0.02)
    for offset in range(0, BASELINE_LAG_DAYS):
        values[offset] = spike if offset < spike_days else base
    return records(pid, domain, values, unit_id)


# ------------------------------------------------------------------ store --
def test_the_baseline_window_excludes_the_period_being_scored():
    """The bug this caught: without the lag, a sustained surge sits inside the
    trailing mean it is supposed to deviate from. Measured on the synthetic
    force, an obvious unit-wide surge produced z_self = 0.83 against a 2.0
    threshold — invisible."""
    store = FeatureStore()
    store.upsert(flat_then_spike("p1", "workload", spike_days=60))
    baseline = store.personal_baseline("p1", "workload", AS_OF)
    # The spike is 0.9; the baseline must not have moved toward it.
    assert baseline.mean == pytest.approx(0.2, abs=0.01)


def test_two_rows_on_the_same_day_collapse_to_their_mean():
    """Ingest order must not be able to change a feature."""
    store = FeatureStore()
    store.upsert(records("p1", "leave", {5: 0.2}))
    store.upsert(records("p1", "leave", {5: 0.8}))
    assert store.series("p1", "leave").points[AS_OF - timedelta(days=5)] == 0.5


def test_a_never_moving_series_cannot_produce_an_infinite_z():
    store = FeatureStore()
    values = dict.fromkeys(
        range(BASELINE_LAG_DAYS, BASELINE_LAG_DAYS + BASELINE_WINDOW_DAYS), 0.30
    )
    values.update(dict.fromkeys(range(0, 7), 0.95))
    store.upsert(records("p1", "leave", values))
    baseline = store.personal_baseline("p1", "leave", AS_OF)
    assert baseline.stdev >= MIN_STDEV


def test_breach_fraction_is_over_elapsed_days_not_over_rows_present():
    """Three observations in ninety days must not report a breach fraction of
    1.0 — persistence would read as sustained when almost nothing was recorded."""
    store = FeatureStore()
    store.upsert(records("p1", "leave", {1: 0.9, 2: 0.9, 3: 0.9}))
    series = store.series("p1", "leave")
    assert series.breach_fraction(AS_OF, 90, level=0.5) == pytest.approx(3 / 90)


def test_the_unit_baseline_is_built_from_per_person_means_not_pooled_rows():
    """A hundred people with one high day each is a different thing from one
    person with a hundred high days, and pooling cannot tell them apart."""
    store = FeatureStore()
    for i in range(10):
        store.upsert(records(f"p{i}", "workload", dict.fromkeys(range(30), 0.2)))
    store.upsert(records("loud", "workload", dict.fromkeys(range(30), 1.0)))
    stats = store.unit_baseline("UNIT-01", "workload", AS_OF, 30)
    assert stats.n == 11, "n counts personnel, not rows"
    assert stats.mean == pytest.approx((10 * 0.2 + 1.0) / 11, abs=1e-6)


def test_rows_age_out_of_the_store():
    store = FeatureStore()
    store.upsert(records("p1", "leave", dict.fromkeys(range(0, 400), 0.4)))
    before = len(store.series("p1", "leave").points)
    removed = store.age_out(AS_OF, retain_days=200)
    assert removed > 0
    assert len(store.series("p1", "leave").points) == before - removed


# -------------------------------------------------------------- deviation --
def test_a_clear_spike_deviates_and_the_numbers_are_hand_checkable():
    store = FeatureStore()
    store.upsert(flat_then_spike("p1", "workload"))
    for i in range(2, 12):  # a calm cohort around them
        store.upsert(flat_then_spike(f"p{i}", "workload", spike=0.2, spike_days=0))

    devs = deviations_for(store, "p1", AS_OF)
    assert [d.domain for d in devs] == ["workload"]
    d = devs[0]
    # baseline mean 0.200, stdev 0.020 (the alternating +/- 0.02); recent 7-day
    # mean is the 0.9 spike, so z = (0.9 - 0.2) / 0.02, far past the cap.
    assert d.z_self > 20
    assert d.direction == "elevated"
    assert d.daily_breach[7] == pytest.approx(1.0)


def test_a_reduced_deviation_is_detected_and_labelled():
    store = FeatureStore()
    store.upsert(flat_then_spike("p1", "leave", base=0.8, spike=0.05))
    devs = deviations_for(store, "p1", AS_OF)
    assert devs and devs[0].direction == "reduced"
    assert devs[0].z_self < 0


def test_too_little_personal_history_produces_no_deviation():
    """'Different from your peers' is not the same claim as 'different from
    yourself', and only the second one is about welfare."""
    store = FeatureStore()
    store.upsert(records("p1", "leave", {0: 0.95, 1: 0.95}))
    assert deviations_for(store, "p1", AS_OF) == ()


def test_a_steady_person_does_not_deviate():
    store = FeatureStore()
    store.upsert(flat_then_spike("p1", "workload", spike=0.2, spike_days=0))
    assert deviations_for(store, "p1", AS_OF) == ()


def test_tier_and_weight_come_from_config_never_from_the_data():
    from samvedna.config.weights import tier_of, weight_of

    store = FeatureStore()
    for domain in ("self_report", "leave", "transfer"):
        store.upsert(flat_then_spike("p1", domain))
    for dev in deviations_for(store, "p1", AS_OF):
        assert dev.tier == tier_of(dev.domain)
        assert dev.weight == weight_of(dev.domain)


def test_missingness_comes_from_the_connector_not_from_observation_density():
    """Two reasons, and the second is the one that matters.

    The first attempt inferred missingness from how many days had rows, and
    compared a 90-day window against 270 expected days — a units error that fired
    the 0.80 data-gap confounder on every domain of every person and produced a
    nightly run with **zero escalations**.

    The second reason would have survived fixing the units: several domains are
    sparse by nature. A self-assessment is an event, not a stream, and a transfer
    is a step function. Density would mark both 95% missing forever, and "this
    person rarely fills in the form" would silently become "the records are
    unreliable".
    """
    store = FeatureStore()
    store.upsert(flat_then_spike("p1", "self_report"))

    sparse_but_complete = deviations_for(store, "p1", AS_OF)[0]
    assert sparse_but_complete.missing_fraction == 0.0

    connector_failed = deviations_for(
        store, "p1", AS_OF, connector_missing={"self_report": 0.4}
    )[0]
    assert connector_failed.missing_fraction == pytest.approx(0.4)


def test_candidate_pids_are_exactly_those_with_a_deviating_domain():
    store = FeatureStore()
    store.upsert(flat_then_spike("loud", "workload"))
    store.upsert(flat_then_spike("quiet", "workload", spike=0.2, spike_days=0))
    assert candidate_pids(store, AS_OF) == ("loud",)


def test_unit_deviating_fraction_counts_people_not_domains():
    store = FeatureStore()
    for i in range(10):
        store.upsert(flat_then_spike(f"p{i}", "workload", spike=0.9 if i < 5 else 0.2,
                                     spike_days=7 if i < 5 else 0))
    by_pid = {pid: deviations_for(store, pid, AS_OF) for pid in store.pids()}
    fractions = unit_deviating_fractions(store, "UNIT-01", AS_OF, by_pid)
    assert fractions["workload"] == pytest.approx(0.5)


def test_opposite_directions_do_not_add_up_into_a_false_op_tempo():
    """Half the unit up and half down is not a surge, and must not read as one."""
    store = FeatureStore()
    for i in range(10):
        store.upsert(
            flat_then_spike(f"p{i}", "workload",
                            base=0.2 if i < 5 else 0.8,
                            spike=0.9 if i < 5 else 0.05)
        )
    by_pid = {pid: deviations_for(store, pid, AS_OF) for pid in store.pids()}
    fractions = unit_deviating_fractions(store, "UNIT-01", AS_OF, by_pid)
    assert fractions["workload"] == pytest.approx(0.5), "5 up and 5 down, not 10"
