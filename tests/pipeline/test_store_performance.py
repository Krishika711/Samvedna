"""The store's reads must stay cheap, and its caches must stay correct.

Four separate quadratic paths were found in this store by benchmarking, all of
them the same mistake: a lookup that scanned a whole collection to answer a
question a dict could answer. Per-person cost of the deviation stage grew from
22 ms to 41 ms as the cohort went from 240 people to 960, which extrapolated to
a national run that would not finish overnight.

The fixes were a day-ordered mirror inside `Series`, two reverse indexes, and a
memoised cohort baseline. That last one is a cache in the decision path, which
is worth being nervous about — a stale cohort baseline silently changes `z_unit`
for every member of the unit, and the number would still look plausible. So the
invalidation is tested here directly rather than trusted.

These tests assert behaviour, not timings. A wall-clock assertion in a test
suite fails on a loaded CI box and teaches everyone to ignore it.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from samvedna.analytics.features.store import FeatureStore, _pstdev
from samvedna.core.types import SignalRecord

AS_OF = date(2026, 9, 5)


def record(pid, domain, offset, value, unit_id="UNIT-01"):
    return SignalRecord(
        pid=pid,
        domain=domain,
        observed_at=datetime.combine(
            AS_OF - timedelta(days=offset), datetime.min.time(), tzinfo=UTC
        ),
        value=value,
        raw_kind="test",
        unit_id=unit_id,
    )


def test_cohort_baseline_is_recomputed_after_an_upsert():
    """The cache must not survive a write that changes its answer.

    Read first, then add a person far from the existing mean, then read again.
    A stale cache returns the old mean and every `z_unit` in the unit is quietly
    wrong.
    """
    store = FeatureStore()
    store.upsert(tuple(
        record(f"p{i}", "workload", d, 0.10) for i in range(3) for d in range(20)
    ))

    before = store.unit_baseline("UNIT-01", "workload", AS_OF, 30)
    assert before.mean == pytest.approx(0.10)

    store.upsert(tuple(record("p9", "workload", d, 0.40) for d in range(20)))
    after = store.unit_baseline("UNIT-01", "workload", AS_OF, 30)

    assert after.n == 4
    assert after.mean == pytest.approx(0.175), (
        "cohort baseline served a stale mean after a write"
    )


def test_cohort_baseline_is_recomputed_after_age_out():
    """Ageing rows out changes the answer too, so it must invalidate as well."""
    store = FeatureStore()
    # One person recent, one person entirely outside the retention window.
    store.upsert(tuple(record("recent", "workload", d, 0.10) for d in range(5)))
    store.upsert(tuple(record("old", "workload", 300 + d, 0.40) for d in range(5)))

    seeded = store.unit_baseline("UNIT-01", "workload", AS_OF, 400)
    assert seeded.n == 2

    removed = store.age_out(AS_OF, retain_days=30)
    assert removed > 0
    after = store.unit_baseline("UNIT-01", "workload", AS_OF, 400)

    assert after.n == 1, "cohort baseline still counted a person whose rows aged out"


def test_cohort_baseline_cache_distinguishes_windows_and_lags():
    """The cache key has five parts. Dropping any of them collides silently."""
    store = FeatureStore()
    # Recent days low, older days high, so window and lag must give different
    # answers or the key is wrong.
    store.upsert(tuple(record("p1", "workload", d, 0.10) for d in range(0, 20)))
    store.upsert(tuple(record("p1", "workload", d, 0.90) for d in range(100, 140)))

    short = store.unit_baseline("UNIT-01", "workload", AS_OF, 20)
    lagged = store.unit_baseline("UNIT-01", "workload", AS_OF, 60, lag=100)

    assert short.mean == pytest.approx(0.10)
    assert lagged.mean == pytest.approx(0.90), "window and lag are not both in the cache key"


def test_series_window_survives_out_of_order_arrival():
    """The day-ordered mirror is rebuilt on write, including a backdated one.

    Records do not arrive in date order — a connector re-sending a late row is
    normal. If the mirror is not invalidated, the backdated value is invisible
    to every window that should contain it.
    """
    store = FeatureStore()
    store.upsert((record("p1", "workload", 1, 0.50),))
    assert store.series("p1", "workload").window(AS_OF, 30) == [0.50]

    # A row for an earlier day, arriving after the later one.
    store.upsert((record("p1", "workload", 10, 0.10),))
    assert store.series("p1", "workload").window(AS_OF, 30) == [0.10, 0.50], (
        "a backdated row did not appear in date order"
    )


def test_unit_of_and_domains_for_agree_with_a_full_scan():
    """The reverse indexes must answer exactly what scanning would have."""
    store = FeatureStore()
    store.upsert((
        record("p1", "workload", 1, 0.10, unit_id="UNIT-01"),
        record("p1", "leave", 1, 0.20, unit_id="UNIT-01"),
        record("p2", "deployment", 1, 0.50, unit_id="UNIT-02"),
    ))

    assert store.unit_of("p1") == "UNIT-01"
    assert store.unit_of("p2") == "UNIT-02"
    assert store.unit_of("nobody") is None
    assert store.domains_for("p1") == ("leave", "workload")
    assert store.domains_for("p2") == ("deployment",)
    assert store.domains_for("nobody") == ()


def test_pstdev_matches_the_exact_implementation():
    """The float standard deviation must agree with `statistics.pstdev`.

    It replaced it for speed — the exact version computes a sum of squares in
    `Fraction` arithmetic, which was 36 of 63 seconds of the deviation stage.
    Speed is not a reason to return a different number, so the agreement is
    pinned here, including for the large-mean small-spread case that the
    sum-of-squares shortcut would have got wrong.
    """
    import statistics

    for values in (
        [1.0, 2.0, 3.0, 4.0],
        [200.1, 200.2, 200.15, 199.9],       # large mean, tiny spread
        [0.0, 0.0, 0.0],
        [1e6, 1e6 + 1, 1e6 + 2],
    ):
        mean = statistics.fmean(values)
        assert _pstdev(values, mean) == statistics.pstdev(values), values

    assert _pstdev([5.0], 5.0) == 0.0, "a single observation has no spread"
    assert _pstdev([], 0.0) == 0.0
