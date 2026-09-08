"""Reads a domain out of an HRMS export file.

This is the reference integration, and it deliberately reads a *file* rather
than calling an API. In the environments this system is built for, that is what
integration actually looks like: the HRMS writes a nightly extract to a share
inside the network, and the analytics side reads it. There is no outbound
connection, no credential in the analytics tier, no token to rotate, and no live
dependency that can make a welfare run fail because a records server was
rebooted. A pull-from-API connector would satisfy the same `Connector` protocol
and can be written later; it would be the less secure of the two.

What this class is careful about is the difference between *absent* and *zero*.
An HRMS extract is routinely short — a unit's clerk has not filed yet, a domain
is not tracked at one station, a station was off the network. Every one of those
must arrive downstream as missingness, never as a low value, because a zero is
a signal and an absence is not. So:

* `expected_rows` comes from the roster and the window, not from the file. If
  the file is half empty, `missing_fraction` says so and the data-gap
  confounder fires. Deriving it from the row count would make every file
  perfectly complete by definition.
* A row that fails validation is counted and dropped, never coerced. A duty
  roster reading of `-3` hours is a broken extract, and clamping it to zero
  would turn a bug in somebody else's system into a welfare finding here.
* Nothing is interpolated, forward-filled or averaged across a gap.

Values are normalised to 0..1 by an explicit per-domain scale rather than by
whatever range happens to appear in the file. Fitting the scale to the data
would mean the same 14-hour day reads differently depending on how hard the
rest of the unit worked that month.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from samvedna.config.weights import DomainName
from samvedna.ingest.ports import ConnectorResult, RawRow

__all__ = ["HRMS_SCALES", "ColumnMap", "HrmsExportConnector"]

# The full-scale value for each domain: what counts as 1.0. These are policy
# numbers and they live here rather than being inferred, for the reason in the
# module docstring. A deployment tunes them once, in review, against its own
# establishment norms.
HRMS_SCALES: dict[DomainName, float] = {
    "leave": 30.0,          # days of pending/denied leave
    "duty_roster": 16.0,    # hours on duty in a day
    "deployment": 1.0,      # already a fraction of the day deployed
    "workload": 20.0,       # tasked hours in a day
    "transfer": 5.0,        # transfers in the trailing window
    "training": 12.0,       # committed training hours in a day
    "self_report": 27.0,    # PHQ-9 total
    "biometric": 1.0,       # already normalised by the device
}


@dataclass(frozen=True, slots=True)
class ColumnMap:
    """Which columns in *this* HRMS's export mean what.

    Every HRMS names its columns differently and none of them will rename them
    for us, so the mapping is configuration. Defaults match the column names in
    `fixtures/hrms/`, which is a worked example rather than a standard.
    """

    service_number: str = "service_no"
    unit_id: str = "unit"
    observed_on: str = "date"
    value: str = "value"
    # Optional. When present and parseable it overrides `observed_on`, which
    # lets an HRMS that stamps a full timestamp keep its precision.
    observed_at: str = "timestamp"


@dataclass
class HrmsExportConnector:
    """One domain, read from one delimited export file."""

    domain: DomainName
    path: Path
    roster_size: int
    columns: ColumnMap = field(default_factory=ColumnMap)
    # Rows this HRMS is expected to file per person per day for this domain.
    # Leave and transfer are event-shaped, not daily, so a deployment sets this
    # below 1.0 rather than having the data-gap confounder fire on every run
    # for a domain that is sparse by nature.
    rows_per_person_per_day: float = 1.0
    delimiter: str = ","
    scale: float | None = None

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.name = f"hrms:{self.domain}"

    def _full_scale(self) -> float:
        explicit = self.scale if self.scale is not None else HRMS_SCALES.get(self.domain)
        # A zero or negative scale would divide every value into nonsense, so it
        # is refused at construction-read time rather than producing quiet
        # rubbish for a whole run.
        if not explicit or explicit <= 0:
            raise ValueError(f"{self.name}: no positive full-scale value configured")
        return float(explicit)

    def pull(self, as_of: date, days: int) -> ConnectorResult:
        expected = max(0, round(self.roster_size * days * self.rows_per_person_per_day))
        earliest = as_of - timedelta(days=days - 1)

        if not self.path.exists():
            # A missing extract is a degraded run, not an empty one. Returning
            # `ok` with no rows would let the pipeline treat "the clerk did not
            # file" as "nobody worked this month".
            return ConnectorResult(
                domain=self.domain,
                rows=(),
                expected_rows=expected,
                status="unavailable",
                detail=f"no export at {self.path.name}",
            )

        full_scale = self._full_scale()
        rows: list[RawRow] = []
        rejected = 0
        out_of_window = 0

        with self.path.open(newline="", encoding="utf-8-sig") as handle:
            for record in csv.DictReader(handle, delimiter=self.delimiter):
                parsed = self._row(record, full_scale)
                if parsed is None:
                    rejected += 1
                    continue
                if not (earliest <= parsed.observed_at.date() <= as_of):
                    out_of_window += 1
                    continue
                rows.append(parsed)

        notes = []
        if rejected:
            notes.append(f"{rejected} row(s) rejected as malformed")
        if out_of_window:
            notes.append(f"{out_of_window} outside the window")
        # Malformed rows degrade the run. They are somebody else's bug, and a
        # welfare decision should not be taken on a file that is partly
        # unreadable without that being on the record.
        return ConnectorResult(
            domain=self.domain,
            rows=tuple(rows),
            expected_rows=expected,
            status="partial" if rejected else "ok",
            detail="; ".join(notes),
        )

    def _row(self, record: dict[str, str], full_scale: float) -> RawRow | None:
        """One export row, or None if it cannot be trusted.

        Every failure here returns None rather than raising: one bad line in a
        50,000-line extract must not lose the other 49,999, and it must not
        silently become a value either.
        """
        cols = self.columns
        service_number = (record.get(cols.service_number) or "").strip()
        unit_id = (record.get(cols.unit_id) or "").strip()
        if not service_number or not unit_id:
            return None

        observed_at = self._when(record)
        if observed_at is None:
            return None

        raw = (record.get(cols.value) or "").strip()
        if not raw:
            return None
        try:
            value = float(raw)
        except ValueError:
            return None
        # Negative is not a low reading, it is a broken extract.
        if value < 0:
            return None

        normalised = value / full_scale
        # Above full scale is clamped rather than rejected: a genuine 18-hour day
        # against a 16-hour scale is real data at the top of the range, unlike a
        # negative figure which cannot be.
        return RawRow(
            service_number=service_number,
            unit_id=unit_id,
            observed_at=observed_at,
            value=min(1.0, normalised),
            raw_kind=f"hrms:{self.domain}",
        )

    def _when(self, record: dict[str, str]) -> datetime | None:
        cols = self.columns
        stamp = (record.get(cols.observed_at) or "").strip()
        if stamp:
            try:
                parsed = datetime.fromisoformat(stamp)
            except ValueError:
                parsed = None
            if parsed is not None:
                # A naive timestamp is read as UTC rather than as local time.
                # Local would make the same export land on different days
                # depending on which machine ran the pipeline.
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

        day = (record.get(cols.observed_on) or "").strip()
        if not day:
            return None
        try:
            return datetime.combine(date.fromisoformat(day), datetime.min.time(), tzinfo=UTC)
        except ValueError:
            return None
