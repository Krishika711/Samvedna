"""The feature store: personal and unit baselines over 7/30/90/180-day windows.

Two baselines, and the difference between them is the whole reason this system
can tell an individual welfare concern from a command workload problem.

* **`z_self`** — how far this person has moved from *their own* 180-day
  baseline. A jawan who has always worked long hours has not changed; a jawan
  whose hours doubled last month has.
* **`z_unit`** — how far they have moved relative to the *unit cohort over the
  same window*. If the whole unit moved, the individual z stays modest even
  though the raw number is alarming.

Measuring only against a fixed threshold would flag every person in a hard
posting and nobody in an easy one, which is the opposite of welfare.

Rolling windows, ageing out on schedule. No identifier reaches here — the only
key is a pid.
"""
from __future__ import annotations

import statistics
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from samvedna.config.weights import DomainName
from samvedna.config.windows import (
    BASELINE_LAG_DAYS,
    BASELINE_WINDOW_DAYS,
    WINDOWS_DAYS,
)
from samvedna.core.types import SignalRecord

__all__ = ["Series", "FeatureStore", "WindowStats"]

# Below this many observations a baseline is not a baseline, and a z-score
# computed from it is a confident number with nothing behind it.
MIN_BASELINE_OBSERVATIONS = 10
# Floor on the standard deviation, so a person whose value has never moved does
# not produce an infinite z the first time it does.
MIN_STDEV = 0.02


@dataclass(frozen=True, slots=True)
class WindowStats:
    days: int
    n: int
    mean: float
    stdev: float
    latest: float

    @property
    def usable(self) -> bool:
        return self.n >= MIN_BASELINE_OBSERVATIONS


def _pstdev(values: list[float], mean: float) -> float:
    """Population standard deviation, in floats.

    `statistics.pstdev` is exact — it computes the sum of squares in `Fraction`
    arithmetic so that the answer does not depend on floating-point ordering.
    That exactness is the right default for a statistics library and the wrong
    one here: profiling the deviation stage showed 36 of 63 seconds inside
    `fractions.py` and `math.gcd`, for a number that then gets floored at
    `MIN_STDEV = 0.02` and compared against a threshold of 2.0.

    Two-pass rather than the sum-of-squares shortcut. `E[x^2] - E[x]^2` is one
    multiplication cheaper and catastrophically cancels when the mean is large
    relative to the spread — which is exactly this data, where a duty-hours
    series sits near 200 and moves by 5.
    """
    n = len(values)
    if n < 2:
        return 0.0
    total = 0.0
    for v in values:
        delta = v - mean
        total += delta * delta
    return (total / n) ** 0.5


@dataclass(slots=True)
class Series:
    """One pid's observations in one domain, ordered by day.

    Observations arrive unordered and are read back by window, many times: the
    deviation stage asks for 7-, 30-, 90- and 180-day windows per domain per
    person, and the unit baselines ask again for every member of the cohort. So
    the day-ordered form is built once, lazily, and reused until something is
    added — and windows are then sliced with a binary search instead of a scan.

    The first version of this sorted the whole dict inside `window()`. It was
    correct, and it was the single reason the pipeline looked super-linear:
    1.5 million calls, each re-sorting up to 270 days of history, turned an
    O(n) stage into an O(n^2) one.
    """

    pid: str
    domain: DomainName
    unit_id: str
    points: dict[date, float] = field(default_factory=dict)
    # Day-ordered mirror of `points`. `None` means "rebuild on next read".
    _days: list[date] | None = field(default=None, repr=False, compare=False)
    _values: list[float] | None = field(default=None, repr=False, compare=False)

    def add(self, day: date, value: float) -> None:
        # Several rows on the same day collapse to their mean rather than the
        # last one seen, so ingest order cannot change a feature.
        if day in self.points:
            self.points[day] = (self.points[day] + value) / 2
        else:
            self.points[day] = value
        self._days = None
        self._values = None

    def _ordered(self) -> tuple[list[date], list[float]]:
        if self._days is None or self._values is None:
            items = sorted(self.points.items())
            self._days = [day for day, _ in items]
            self._values = [value for _, value in items]
        return self._days, self._values

    def window(self, as_of: date, days: int, lag: int = 0) -> list[float]:
        latest = as_of - timedelta(days=lag)
        earliest = latest - timedelta(days=days - 1)
        ordered_days, ordered_values = self._ordered()
        lo = bisect_left(ordered_days, earliest)
        hi = bisect_right(ordered_days, latest)
        return ordered_values[lo:hi]

    def stats(self, as_of: date, days: int, lag: int = 0) -> WindowStats:
        values = self.window(as_of, days, lag)
        if not values:
            return WindowStats(days, 0, 0.0, MIN_STDEV, 0.0)
        mean = statistics.fmean(values)
        stdev = _pstdev(values, mean)
        return WindowStats(days, len(values), mean, max(stdev, MIN_STDEV), values[-1])

    def drop_before(self, earliest: date) -> int:
        """Age rows out. Owned by `Series` so the ordered mirror stays honest.

        `FeatureStore.age_out` used to delete straight out of `points`, which
        left `_days` and `_values` describing rows that no longer existed —
        every window kept returning aged-out values, including in the cohort
        baseline. Any mutation of `points` has to go through a method that
        invalidates the mirror, so there is only one such method and this is it.
        """
        stale = [day for day in self.points if day < earliest]
        for day in stale:
            del self.points[day]
        if stale:
            self._days = None
            self._values = None
        return len(stale)

    def observed_days(self, as_of: date, days: int) -> int:
        earliest = as_of - timedelta(days=days - 1)
        ordered_days, _ = self._ordered()
        lo = bisect_left(ordered_days, earliest)
        hi = bisect_right(ordered_days, as_of)
        return hi - lo

    def breach_fraction(self, as_of: date, days: int, level: float) -> float:
        """Fraction of *elapsed* days in the window on which the value breached.

        Denominator is the window length, not the number of rows present. Using
        the row count would let a domain with three observations in ninety days
        report a breach fraction of 1.0, and persistence would read as sustained
        when the truth is that almost nothing was recorded.
        """
        values = self.window(as_of, days)
        if not values:
            return 0.0
        return sum(1 for v in values if v >= level) / days


