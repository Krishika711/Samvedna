"""Legal state transitions for a pid within one cycle.

Nothing reaches ESCALATED without a gate verdict of ESCALATE or a logged
override. That sentence is only true if it is enforced somewhere, and this is
where — an illegal transition raises rather than logging a warning, because a
warning in a nightly batch is a thing nobody reads.
"""
from __future__ import annotations

from typing import Literal

__all__ = ["State", "LEGAL", "assert_transition", "IllegalTransition"]

State = Literal[
    "OBSERVED",
    "DEVIATING",
    "SCORED",
    "REVIEWED",
    "GATED",
    "ESCALATED",
    "CONTACTED",
    "CLOSED",
    "MONITORED",
    "CLEARED",
]

LEGAL: dict[State, frozenset[State]] = {
    "OBSERVED": frozenset({"DEVIATING", "CLEARED"}),
    "DEVIATING": frozenset({"SCORED", "CLEARED"}),
    "SCORED": frozenset({"REVIEWED"}),
    "REVIEWED": frozenset({"GATED"}),
    # An override skips straight from REVIEWED-equivalent to ESCALATED, but it
    # still passes through GATED so the gate values are recorded even when they
    # did not decide anything. An officer must be able to see what the gates said
    # about a case the override carried.
    "GATED": frozenset({"ESCALATED", "MONITORED", "CLEARED"}),
    "ESCALATED": frozenset({"CONTACTED", "MONITORED", "CLOSED"}),
    "CONTACTED": frozenset({"CLOSED"}),
    "MONITORED": frozenset({"OBSERVED", "ESCALATED", "CLEARED"}),
    "CLOSED": frozenset(),
    "CLEARED": frozenset(),
}


class IllegalTransition(RuntimeError):
    pass


def assert_transition(current: State, nxt: State) -> None:
    if nxt not in LEGAL[current]:
        raise IllegalTransition(f"{current} -> {nxt} is not a legal transition")
