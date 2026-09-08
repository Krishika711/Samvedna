"""The seams at L1. Everything replaceable is a Protocol here.

Keeping the contracts in one small module makes the substitution matrix obvious:
a REPLAY connector reading synthetic fixtures and a live connector reading a unit
records database satisfy the same interface, and nothing downstream can tell
which one it got. That is what makes constraint 7 — REPLAY runs the full pipeline
offline — a property of the architecture rather than a demo mode.

Contracts are deliberately narrow. A connector does not know what a pid is, what
consent is, or what a gate is. It pulls rows for one domain and stops.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable

from samvedna.config.weights import DomainName

__all__ = ["RawRow", "Connector", "ConnectorResult", "ConsentRegistry"]


@dataclass(frozen=True, slots=True)
class RawRow:
    """One row as it exists in the unit's records — still identified.

    This is the only type in the system that carries a service number, and it
    exists for exactly one hop: connector to `normalise`. Nothing downstream
    accepts it.
    """

    service_number: str
    unit_id: str
    observed_at: datetime
    value: float
    raw_kind: str


@dataclass(frozen=True, slots=True)
class ConnectorResult:
    """Rows plus an honest account of what was not retrieved.

    `missing_fraction` feeds the data-gap confounder. A connector that silently
    returns a short result turns missingness into a signal, which PART 8.8
    forbids — so the shortfall is reported, not smoothed over.
    """

    domain: DomainName
    rows: tuple[RawRow, ...]
    expected_rows: int
    status: str = "ok"
    detail: str = ""

    @property
    def missing_fraction(self) -> float:
        if self.expected_rows <= 0:
            return 0.0
        return max(0.0, 1.0 - len(self.rows) / self.expected_rows)

    @property
    def degraded(self) -> bool:
        return self.status != "ok"


@runtime_checkable
class Connector(Protocol):
    """Pulls one domain's rows for a window. One job, one log, one test."""

    domain: DomainName
    name: str

    def pull(self, as_of: date, days: int) -> ConnectorResult: ...


@runtime_checkable
class ConsentRegistry(Protocol):
    """Consent state per pid, evaluated per run and never cached across runs.

    Keyed by pid rather than by service number on purpose: the registry sits
    downstream of pseudonymisation, so even the consent store holds no identifier.
    """

    def state_for(self, pid: str) -> object: ...
