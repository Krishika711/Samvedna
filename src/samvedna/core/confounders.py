"""Deterministic benign explanations, and the mass each contributes.

This module is what gives the Confounder Check reviewer mechanical power. A
reviewer can write the most persuasive paragraph in the world about a unit being
deployed, and it will not move a single number — what moves numbers is a rule
here firing on structured facts, and adding weight *against* the signal in the
consistency gate.

The most important rule is `unit_op_tempo`. When 40% of a jawan's unit is
deviating the same way in the same domain, the finding is not about the jawan.
It is a command workload problem, and naming an individual for it would be both
wrong and the fastest way to lose the force's confidence in the system.

Pure. No I/O. Same facts in, same hits out.
"""
from __future__ import annotations

from samvedna.config.thresholds import (
    CONFOUNDER_LABEL,
    CONFOUNDER_MASS,
    DATA_GAP_MISSING_FRACTION,
    UNIT_OP_TEMPO_COHORT_FRACTION,
)
from samvedna.core.types import CaseContext, ConfounderHit, DomainDeviation, UnitContext


def _hit(rule: str, domain: str, detail: str) -> ConfounderHit:
    return ConfounderHit(
        rule=rule,
        domain=domain,  # type: ignore[arg-type]
        mass=CONFOUNDER_MASS[rule],
        label=CONFOUNDER_LABEL[rule],
        detail=detail,
    )


def _unit_op_tempo(dev: DomainDeviation, unit: UnitContext) -> ConfounderHit | None:
    fraction = unit.cohort_deviating_fraction.get(dev.domain, 0.0)
    if fraction < UNIT_OP_TEMPO_COHORT_FRACTION:
        return None
    return _hit(
        "unit_op_tempo",
        dev.domain,
        f"{fraction:.0%} of the unit cohort ({unit.cohort_size} personnel) deviates "
        f"in {dev.domain} in the same direction; threshold is "
        f"{UNIT_OP_TEMPO_COHORT_FRACTION:.0%}",
    )


def _planned_leave(dev: DomainDeviation, unit: UnitContext) -> ConfounderHit | None:
    if dev.domain not in unit.sanctioned_leave_domains:
        return None
    return _hit(
        "planned_leave_cycle",
        dev.domain,
        f"the {dev.domain} deviation coincides with an approved leave calendar entry",
    )


def _scheduled_training(dev: DomainDeviation, unit: UnitContext) -> ConfounderHit | None:
    if dev.domain not in unit.training_domains:
        return None
    return _hit(
        "scheduled_training",
        dev.domain,
        f"{dev.domain} load is explained by a scheduled training assignment",
    )


def _seasonal(dev: DomainDeviation, unit: UnitContext) -> ConfounderHit | None:
    if dev.domain not in unit.seasonal_domains:
        return None
    return _hit(
        "seasonal_roster",
        dev.domain,
        f"the same {dev.domain} deviation is present in the prior year's same window",
    )


def _data_gap(dev: DomainDeviation, unit: UnitContext) -> ConfounderHit | None:
    if dev.missing_fraction <= DATA_GAP_MISSING_FRACTION:
        return None
    return _hit(
        "data_gap",
        dev.domain,
        f"{dev.missing_fraction:.0%} of {dev.domain} records are missing in the "
        f"window; above {DATA_GAP_MISSING_FRACTION:.0%} the window is an artefact",
    )


RULES = (_unit_op_tempo, _planned_leave, _scheduled_training, _seasonal, _data_gap)


def detect(ctx: CaseContext) -> tuple[ConfounderHit, ...]:
    """Every benign explanation that fires, across every deviating domain."""
    hits: list[ConfounderHit] = []
    for dev in ctx.deviations:
        for rule in RULES:
            hit = rule(dev, ctx.unit)
            if hit is not None:
                hits.append(hit)
    return tuple(hits)


def rules_by_domain(hits: tuple[ConfounderHit, ...]) -> dict[str, dict[str, float]]:
    """Which rules fired on each domain, and with what mass.

    Needed by the consistency gate to tell *shared* benign explanations from
    unshared ones. Two domains explained by the same unit surge are not
    corroborating each other — they have a common cause.
    """
    out: dict[str, dict[str, float]] = {}
    for hit in hits:
        out.setdefault(hit.domain, {})[hit.rule] = hit.mass
    return out


def mass_by_domain(hits: tuple[ConfounderHit, ...]) -> dict[str, float]:
    """Total confounder mass standing against each domain.

    Masses sum rather than max. Two independent benign explanations really are
    more explanatory than one, and summing keeps the consistency gate monotone:
    adding a confounder can never raise the score, which is a property test.
    """
    totals: dict[str, float] = {}
    for hit in hits:
        totals[hit.domain] = totals.get(hit.domain, 0.0) + hit.mass
    return totals
