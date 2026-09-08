"""Deviation detection: feature store -> DomainDeviation[], with tiering fixed.

The screening step. It answers "has anything about this person changed?" and
nothing else — not how serious, not what to do, not whether to tell anybody.
Those are four gates and a verdict away, which is why this step is allowed to be
generous: `DEVIATION_Z_SELF = 2.0` rather than 3.0, because a screening step that
misses is unrecoverable and a screening step that over-selects is merely work.

**Tier is read from config, never computed.** A deviation carries the tier and
weight of its *data source*, and nothing in this module can promote one. That is
PART 6.1, and it is the difference between a weight a governance board approved
and a weight the pipeline chose.
"""
from __future__ import annotations

from datetime import date

from samvedna.analytics.features.store import FeatureStore
from samvedna.config.thresholds import (
    DAILY_BREACH_Z,
    DEVIATION_Z_SELF,
    DEVIATION_Z_UNIT,
)
from samvedna.config.weights import DomainName, tier_of, weight_of
from samvedna.config.windows import PERSISTENCE_WINDOWS_DAYS, WINDOWS_DAYS
from samvedna.core.types import DomainDeviation

__all__ = ["deviations_for", "candidate_pids", "unit_deviating_fractions"]


def _z(value: float, mean: float, stdev: float) -> float:
    return (value - mean) / stdev if stdev else 0.0


def _deviation_for_domain(
    store: FeatureStore,
    pid: str,
    domain: DomainName,
    unit_id: str,
    as_of: date,
    connector_missing: dict[DomainName, float] | None = None,
) -> DomainDeviation | None:
    series = store.series(pid, domain)
    if series is None:
        return None

    baseline = store.personal_baseline(pid, domain, as_of)
    if not baseline.usable:
        # Not enough of the person's own history to say they have changed. This
        # returns nothing rather than falling back to a unit comparison, because
        # "different from your peers" is not the same claim as "different from
        # yourself" and only the second one is about welfare.
        return None

    recent = series.stats(as_of, min(WINDOWS_DAYS))
    if not recent.n:
        return None

    z_self = _z(recent.mean, baseline.mean, baseline.stdev)
    unit_stats = store.unit_baseline(unit_id, domain, as_of, min(WINDOWS_DAYS))
    z_unit = _z(recent.mean, unit_stats.mean, unit_stats.stdev)

    if abs(z_self) < DEVIATION_Z_SELF and abs(z_unit) < DEVIATION_Z_UNIT:
        return None

    direction = "elevated" if z_self >= 0 else "reduced"
    level = baseline.mean + DAILY_BREACH_Z * baseline.stdev
    daily = {
        days: series.breach_fraction(as_of, days, level)
        for days in PERSISTENCE_WINDOWS_DAYS
    }
    windows_breached = sum(
        1
        for days in PERSISTENCE_WINDOWS_DAYS
        if abs(_z(series.stats(as_of, days).mean, baseline.mean, baseline.stdev))
        >= DEVIATION_Z_SELF
    )

    # Missingness comes from the CONNECTOR, which knows how many rows it
    # expected and how many it returned. It is deliberately not inferred from
    # observation density in the window, for two reasons. The first attempt did
    # exactly that and compared days observed in a 90-day window against 270
    # expected days — a units error that fired the 0.80 data-gap confounder on
    # every domain of every person and produced a run with zero escalations.
    # The second reason is the one that would have survived fixing the units:
    # several domains are sparse by nature. A self-assessment is an event, not a
    # stream, and a transfer is a step function. Density would mark both as
    # 95% missing forever, and "this person rarely fills in the form" would
    # silently become "the records are unreliable".
    missing = max(0.0, min(1.0, (connector_missing or {}).get(domain, 0.0)))

    return DomainDeviation(
        domain=domain,
        z_self=round(z_self, 4),
        z_unit=round(z_unit, 4),
        direction=direction,
        windows_breached=windows_breached,
        # From config. Not computed, not model-assigned, not fixture-supplied.
        tier=tier_of(domain),
        weight=weight_of(domain),
        daily_breach=daily,
        missing_fraction=round(missing, 4),
    )


def deviations_for(
    store: FeatureStore,
    pid: str,
    as_of: date,
    *,
    connector_missing: dict[DomainName, float] | None = None,
) -> tuple[DomainDeviation, ...]:
    """Every domain in which this person has moved from their own baseline.

    `connector_missing` is the fraction of rows each connector failed to return
    this run, and it is the only source of truth for missingness — see the note
    in `_deviation_for_domain`.
    """
    unit_id = store.unit_of(pid) or ""
    out = [
        _deviation_for_domain(store, pid, domain, unit_id, as_of, connector_missing)
        for domain in store.domains_for(pid)
    ]
    return tuple(d for d in out if d is not None)


def candidate_pids(store: FeatureStore, as_of: date) -> tuple[str, ...]:
    """Every pid with at least one deviating domain. The rest are CLEARED."""
    return tuple(pid for pid in store.pids() if deviations_for(store, pid, as_of))


def unit_deviating_fractions(
    store: FeatureStore,
    unit_id: str,
    as_of: date,
    deviations_by_pid: dict[str, tuple[DomainDeviation, ...]],
) -> dict[DomainName, float]:
    """Fraction of the unit cohort deviating in each domain, same direction.

    This is the input the op-tempo confounder reads. It is computed here, over
    the whole unit, rather than inside the confounder rule — the rule must stay a
    pure function of facts it is handed, or L3 stops being testable in
    milliseconds.
    """
    cohort = store.pids_in_unit(unit_id)
    if not cohort:
        return {}
    counts: dict[DomainName, dict[str, int]] = {}
    for pid in cohort:
        for dev in deviations_by_pid.get(pid, ()):
            counts.setdefault(dev.domain, {"elevated": 0, "reduced": 0})
            counts[dev.domain][dev.direction] += 1
    return {
        domain: max(by_direction.values()) / len(cohort)
        for domain, by_direction in counts.items()
    }
