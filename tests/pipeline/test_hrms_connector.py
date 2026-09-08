"""The HRMS integration seam.

The problem statement's scope includes "secure integration with HRMS and
personnel management systems", and the reference implementation reads a nightly
export file rather than calling an API — no outbound connection, no credential
in the analytics tier, no live dependency that can fail a welfare run.

What these tests are actually protecting is the boundary between *absent* and
*zero*. An HRMS extract is routinely short, and every way of papering over that
turns somebody else's filing delay into a welfare finding here.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from samvedna.ingest.connectors.hrms import HrmsExportConnector
from samvedna.ingest.ports import Connector

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "hrms" / "workload.csv"
AS_OF = date(2026, 9, 5)


def connector(**kw) -> HrmsExportConnector:
    return HrmsExportConnector(
        domain="workload", path=FIXTURE, roster_size=kw.pop("roster_size", 6), **kw
    )


def test_it_satisfies_the_connector_protocol():
    """Nothing downstream may be able to tell this from the replay connector."""
    assert isinstance(connector(), Connector)


def test_good_rows_are_normalised_against_the_configured_scale():
    """20 tasked hours is full scale, so 14.5 is 0.725 — not 'the highest seen'.

    Fitting the scale to the file would mean the same 14-hour day read
    differently depending on how hard the rest of the unit worked that month.
    """
    result = connector().pull(AS_OF, days=7)
    by_person = {
        r.service_number: r.value
        for r in result.rows
        if r.observed_at.date() == AS_OF
    }

    assert by_person["CAPF-000001"] == pytest.approx(14.5 / 20.0)
    assert by_person["CAPF-000002"] == pytest.approx(8.0 / 20.0)


def test_above_full_scale_clamps_but_negative_is_rejected():
    """A real 22-hour day is data at the top of the range. Minus three is not.

    Clamping a negative to zero would turn a broken extract into a welfare
    signal, because zero is a reading and absence is not.
    """
    result = connector().pull(AS_OF, days=7)
    values = {r.service_number: r.value for r in result.rows}

    assert values["CAPF-000003"] == 1.0, "22 hours against a 20-hour scale should clamp"
    assert "CAPF-000004" not in values, "a negative value was accepted"


def test_malformed_rows_are_dropped_counted_and_degrade_the_run():
    """One bad line must not lose the file, and must not be invisible either."""
    result = connector().pull(AS_OF, days=7)

    assert result.status == "partial", "a file with unreadable rows reported as ok"
    assert "rejected as malformed" in result.detail
    numbers = {r.service_number for r in result.rows}
    assert "CAPF-000005" not in numbers, "'not-a-number' became a value"
    assert "" not in numbers, "a row with no service number was accepted"


def test_rows_outside_the_window_are_excluded_not_counted_as_malformed():
    result = connector().pull(AS_OF, days=7)

    assert "CAPF-000006" not in {r.service_number for r in result.rows}
    assert "1 outside the window" in result.detail


def test_expected_rows_comes_from_the_roster_not_the_file():
    """Otherwise every extract is complete by definition and the gap never fires."""
    result = connector(roster_size=6).pull(AS_OF, days=7)

    assert result.expected_rows == 42, "expected_rows was derived from the file"
    assert result.missing_fraction > 0.8, (
        "a nearly-empty extract reported as nearly complete"
    )


def test_a_sparse_domain_can_lower_its_expectation():
    """Leave and transfer are event-shaped, not daily.

    Without this the data-gap confounder fires forever on domains that are
    sparse by nature — which is the bug that once produced zero escalations
    across the whole cohort.
    """
    dense = connector(roster_size=6).pull(AS_OF, days=7)
    sparse = connector(roster_size=6, rows_per_person_per_day=0.05).pull(AS_OF, days=7)

    assert sparse.expected_rows < dense.expected_rows
    assert sparse.missing_fraction < dense.missing_fraction


def test_a_missing_export_is_unavailable_rather_than_empty():
    """'The clerk has not filed' must not read as 'nobody worked this month'."""
    result = HrmsExportConnector(
        domain="workload", path=FIXTURE.parent / "nope.csv", roster_size=6
    ).pull(AS_OF, days=7)

    assert result.rows == ()
    assert result.status == "unavailable"
    assert result.degraded
    assert result.expected_rows == 42, "an unavailable connector must still report the gap"


def test_a_domain_with_no_scale_is_refused_rather_than_guessed():
    with pytest.raises(ValueError, match="full-scale"):
        HrmsExportConnector(
            domain="workload", path=FIXTURE, roster_size=6, scale=0.0
        ).pull(AS_OF, days=7)
