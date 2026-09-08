"""What would change our mind — computed by inverting the gate, never generated.

This is the module that turns silence into a statement. When the gates decline to
name somebody, the system does not shrug; it says exactly what additional evidence
would have produced a different answer, in terms the officer reading it can go and
check.

**No language model may write any of this text.** A generated sentence is a
sentence nobody can verify, and "more data would help" is a bug. "One voluntary
wellness self-assessment (worth 0.20 of the evidence gate), or corroboration from
two further domains" is correct, because both halves are checkable and both were
derived by solving the gate for the shortfall.
"""
from __future__ import annotations

import math

from samvedna.config.weights import (
    EVIDENCE_BREADTH_TARGET,
    EVIDENCE_VOLUME_SATURATION,
    EVIDENCE_W_HAS_T1,
    EVIDENCE_W_VOLUME,
    PERSISTENCE_W_30D,
    TIER_WEIGHT,
)
from samvedna.config.windows import PRIMARY_WINDOW_DAYS
from samvedna.core.types import CaseContext, ConfounderHit, Gate, GateName, MindChangeItem

__all__ = ["for_gate", "compute"]


def _evidence_items(gate: Gate) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    shortfall = gate.threshold - gate.value
    has_t1 = bool(gate.inputs["has_t1"])
    breadth = float(gate.inputs["breadth"])  # type: ignore[arg-type]
    distinct = int(gate.inputs["distinct_domains"])  # type: ignore[arg-type]

    because = [
        f"weighted corroboration is {gate.inputs['weighted_volume']} of "
        f"{EVIDENCE_VOLUME_SATURATION} weighted units",
        f"{distinct} of {EVIDENCE_BREADTH_TARGET} independent domains are deviating",
    ]
    if not has_t1:
        because.append("no validated self-assessment (T1) is present")

    changes: list[str] = []
    if not has_t1 and shortfall <= EVIDENCE_W_HAS_T1:
        changes.append(
            f"one voluntary wellness self-assessment (T1), worth "
            f"{EVIDENCE_W_HAS_T1:.2f} of this gate on its own"
        )
    # Solve the volume term for the shortfall: how many weighted units are needed.
    needed_units = shortfall / EVIDENCE_W_VOLUME * EVIDENCE_VOLUME_SATURATION
    if float(gate.inputs["volume"]) < 1.0:  # type: ignore[arg-type]
        n_t2 = math.ceil(needed_units / TIER_WEIGHT["T2"])
        changes.append(
            f"corroboration from {n_t2} further service-record "
            f"domain{'s' if n_t2 != 1 else ''} "
            f"({needed_units:.2f} weighted units short)"
        )
    if breadth < 1.0:
        missing = EVIDENCE_BREADTH_TARGET - distinct
        changes.append(
            f"{missing} more distinct deviating domain{'s' if missing != 1 else ''} "
            f"to satisfy the breadth requirement"
        )
    return tuple(because), tuple(changes), True


def _consistency_items(
    gate: Gate, hits: tuple[ConfounderHit, ...]
) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    because: list[str] = []
    changes: list[str] = []
    if not hits:
        because.append(
            "deviating domains do not agree with one another; "
            f"{gate.inputs['n_domains']} domain(s) assessed"
        )
        changes.append(
            "a further domain deviating in the same direction, "
            "so the existing signal is corroborated rather than isolated"
        )
    for hit in hits:
        because.append(f"{hit.label} on {hit.domain} (mass {hit.mass:.2f}) — {hit.detail}")
        if hit.rule == "unit_op_tempo":
            changes.append(
                f"the {hit.domain} deviation is still present after the unit's "
                f"current deployment cycle ends (op-tempo confounder, {hit.mass:.2f})"
            )
        elif hit.rule == "planned_leave_cycle":
            changes.append(
                f"the {hit.domain} deviation continues outside the sanctioned "
                f"leave window (planned-leave confounder, {hit.mass:.2f})"
            )
        elif hit.rule == "scheduled_training":
            changes.append(
                f"the {hit.domain} deviation persists after the training "
                f"assignment concludes (training confounder, {hit.mass:.2f})"
            )
        elif hit.rule == "seasonal_roster":
            changes.append(
                f"the {hit.domain} deviation exceeds the prior-year same-window "
                f"level (seasonal confounder, {hit.mass:.2f})"
            )
        elif hit.rule == "data_gap":
            changes.append(
                f"the missing {hit.domain} records for this window are supplied by "
                f"the unit records custodian (data-gap confounder, {hit.mass:.2f})"
            )
    # A confounder is recoverable — it can expire or be disproved. A structural
    # disagreement between domains is not something the person can act on.
    return tuple(because), tuple(changes), bool(hits)


