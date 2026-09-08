"""Connectors that read a synthetic force instead of a records database.

Seven of them, one per service-record domain, each a separate small object — the
same shape a live connector will have, so swapping in a real records pull is a
constructor change and nothing else.

`fail_rate` and `drop_fraction` exist so degradation can be *demonstrated*
rather than described: a run where the leave connector returns 70% of its rows
must produce a data-gap confounder and a `PARTIAL` run record, and the only
honest way to know that it does is to make it happen.
"""
from __future__ import annotations

from datetime import date, timedelta

from samvedna.config.weights import CONNECTOR_DOMAINS, DomainName
from samvedna.ingest.generator import Force
from samvedna.ingest.ports import ConnectorResult, RawRow

__all__ = ["ReplayConnector", "connectors_for"]


class ReplayConnector:
    """One domain, read out of an in-memory synthetic force."""

    def __init__(
        self,
        domain: DomainName,
        force: Force,
        *,
        drop_fraction: float = 0.0,
        fail: bool = False,
    ) -> None:
        self.domain = domain
        self.name = f"replay:{domain}"
        self._force = force
        self._drop = drop_fraction
        self._fail = fail

    def pull(self, as_of: date, days: int) -> ConnectorResult:
        earliest = as_of - timedelta(days=days - 1)
        rows = tuple(
            RawRow(
                service_number=r.pid,  # still identified at this point, by design
                unit_id=r.unit_id,
                observed_at=r.observed_at,
                value=r.value,
                raw_kind=r.raw_kind,
            )
            for r in self._force.records
            if r.domain == self.domain and earliest <= r.observed_at.date() <= as_of
        )
        expected = len(rows)

        if self._fail:
            return ConnectorResult(
                domain=self.domain,
                rows=(),
                expected_rows=expected,
                status="unavailable",
                detail=f"{self.name} did not respond",
            )
        if self._drop > 0.0:
            # Drop a contiguous tail, which is what a records system that went
            # down mid-window actually looks like. Random thinning would be a
            # kinder, less realistic failure.
            keep = int(len(rows) * (1.0 - self._drop))
            return ConnectorResult(
                domain=self.domain,
                rows=rows[:keep],
                expected_rows=expected,
                status="partial",
                detail=f"{self.name} returned {keep} of {expected} rows",
            )
        return ConnectorResult(domain=self.domain, rows=rows, expected_rows=expected)


def connectors_for(
    force: Force,
    *,
    drop: dict[str, float] | None = None,
    failed: tuple[str, ...] = (),
) -> tuple[ReplayConnector, ...]:
    drop = drop or {}
    return tuple(
        ReplayConnector(
            domain,
            force,
            drop_fraction=drop.get(domain, 0.0),
            fail=domain in failed,
        )
        for domain in CONNECTOR_DOMAINS
    )
