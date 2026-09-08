"""RawRow -> SignalRecord. The boundary an identifier does not cross.

This is a short module doing one irreversible thing, and it is short on purpose:
everything that happens here should be visible on one screen, because "where does
the service number stop?" is the first question anybody serious will ask.

Two filters, in this order:

1. **Pseudonymise.** The service number becomes a pid and is not carried forward.
   Not masked, not encrypted-and-attached — dropped.
2. **Consent.** A domain the person has not consented to is discarded here, not
   marked and passed on. A record that exists downstream is a record something
   can accidentally use.

Order matters. Pseudonymising first means the consent registry itself holds no
identifier, so a leak of the consent store is not a leak of who is enrolled.
"""
from __future__ import annotations

from dataclasses import dataclass

from samvedna.config.weights import DomainName
from samvedna.core.types import ConsentState, SignalRecord
from samvedna.ingest.ports import ConnectorResult
from samvedna.ingest.pseudonymise import Pseudonymiser

__all__ = ["NormaliseReport", "normalise"]


@dataclass(frozen=True, slots=True)
class NormaliseReport:
    """What came in, what went out, and why the difference.

    Reported rather than logged, because a nightly batch's warnings are read by
    nobody and this difference is the consent filter doing its job.
    """

    records: tuple[SignalRecord, ...]
    rows_in: int
    dropped_no_consent: int
    dropped_not_enrolled: int
    missing_fraction: dict[DomainName, float]
    degraded_domains: tuple[DomainName, ...]

    @property
    def rows_out(self) -> int:
        return len(self.records)


def normalise(
    results: tuple[ConnectorResult, ...],
    pseudonymiser: Pseudonymiser,
    consent_for,  # Callable[[str], ConsentState | None]
) -> NormaliseReport:
    """Pseudonymise, then drop everything consent does not cover."""
    out: list[SignalRecord] = []
    rows_in = 0
    no_consent = 0
    not_enrolled = 0
    missing: dict[DomainName, float] = {}
    degraded: list[DomainName] = []

    for result in results:
        missing[result.domain] = result.missing_fraction
        if result.degraded:
            degraded.append(result.domain)

        for row in result.rows:
            rows_in += 1
            pid = pseudonymiser.pid(row.service_number)
            state: ConsentState | None = consent_for(pid)
            if state is None or state.status in ("NOT_ENROLLED", "REVOKED"):
                not_enrolled += 1
                continue
            if not state.covers(result.domain):
                no_consent += 1
                continue
            out.append(
                SignalRecord(
                    pid=pid,
                    domain=result.domain,
                    observed_at=row.observed_at,
                    value=row.value,
                    raw_kind=row.raw_kind,
                    unit_id=row.unit_id,
                    consent_scope=state.scope,
                )
            )

    return NormaliseReport(
        records=tuple(out),
        rows_in=rows_in,
        dropped_no_consent=no_consent,
        dropped_not_enrolled=not_enrolled,
        missing_fraction=missing,
        degraded_domains=tuple(degraded),
    )