class FeatureStore:
    """Rolling per-pid, per-domain series plus unit cohort aggregates.

    In-memory here; the persistent implementation is the same shape backed by a
    time-series table. Rows age out beyond the retention window automatically,
    which is Workflow J's "rolling window; ages out automatically" as code.
    """

    def __init__(self) -> None:
        self._series: dict[tuple[str, str], Series] = {}
        self._pids_by_unit: dict[str, set[str]] = defaultdict(set)
        # Reverse indexes, maintained on write. Both questions they answer used
        # to be answered by scanning every (pid, domain) key in the store, once
        # per person — which is quadratic in cohort size for a lookup that is
        # a dict access.
        self._unit_by_pid: dict[str, str] = {}
        self._domains_by_pid: dict[str, set[str]] = defaultdict(set)
        # Memoised cohort baselines. See `unit_baseline` for why this is safe.
        self._unit_baselines: dict[tuple[str, str, date, int, int], WindowStats] = {}

    def upsert(self, records: tuple[SignalRecord, ...]) -> int:
        for record in records:
            key = (record.pid, record.domain)
            series = self._series.get(key)
            if series is None:
                series = Series(record.pid, record.domain, record.unit_id)
                self._series[key] = series
            series.add(record.observed_at.date(), record.value)
            self._pids_by_unit[record.unit_id].add(record.pid)
            self._unit_by_pid[record.pid] = record.unit_id
            self._domains_by_pid[record.pid].add(record.domain)
        self._unit_baselines.clear()
        return len(records)

    def age_out(self, as_of: date, retain_days: int) -> int:
        earliest = as_of - timedelta(days=retain_days)
        removed = sum(
            series.drop_before(earliest) for series in self._series.values()
        )
        if removed:
            self._unit_baselines.clear()
        return removed

    # ------------------------------------------------------------- reads --
    def pids(self) -> tuple[str, ...]:
        return tuple(sorted({pid for pid, _ in self._series}))

    def pids_in_unit(self, unit_id: str) -> tuple[str, ...]:
        return tuple(sorted(self._pids_by_unit.get(unit_id, ())))

    def unit_of(self, pid: str) -> str | None:
        return self._unit_by_pid.get(pid)

    def domains_for(self, pid: str) -> tuple[DomainName, ...]:
        return tuple(sorted(self._domains_by_pid.get(pid, ())))

    def series(self, pid: str, domain: DomainName) -> Series | None:
        return self._series.get((pid, domain))

    def personal_baseline(self, pid: str, domain: DomainName, as_of: date) -> WindowStats:
        series = self._series.get((pid, domain))
        if series is None:
            return WindowStats(BASELINE_WINDOW_DAYS, 0, 0.0, MIN_STDEV, 0.0)
        return series.stats(as_of, BASELINE_WINDOW_DAYS, lag=BASELINE_LAG_DAYS)

    def unit_baseline(
        self, unit_id: str, domain: DomainName, as_of: date, days: int, lag: int = 0
    ) -> WindowStats:
        """The cohort's distribution in this domain and window.

        Computed from every person's window mean, not from the pooled rows: a
        cohort of a hundred people each with one high day is a different thing
        from one person with a hundred high days, and pooling cannot tell them
        apart.

        Memoised per (unit, domain, as_of, window, lag). The cohort baseline is
        the same number for every member of the unit, and the deviation stage
        asks for it once per person per domain — so without the cache the stage
        recomputes an identical figure `cohort_size` times, which is the
        difference between a linear pipeline and a quadratic one. The cache is
        cleared by `upsert` and by `age_out`, which are the only two things that
        can change the answer, and nothing writes to the store during a scoring
        pass.
        """
        cache_key = (unit_id, domain, as_of, days, lag)
        cached = self._unit_baselines.get(cache_key)
        if cached is not None:
            return cached

        means = []
        for pid in self._pids_by_unit.get(unit_id, ()):
            series = self._series.get((pid, domain))
            if series is None:
                continue
            stats = series.stats(as_of, days, lag)
            if stats.n:
                means.append(stats.mean)
        if not means:
            result = WindowStats(days, 0, 0.0, MIN_STDEV, 0.0)
        else:
            mean = statistics.fmean(means)
            result = WindowStats(
                days, len(means), mean, max(_pstdev(means, mean), MIN_STDEV), means[-1]
            )
        self._unit_baselines[cache_key] = result
        return result

    def window_means(self, pid: str, domain: DomainName, as_of: date) -> dict[int, float]:
        series = self._series.get((pid, domain))
        if series is None:
            return dict.fromkeys(WINDOWS_DAYS, 0.0)
        return {d: series.stats(as_of, d).mean for d in WINDOWS_DAYS}
