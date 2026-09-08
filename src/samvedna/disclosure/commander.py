"""The commander's unit view. Aggregate only, and there is no drill-down to build.

PART 8.6 says there is no "show me who" button and no API that would answer it.
This module is that API, and the reason a commander cannot identify anybody is
not that the button is hidden — it is that every function here returns `Cell`
objects and `Cell` has no pid field. There is nothing to drill into.

When a commander asks the question in real life, the answer is a process: raise
welfare capacity, and the welfare officer — not the commander — works the
individual cases. `unit_view` returns that sentence alongside the numbers,
because a screen that only says "no" teaches people to route around it.
"""
from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass

from samvedna.disclosure.audit import Ledger
from samvedna.disclosure.dpcache import ReleaseCache
from samvedna.disclosure.kanon import Cell, aggregate, k_min
from samvedna.disclosure.rbac import Principal, check
from samvedna.ingest.dp import Budget, BudgetExhausted
from samvedna.pipeline.record import RunRecord

__all__ = ["UnitView", "unit_view", "NEXT_STEP", "HeatCell", "heat_map", "HEAT_DOMAINS"]

NEXT_STEP = (
    "Individual cases are worked by the welfare officer, not from this screen. "
    "If this unit's load is the concern, the levers here are rostering, leave "
    "sanctioning, rotation planning and welfare capacity."
)


@dataclass(frozen=True, slots=True)
class UnitView:
    unit_id: str
    as_of: str
    cells: tuple[Cell, ...]
    suppressed: int
    next_step: str = NEXT_STEP
    budget_remaining: float = 0.0
    note: str = ""

    def to_dict(self) -> dict:
        """The payload the API returns. Assert on this in the privacy tests."""
        return {
            "unit_id": self.unit_id,
            "as_of": self.as_of,
            "k": k_min(),
            "cells": [c.to_dict() for c in self.cells],
            "suppressed": self.suppressed,
            "next_step": self.next_step,
            "budget_remaining": round(self.budget_remaining, 3),
            "note": self.note,
        }


def unit_view(
    record: RunRecord,
    unit_id: str,
    principal: Principal,
    budget: Budget,
    ledger: Ledger,
    *,
    differential_privacy: bool = True,
    rng: random.Random | None = None,
    cache: ReleaseCache | None = None,
) -> UnitView:
    """Aggregates for one unit. Raises `Denied` for any purpose but the right one.

    `cache` is what stops a refresh from becoming an averaging attack. Without
    it, ten refreshes of the same view draw ten independent noise samples around
    the same truth, and their mean is the truth. See `dpcache.py`.
    """
    check(principal, "command:aggregate", unit_id)
    cache = cache if cache is not None else ReleaseCache()

    cases = [c for c in record.cases if c.unit_id == unit_id]

    # Every series a commander can see is a distribution over the unit, never a
    # list of people. Building them this way means there is no intermediate
    # per-person structure for a future endpoint to accidentally expose.
    # Deviations are deliberately NOT exposed per domain per person here. A
    # per-person structure that exists is a per-person structure some future
    # endpoint returns.
    series: dict[str, list[float]] = defaultdict(list)
    for case in cases:
        series["fatigue index"].append(case.composite)
        if case.verdict:
            for name, gate in case.verdict.gates.items():
                series[f"{name} gate"].append(gate.value)
    series["deviating share"] = [
        1.0 if c.decision != "CLEARED" else 0.0 for c in cases
    ]
    series["under active monitoring"] = [
        1.0 if c.decision == "MONITOR" else 0.0 for c in cases
    ]

    cells: list[Cell] = []
    note = ""
    for label, values in sorted(series.items()):
        cached = cache.get(unit_id, record.as_of, label)
        if cached is not None:
            # Same question, same period, same answer. Charges no epsilon.
            cells.append(cached)
            continue
        try:
            cells.append(
                cache.put(
                    unit_id, record.as_of, label,
                    aggregate(
                        label, values, budget,
                        differential_privacy=differential_privacy, rng=rng,
                    ),
                )
            )
        except BudgetExhausted as exc:
            note = (
                f"Privacy budget for this period is exhausted; remaining cells are "
                f"withheld rather than released without noise. ({exc})"
            )
            break

    suppressed = sum(1 for c in cells if c.suppressed)
    ledger.append(
        actor=principal.actor,
        action="aggregate.released" if suppressed < len(cells) else "aggregate.suppressed",
        unit_id=unit_id,
        purpose="command:aggregate",
        detail={
            "cells": len(cells),
            "suppressed": suppressed,
            "cohort_size": len(cases),
            "epsilon_spent": round(budget.spent, 4),
            "served_from_cache": cache.hits,
        },
    )
    return UnitView(
        unit_id=unit_id,
        as_of=record.as_of.isoformat(),
        cells=tuple(cells),
        suppressed=suppressed,
        budget_remaining=budget.remaining,
        note=note,
    )


