"""REPLAY — run the full pipeline offline from synthetic fixtures.

PART 1 constraint 7 makes this non-negotiable: no demo may depend on live
service-record access. REPLAY is also the default run mode, so the failure mode
is a demo that runs on fixtures when it should have run on records, rather than
a demo that reaches for records that are not there.

The loader deliberately **drops the `expected` field** from every fixture. It is
there for the test suite to assert against, and if the pipeline could read it,
constraint 8 — that the MONITOR path is produced by the gate engine and never by
a demo branch — would be unprovable. `EXCLUDED_FIELDS` is asserted in a test.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from samvedna.config.weights import tier_of, weight_of
from samvedna.core.interventions import BY_CODE
from samvedna.core.types import (
    CaseContext,
    ConsentState,
    DomainDeviation,
    UnitContext,
)

__all__ = ["EXCLUDED_FIELDS", "load_cohort", "cohort_names", "Cohort"]

# Fields the pipeline must never see. `expected` is the fixture's own answer and
# `note` is prose written for a human reading the JSON.
EXCLUDED_FIELDS = frozenset({"expected", "note"})


class Cohort(list):
    """A list of CaseContext, plus the cohort's metadata.

    Subclassing `list` means an empty cohort is falsy, which is the same trap
    `Ledger.__bool__` documents. Here it is left as-is deliberately: an empty
    cohort really is nothing to process, and no code path substitutes a default
    for one. The comment exists so the next person checks rather than assumes.
    """

    def __init__(self, name: str, description: str, as_of: date, cases):
        super().__init__(cases)
        self.name = name
        self.description = description
        self.as_of = as_of


def _consent(pid: str, block: dict, as_of: date) -> ConsentState:
    from datetime import UTC, datetime

    return ConsentState(
        pid=pid,
        scope=frozenset(block["scope"]),
        welfare_contact=bool(block["welfare_contact"]),
        status=block["status"],
        updated_at=datetime(as_of.year, as_of.month, as_of.day, tzinfo=UTC),
    )


def _unit(block: dict) -> UnitContext:
    return UnitContext(
        unit_id=block["unit_id"],
        cohort_size=int(block["cohort_size"]),
        cohort_deviating_fraction={k: float(v) for k, v in
                                   block.get("cohort_deviating_fraction", {}).items()},
        sanctioned_leave_domains=frozenset(block.get("sanctioned_leave_domains", [])),
        training_domains=frozenset(block.get("training_domains", [])),
        seasonal_domains=frozenset(block.get("seasonal_domains", [])),
        welfare_capacity_available=bool(block.get("welfare_capacity_available", True)),
    )


def _deviation(block: dict) -> DomainDeviation:
    domain = block["domain"]
    return DomainDeviation(
        domain=domain,
        z_self=float(block["z_self"]),
        z_unit=float(block["z_unit"]),
        direction=block["direction"],
        windows_breached=int(block["windows_breached"]),
        # Tier and weight are read from config, never from the fixture. A fixture
        # that could set its own tier could promote a T3 domain to T1, which is
        # exactly what PART 6.1 forbids a model from doing.
        tier=tier_of(domain),
        weight=weight_of(domain),
        daily_breach={int(k): float(v) for k, v in block.get("daily_breach", {}).items()},
        missing_fraction=float(block.get("missing_fraction", 0.0)),
    )


def load_cohort(name: str, fixtures_dir: str | Path = "fixtures") -> Cohort:
    path = Path(fixtures_dir) / f"cohort_{name}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    as_of = date.fromisoformat(payload["as_of"])
    cases = []
    for raw in payload["personnel"]:
        block = {k: v for k, v in raw.items() if k not in EXCLUDED_FIELDS}
        cases.append(
            CaseContext(
                pid=block["pid"],
                unit_id=block["unit_id"],
                as_of=as_of,
                deviations=tuple(_deviation(d) for d in block["deviations"]),
                consent=_consent(block["pid"], block["consent"], as_of),
                unit=_unit(block["unit"]),
                active_interventions=tuple(
                    BY_CODE[c] for c in block.get("active_interventions", [])
                ),
                suppressed_drivers=frozenset(block.get("suppressed_drivers", [])),
                acute_items=tuple(block.get("acute_items", [])),
                clinician_concern=bool(block.get("clinician_concern", False)),
            )
        )
    return Cohort(payload["cohort"], payload["description"], as_of, cases)


def expected_verdicts(name: str, fixtures_dir: str | Path = "fixtures") -> dict[str, str]:
    """Test-suite only. Nothing in `samvedna.pipeline` may call this."""
    path = Path(fixtures_dir) / f"cohort_{name}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {p["pid"]: p["expected"] for p in payload["personnel"]}


def cohort_names(fixtures_dir: str | Path = "fixtures") -> list[str]:
    return sorted(
        p.stem.removeprefix("cohort_") for p in Path(fixtures_dir).glob("cohort_*.json")
    )
