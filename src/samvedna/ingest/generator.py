"""Synthetic personnel cohorts — realistic service-record sequences, no real data.

Everything this module produces is clearly marked synthetic and must never be
reported as validation (PART 9). It exists so that the whole pipeline can be
exercised, demonstrated and load-tested offline, with no live service-record
access anywhere in the path.

What makes the output usable rather than noise is that the sequences have the
*shape* of real unit records: duty runs in blocks because rosters are planned in
blocks, leave is applied for and sometimes denied, deployments are contiguous
tours rather than scattered days, and the whole unit moves together when it is
deployed — which is exactly the pattern the op-tempo confounder exists to catch.

Deterministic under a seed. Same seed, same force, always.
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from samvedna.config.weights import CONNECTOR_DOMAINS, DomainName
from samvedna.config.windows import BASELINE_WINDOW_DAYS
from samvedna.core.types import SignalRecord

__all__ = ["Personnel", "Unit", "Force", "generate_force", "RAW_KIND"]

# The service-record fact behind each normalised domain value. Kept explicit so
# that a driver shown to an officer can be traced back to a row somebody could
# go and look up in the unit's records.
RAW_KIND: dict[DomainName, str] = {
    "leave": "leave_denied_rate",
    "deployment": "days_deployed_away_from_station",
    "duty_roster": "consecutive_duty_days",
    "transfer": "postings_in_trailing_year",
    "training": "course_days_assigned",
    "workload": "duty_hours_over_establishment",
    "self_report": "instrument_score_normalised",
    "biometric": "resting_heart_rate_trend",
    # No entry for "voice": there is no records system to pull a voice from,
    # and the generator must not invent one.
}

RANKS = ("Constable", "Head Constable", "ASI", "SI", "Inspector", "Assistant Commandant")
# How far an operational surge lifts a domain for somebody fully exposed to it.
SURGE_LIFT = 0.34
UNIT_KINDS = ("battalion", "training centre", "border post", "static guard")


@dataclass(frozen=True, slots=True)
class Personnel:
    """A synthetic person. `service_number` never leaves L1 — see pseudonymise.py."""

    service_number: str
    unit_id: str
    rank: str
    age: int
    years_of_service: int
    # Latent, unobservable, and the thing the whole system is trying to notice
    # indirectly. Never exported into a feature or a fixture.
    strain: float
    # How much of the unit's operational surge this person actually carries.
    # A surge is not uniform: a quick-reaction sub-unit is on the line while the
    # quartermaster's staff are not. A uniform lift made 92% of the unit deviate,
    # which is not a surge — it is a broken generator, and it would have made the
    # op-tempo confounder look far more decisive than it is.
    surge_exposure: float = 1.0


@dataclass(frozen=True, slots=True)
class Unit:
    unit_id: str
    kind: str
    strength: int
    # Days on which the whole unit is under operational surge. This is what makes
    # the op-tempo confounder fire, and it is a property of the unit, not of any
    # person in it.
    surge_days: frozenset[date]


@dataclass(frozen=True, slots=True)
class Force:
    units: tuple[Unit, ...]
    personnel: tuple[Personnel, ...]
    records: tuple[SignalRecord, ...]
    as_of: date
    seed: int

    def by_unit(self, unit_id: str) -> tuple[Personnel, ...]:
        return tuple(p for p in self.personnel if p.unit_id == unit_id)


def _stable_number(rng: random.Random, unit_id: str, index: int) -> str:
    digest = hashlib.sha256(f"{unit_id}:{index}:{rng.random()}".encode()).hexdigest()
    return f"{unit_id}-{int(digest[:8], 16) % 900000 + 100000}"


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _blocked_series(
    rng: random.Random, days: int, base: float, block_len: int, elevation: float
) -> list[float]:
    """A series that moves in blocks, because rosters are planned in blocks.

    Independent daily noise produces a series no unit has ever generated, and a
    persistence gate scored against it would look far better than it deserves —
    the 7/30/90-day windows would each see the same white noise and agree. Blocks
    are what make persistence a real test.
    """
    out: list[float] = []
    while len(out) < days:
        run = max(1, int(rng.gauss(block_len, block_len / 3)))
        level = base + (elevation if rng.random() < 0.5 else 0.0)
        level += rng.gauss(0, 0.05)
        out.extend([_clamp01(level)] * run)
    return out[:days]


def _tour_series(rng: random.Random, days: int, tours: int, length: int) -> list[float]:
    """Deployments are contiguous tours, not scattered days."""
    out = [0.0] * days
    for _ in range(tours):
        start = rng.randrange(0, max(1, days - length))
        for d in range(start, min(days, start + length)):
            out[d] = 1.0
    return out


def _domain_series(
    rng: random.Random,
    domain: DomainName,
    person: Personnel,
    unit: Unit,
    days: int,
    start: date,
) -> list[float]:
    strain = person.strain
    if domain == "deployment":
        tours = 1 + int(strain * 2)
        series = _tour_series(rng, days, tours, length=28 + int(strain * 30))
    elif domain == "transfer":
        # A step function: postings are discrete events, so the trailing-year
        # count is flat between them.
        count = rng.random() < (0.15 + strain * 0.35)
        series = [0.25 + 0.5 * count] * days
    elif domain == "training":
        series = _tour_series(rng, days, tours=rng.randint(0, 2), length=14)
    elif domain == "self_report":
        # Sparse: a self-assessment is an event, not a stream. Between
        # submissions the value is carried forward, which is what a real
        # instrument score does.
        series = [0.0] * days
        current = 0.0
        for d in range(days):
            if rng.random() < 0.02:
                current = _clamp01(rng.gauss(0.25 + strain * 0.5, 0.12))
            series[d] = current
    elif domain == "biometric":
        series = [
            _clamp01(rng.gauss(0.3 + strain * 0.25, 0.12)
                     + 0.05 * math.sin(d / 7.0))
            for d in range(days)
        ]
    else:
        # leave / duty_roster / workload: blocked, and pushed up by strain.
        series = _blocked_series(
            rng, days, base=0.22 + strain * 0.30, block_len=9, elevation=0.18
        )

    # Unit surge lifts the operational domains for the personnel who carry it,
    # on the same days. This is the signal the op-tempo confounder must see — and
    # it must see a majority of the cohort move, not all of it.
    if domain in ("duty_roster", "workload", "deployment", "leave"):
        lift = SURGE_LIFT * person.surge_exposure
        for d in range(days):
            if start + timedelta(days=d) in unit.surge_days:
                series[d] = _clamp01(series[d] + lift)
    return series


def generate_force(
    *,
    units: int = 3,
    strength: int = 60,
    days: int = BASELINE_WINDOW_DAYS + 90,
    as_of: date | None = None,
    seed: int = 26186,
    surge_unit_index: int | None = 0,
) -> Force:
    """A synthetic force with `units` units of roughly `strength` personnel each.

    `surge_unit_index` puts one unit under an operational surge for a contiguous
    block, so that a generated cohort reproduces the op-tempo case without any
    fixture having to assert it.
    """
    rng = random.Random(seed)
    as_of = as_of or date(2026, 9, 5)
    start = as_of - timedelta(days=days - 1)

    unit_list: list[Unit] = []
    for i in range(units):
        surge: frozenset[date] = frozenset()
        if surge_unit_index is not None and i == surge_unit_index:
            surge_start = rng.randrange(days - 70, days - 40)
            surge = frozenset(
                start + timedelta(days=d) for d in range(surge_start, days)
            )
        unit_list.append(
            Unit(
                unit_id=f"UNIT-{i + 1:02d}",
                kind=UNIT_KINDS[i % len(UNIT_KINDS)],
                strength=strength,
                surge_days=surge,
            )
        )

    people: list[Personnel] = []
    for unit in unit_list:
        for index in range(unit.strength):
            years = rng.randint(1, 28)
            people.append(
                Personnel(
                    service_number=_stable_number(rng, unit.unit_id, index),
                    unit_id=unit.unit_id,
                    rank=RANKS[min(len(RANKS) - 1, years // 5)],
                    age=20 + years + rng.randint(0, 4),
                    years_of_service=years,
                    # Most people are fine. A long right tail, because that is
                    # what the prevalence literature describes and what makes
                    # the positive class rare enough to be a real problem.
                    strain=_clamp01(rng.betavariate(2.0, 6.0)),
                    # Roughly two thirds of a unit carries a surge meaningfully;
                    # the rest are on tasks the surge does not touch.
                    surge_exposure=_clamp01(rng.betavariate(2.6, 1.4)),
                )
            )

    units_by_id = {u.unit_id: u for u in unit_list}
    records: list[SignalRecord] = []
    for person in people:
        unit = units_by_id[person.unit_id]
        # Consent is a per-person fact decided here so that ingest has something
        # real to filter on. Roughly a third decline the self-assessment channel.
        scope: set[DomainName] = set(CONNECTOR_DOMAINS)
        if rng.random() < 0.34:
            scope.discard("self_report")
        if rng.random() < 0.55:
            scope.discard("biometric")
        frozen_scope = frozenset(scope)

        for domain in CONNECTOR_DOMAINS:
            if domain not in frozen_scope:
                continue
            series = _domain_series(rng, domain, person, unit, days, start)
            for d, value in enumerate(series):
                if domain in ("self_report", "transfer") and value == 0.0:
                    continue
                records.append(
                    SignalRecord(
                        pid=person.service_number,  # pseudonymised at ingest, not here
                        domain=domain,
                        observed_at=datetime.combine(
                            start + timedelta(days=d), datetime.min.time(), tzinfo=UTC
                        ),
                        value=round(value, 4),
                        raw_kind=RAW_KIND[domain],
                        unit_id=person.unit_id,
                        consent_scope=frozen_scope,
                    )
                )

    return Force(
        units=tuple(unit_list),
        personnel=tuple(people),
        records=tuple(records),
        as_of=as_of,
        seed=seed,
    )