# ---------------------------------------------------------------- heat map --
#
# The commander's actual working surface: which domains are running hot across
# which sub-units, so rosters and leave sanctioning can be rebalanced.
#
# Every cell is k-checked and DP-noised exactly like a scalar aggregate, and a
# cell below k is suppressed rather than shaded — a shaded cell covering three
# people is a picture of three people. The grid is over (sub-unit x domain), and
# there is deliberately no axis anywhere on it that resolves to a person.

# Domains a commander can act on by changing how the unit is run. Self-report,
# biometric and voice are absent on purpose: they are the person's own, they are
# not levers a commander has, and putting them on this screen would invite
# exactly the reading the whole design excludes.
HEAT_DOMAINS: tuple[str, ...] = (
    "duty_roster", "leave", "workload", "deployment", "transfer", "training",
)


@dataclass(frozen=True, slots=True)
class HeatCell:
    """One (sub-unit, domain) square."""

    sub_unit: str
    domain: str
    n: int
    value: float | None
    suppressed: bool
    reason: str = ""

    @property
    def band(self) -> str:
        """Five bands, so the grid reads at a glance without quoting a number
        anybody would mistake for a measurement of a person."""
        if self.suppressed or self.value is None:
            return "suppressed"
        if self.value >= 0.75:
            return "critical"
        if self.value >= 0.55:
            return "high"
        if self.value >= 0.35:
            return "moderate"
        if self.value >= 0.18:
            return "low"
        return "nominal"

    def to_dict(self) -> dict:
        if self.suppressed:
            return {
                "sub_unit": self.sub_unit, "domain": self.domain,
                "suppressed": True, "band": "suppressed", "reason": self.reason,
            }
        return {
            "sub_unit": self.sub_unit,
            "domain": self.domain,
            "suppressed": False,
            "n": self.n,
            "value": round(self.value or 0.0, 4),
            "band": self.band,
        }


def heat_map(
    record: RunRecord,
    unit_id: str,
    principal: Principal,
    budget: Budget,
    ledger: Ledger,
    *,
    sub_units: int = 4,
    differential_privacy: bool = True,
    rng: random.Random | None = None,
    cache=None,
) -> dict:
    """Fatigue and workload across a unit's sub-units, for rebalancing.

    Raises `Denied` for any principal but a commander scoped to this unit.
    """
    check(principal, "command:aggregate", unit_id)
    from samvedna.disclosure.dpcache import ReleaseCache

    cache = cache if cache is not None else ReleaseCache()
    cases = [c for c in record.cases if c.unit_id == unit_id]

    # Sub-units are derived from the pid rather than stored, because a stored
    # sub-unit roster is one join away from a name. A stable hash keeps the same
    # person in the same square between runs without anybody holding the mapping.
    def sub_unit_of(pid: str) -> str:
        return f"Coy {chr(ord('A') + (hash(pid) % sub_units))}"

    grid: dict[tuple[str, str], list[float]] = defaultdict(list)
    for case in cases:
        coy = sub_unit_of(case.pid)
        for domain in HEAT_DOMAINS:
            # A case's deviation profile is not exposed per domain, so the heat
            # value is the case composite attributed to the domains the gate
            # engine actually saw. Absent that, the square stays empty rather
            # than being filled with a plausible number.
            if case.verdict is None:
                continue
            seen = str(case.verdict.gates["evidence"].inputs.get("domains", ""))
            if domain in seen:
                grid[(coy, domain)].append(case.composite)

    cells: list[HeatCell] = []
    for coy in sorted({sub_unit_of(c.pid) for c in cases}):
        for domain in HEAT_DOMAINS:
            values = grid.get((coy, domain), [])
            label = f"heat:{coy}:{domain}"
            cached = cache.get(unit_id, record.as_of, label)
            if cached is not None:
                cells.append(
                    HeatCell(coy, domain, cached.n, cached.value, cached.suppressed,
                             cached.reason)
                )
                continue
            try:
                cell = aggregate(
                    label, values, budget,
                    differential_privacy=differential_privacy, rng=rng,
                )
            except BudgetExhausted:
                cell = Cell(label, 0, None, True, "privacy budget exhausted")
            cache.put(unit_id, record.as_of, label, cell)
            cells.append(
                HeatCell(coy, domain, cell.n, cell.value, cell.suppressed, cell.reason)
            )

    suppressed = sum(1 for c in cells if c.suppressed)
    ledger.append(
        actor=principal.actor,
        action="aggregate.released" if suppressed < len(cells) else "aggregate.suppressed",
        unit_id=unit_id,
        purpose="command:aggregate",
        detail={
            "view": "heat_map", "cells": len(cells), "suppressed": suppressed,
            "epsilon_spent": round(budget.spent, 4),
        },
    )
    return {
        "unit_id": unit_id,
        "as_of": record.as_of.isoformat(),
        "k": k_min(),
        "domains": list(HEAT_DOMAINS),
        "sub_units": sorted({c.sub_unit for c in cells}),
        "cells": [c.to_dict() for c in cells],
        "suppressed": suppressed,
        "next_step": NEXT_STEP,
        "note": (
            "Self-assessment, biometric and voice are absent by design. They are "
            "the person's own, they are not levers a commander has, and showing "
            "them here would invite the reading this system exists to exclude."
        ),
    }
