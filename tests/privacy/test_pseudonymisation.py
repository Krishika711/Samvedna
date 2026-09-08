"""Phase 3 ship gate: no identifier past L1, proven rather than asserted."""
from __future__ import annotations

from datetime import date

import pytest

from samvedna.config.weights import ALL_DOMAINS
from samvedna.disclosure.consent import ConsentRegistry
from samvedna.ingest.connectors.replay import connectors_for
from samvedna.ingest.generator import generate_force
from samvedna.ingest.normalise import normalise
from samvedna.ingest.pseudonymise import Pseudonymiser, epoch_for

SALT = "test-salt-value-not-a-real-key"


@pytest.fixture(scope="module")
def force():
    return generate_force(units=2, strength=25, days=200, seed=99)


@pytest.fixture(scope="module")
def pseudonymiser():
    return Pseudonymiser(SALT, on=date(2026, 9, 5))


def enrol_everyone(force, pseudonymiser, *, drop_self_report=()):
    registry = ConsentRegistry()
    for person in force.personnel:
        pid = pseudonymiser.pid(person.service_number)
        scope = tuple(d for d in ALL_DOMAINS if d not in drop_self_report)
        registry.enrol(pid, scope, welfare_contact=True)
    return registry


# ----------------------------------------------------------- pseudonymiser --
def test_the_same_service_number_maps_to_the_same_pid_within_an_epoch(pseudonymiser):
    assert pseudonymiser.pid("UNIT-01-123456") == pseudonymiser.pid("UNIT-01-123456")


def test_different_service_numbers_map_to_different_pids(pseudonymiser):
    assert pseudonymiser.pid("UNIT-01-123456") != pseudonymiser.pid("UNIT-01-123457")


def test_a_pid_contains_no_trace_of_the_service_number(pseudonymiser):
    number = "UNIT-01-123456"
    pid = pseudonymiser.pid(number)
    assert number not in pid
    assert "123456" not in pid
    assert "UNIT" not in pid


def test_rotating_the_salt_changes_every_pid():
    a = Pseudonymiser(SALT, on=date(2026, 1, 15))
    b = Pseudonymiser(SALT, on=date(2026, 9, 5))
    assert a.epoch.index != b.epoch.index
    assert a.pid("UNIT-01-123456") != b.pid("UNIT-01-123456")


def test_a_different_salt_produces_a_different_pid():
    a = Pseudonymiser("salt-one", on=date(2026, 9, 5))
    b = Pseudonymiser("salt-two", on=date(2026, 9, 5))
    assert a.pid("UNIT-01-123456") != b.pid("UNIT-01-123456")


def test_an_empty_salt_refuses_to_run():
    with pytest.raises(ValueError):
        Pseudonymiser("")


def test_the_salt_never_appears_in_the_repr(pseudonymiser):
    assert SALT not in repr(pseudonymiser)


def test_epochs_are_contiguous_and_non_overlapping():
    first = epoch_for(date(2026, 1, 1))
    second = epoch_for(first.ends_on)
    third = epoch_for(first.ends_on.replace(day=first.ends_on.day))
    assert first.index == second.index == third.index
    from datetime import timedelta

    nxt = epoch_for(first.ends_on + timedelta(days=1))
    assert nxt.index == first.index + 1
    assert nxt.starts_on == first.ends_on + timedelta(days=1)


# ------------------------------------------------- the boundary itself --
def test_no_service_number_survives_normalisation(force, pseudonymiser):
    registry = enrol_everyone(force, pseudonymiser)
    results = tuple(c.pull(force.as_of, 200) for c in connectors_for(force))
    report = normalise(results, pseudonymiser, registry.state_for)

    numbers = {p.service_number for p in force.personnel}
    assert report.records
    for record in report.records:
        assert record.pid not in numbers
        blob = f"{record.pid}{record.raw_kind}{record.unit_id}"
        for number in numbers:
            assert number not in blob


def test_every_emitted_pid_is_reachable_only_through_the_pseudonymiser(force, pseudonymiser):
    registry = enrol_everyone(force, pseudonymiser)
    results = tuple(c.pull(force.as_of, 200) for c in connectors_for(force))
    report = normalise(results, pseudonymiser, registry.state_for)

    valid = {pseudonymiser.pid(p.service_number) for p in force.personnel}
    assert {r.pid for r in report.records} <= valid


def test_the_consent_filter_drops_unconsented_domains(force, pseudonymiser):
    registry = enrol_everyone(force, pseudonymiser, drop_self_report=("self_report",))
    results = tuple(c.pull(force.as_of, 200) for c in connectors_for(force))
    report = normalise(results, pseudonymiser, registry.state_for)

    assert report.dropped_no_consent > 0
    assert all(r.domain != "self_report" for r in report.records)


def test_an_unenrolled_person_contributes_nothing(force, pseudonymiser):
    registry = ConsentRegistry()  # nobody enrolled
    results = tuple(c.pull(force.as_of, 200) for c in connectors_for(force))
    report = normalise(results, pseudonymiser, registry.state_for)

    assert report.records == ()
    assert report.dropped_not_enrolled == report.rows_in


def test_a_revoked_person_contributes_nothing_from_the_next_run(force, pseudonymiser):
    registry = enrol_everyone(force, pseudonymiser)
    victim = force.personnel[0]
    pid = pseudonymiser.pid(victim.service_number)
    registry.revoke(pid)

    results = tuple(c.pull(force.as_of, 200) for c in connectors_for(force))
    report = normalise(results, pseudonymiser, registry.state_for)
    assert all(r.pid != pid for r in report.records)


def test_a_failed_connector_excludes_its_domain_and_never_imputes(force, pseudonymiser):
    registry = enrol_everyone(force, pseudonymiser)
    results = tuple(
        c.pull(force.as_of, 200) for c in connectors_for(force, failed=("leave",))
    )
    report = normalise(results, pseudonymiser, registry.state_for)

    assert "leave" in report.degraded_domains
    assert all(r.domain != "leave" for r in report.records)
    assert report.missing_fraction["leave"] == 1.0


def test_a_partial_connector_reports_its_shortfall_rather_than_smoothing_it(
    force, pseudonymiser
):
    registry = enrol_everyone(force, pseudonymiser)
    results = tuple(
        c.pull(force.as_of, 200) for c in connectors_for(force, drop={"leave": 0.4})
    )
    report = normalise(results, pseudonymiser, registry.state_for)
    assert report.missing_fraction["leave"] == pytest.approx(0.4, abs=0.01)
    assert "leave" in report.degraded_domains