def _persistence_items(gate: Gate) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    shortfall = gate.threshold - gate.value
    w30 = float(gate.inputs["w30d"])  # type: ignore[arg-type]
    because = [
        f"breach fraction is {gate.inputs['w7d']} over 7 days, "
        f"{w30} over 30 days, {gate.inputs['w90d']} over 90 days"
    ]
    # Solve the 30-day term: how many more breaching days close the gap.
    extra_fraction = shortfall / PERSISTENCE_W_30D
    extra_days = math.ceil(min(1.0 - w30, extra_fraction) * PRIMARY_WINDOW_DAYS)
    changes: list[str] = []
    if extra_days > 0 and w30 + extra_fraction <= 1.0:
        changes.append(
            f"the deviation is sustained a further {extra_days} day"
            f"{'s' if extra_days != 1 else ''} within the "
            f"{PRIMARY_WINDOW_DAYS}-day window"
        )
    else:
        changes.append(
            "the deviation is sustained across the 90-day window as well as the "
            "30-day window; the 30-day window alone can no longer close this gap"
        )
    return tuple(because), tuple(changes), True


def _actionability_items(gate: Gate) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    because: list[str] = []
    changes: list[str] = []
    recoverable = True
    if not gate.inputs["consent_ok"]:
        because.append("consent does not extend to welfare contact")
        changes.append(
            "the person extends consent to welfare contact in the app "
            "(this is theirs to give, and the system will not ask again)"
        )
    if not gate.inputs["match"]:
        because.append("no playbook intervention matches the current drivers")
        changes.append("a welfare action covering these drivers is added to the playbook")
    if not gate.inputs["not_duplicate"]:
        because.append(
            f"an active intervention ({gate.inputs['duplicate_of']}) already "
            f"covers these drivers"
        )
        changes.append(f"the current intervention {gate.inputs['duplicate_of']} is concluded")
        recoverable = False
    if not gate.inputs["capacity"]:
        because.append("unit welfare capacity for this period is exhausted")
        changes.append("welfare capacity becomes available in the next cycle")
    return tuple(because), tuple(changes), recoverable


def for_gate(gate: Gate, hits: tuple[ConfounderHit, ...] = ()) -> MindChangeItem:
    """Invert one failed gate into the cheapest condition that would close it."""
    domain_hits = tuple(h for h in hits) if gate.name == "consistency" else ()
    if gate.name == "evidence":
        because, changes, recoverable = _evidence_items(gate)
    elif gate.name == "consistency":
        because, changes, recoverable = _consistency_items(gate, domain_hits)
    elif gate.name == "persistence":
        because, changes, recoverable = _persistence_items(gate)
    else:
        because, changes, recoverable = _actionability_items(gate)
    return MindChangeItem(
        gate=gate.name,
        current=round(gate.value, 4),
        required=gate.threshold,
        failed_because=because,
        would_change_if=changes,
        recoverable=recoverable,
    )


def compute(
    _ctx: CaseContext,
    gates: dict[GateName, Gate],
    hits: tuple[ConfounderHit, ...] = (),
) -> tuple[MindChangeItem, ...]:
    """One item per failed gate, cheapest-to-close first."""
    items = [for_gate(gate, hits) for gate in gates.values() if not gate.passed]
    items.sort(key=lambda i: (not i.recoverable, i.required - i.current))
    return tuple(items)
