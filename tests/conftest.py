"""Builders for decision-layer tests.

Every test in `tests/core` constructs a `CaseContext` by hand, because the point
of L3 being pure is that it can be exercised with no database, no model and no
clock. If a test here needs a fixture file, something has leaked downward.
"""
from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from samvedna.config.weights import ALL_DOMAINS, tier_of, weight_of  # noqa: E402
from samvedna.core.types import (  # noqa: E402
    CaseContext,
    ConsentState,
    DomainDeviation,
    Intervention,
    RiskAssessment,
    UnitContext,
)

NOW = datetime(2026, 9, 5, 2, 0, tzinfo=UTC)
TODAY = date(2026, 9, 5)


def deviation(
    domain: str,
    *,
    z_self: float = 2.6,
    z_unit: float = 2.1,
    direction: str = "elevated",
    windows_breached: int = 3,
    breach: dict[int, float] | None = None,
    missing: float = 0.0,
) -> DomainDeviation:
    return DomainDeviation(
        domain=domain,  # type: ignore[arg-type]
        z_self=z_self,
        z_unit=z_unit,
        direction=direction,  # type: ignore[arg-type]
        windows_breached=windows_breached,
        tier=tier_of(domain),  # type: ignore[arg-type]
        weight=weight_of(domain),  # type: ignore[arg-type]
        daily_breach=breach if breach is not None else {7: 1.0, 30: 1.0, 90: 0.9},
        missing_fraction=missing,
    )


def consent(
    *,
    scope: tuple[str, ...] | None = None,
    welfare_contact: bool = True,
    status: str = "ACTIVE",
) -> ConsentState:
    return ConsentState(
        pid="pid-test",
        scope=frozenset(scope if scope is not None else ALL_DOMAINS),  # type: ignore[arg-type]
        welfare_contact=welfare_contact,
        status=status,  # type: ignore[arg-type]
        updated_at=NOW,
    )


def unit(
    *,
    cohort_size: int = 120,
    deviating: dict[str, float] | None = None,
    sanctioned_leave: tuple[str, ...] = (),
    training: tuple[str, ...] = (),
    seasonal: tuple[str, ...] = (),
    capacity: bool = True,
) -> UnitContext:
    return UnitContext(
        unit_id="unit-A",
        cohort_size=cohort_size,
        cohort_deviating_fraction=dict(deviating or {}),
        sanctioned_leave_domains=frozenset(sanctioned_leave),  # type: ignore[arg-type]
        training_domains=frozenset(training),  # type: ignore[arg-type]
        seasonal_domains=frozenset(seasonal),  # type: ignore[arg-type]
        welfare_capacity_available=capacity,
    )


def case(
    *deviations: DomainDeviation,
    consent_state: ConsentState | None = None,
    unit_state: UnitContext | None = None,
    risk: RiskAssessment | None = None,
    active: tuple[Intervention, ...] = (),
    suppressed: tuple[str, ...] = (),
    acute: tuple[str, ...] = (),
    clinician_concern: bool = False,
) -> CaseContext:
    return CaseContext(
        pid="pid-test",
        unit_id="unit-A",
        as_of=TODAY,
        deviations=deviations,
        consent=consent_state or consent(),
        unit=unit_state or unit(),
        risk=risk,
        active_interventions=active,
        suppressed_drivers=frozenset(suppressed),
        acute_items=acute,
        clinician_concern=clinician_concern,
    )


@pytest.fixture
def build():
    return case


@pytest.fixture(scope="session", autouse=True)
def _no_shared_journal(tmp_path_factory):
    """Persistence is off for the suite. The journal tests turn it on.

    Two attempts got this wrong in instructive ways.

    Pointing every test at one temp database still shared state — a
    walk-through test failed because an earlier test's assessment had already
    escalated its subject. Pointing each test at its *own* temp database cannot
    work either: `tests/workflow/test_api.py` builds its world with
    `@pytest.fixture(scope="module")`, and pytest sets function-scoped fixtures
    up after higher-scoped ones, so the module fixture ran before any
    per-test patch existed and opened the real database in the repository root.

    So persistence is simply off here. It is a feature of a running deployment,
    not a property the rest of the suite is testing, and every test that does
    not care about it should behave exactly as it did before the journal
    existed. `tests/storage/test_journal.py` enables it against a temp database
    of its own.
    """
    import samvedna.api.app as app_mod
    import samvedna.api.bootstrap as bootstrap
    import samvedna.api.voice_routes as voice_mod
    import samvedna.config.flags as flags

    off = flags.settings().model_copy(
        update={
            "persist_state": False,
            # Belt and braces: if something opens a store despite the flag, it
            # must not be the repository's database.
            "database_url": (
                f"sqlite+aiosqlite:///{tmp_path_factory.mktemp('journal')}/unused.db"
            ),
        }
    )
    with pytest.MonkeyPatch.context() as patch:
        for module in (flags, bootstrap, app_mod, voice_mod):
            patch.setattr(module, "settings", lambda: off, raising=False)
        yield
