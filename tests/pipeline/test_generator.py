"""Phase 2 ship gate: the generator produces realistic roster/leave/deployment
sequences — not white noise dressed up as service records.

The distinction matters. A persistence gate scored against independent daily
noise looks far better than it deserves, because the 7-, 30- and 90-day windows
all see the same noise and agree with each other. These tests assert the
sequences actually have the structure the gate is meant to be tested against.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta

import pytest

from samvedna.config.weights import CONNECTOR_DOMAINS
from samvedna.ingest.generator import generate_force


@pytest.fixture(scope="module")
def force():
    return generate_force(units=3, strength=40, days=270, seed=26186)


def test_the_same_seed_produces_the_same_force():
    a = generate_force(units=2, strength=10, days=90, seed=7)
    b = generate_force(units=2, strength=10, days=90, seed=7)
    assert a.records == b.records
    assert a.personnel == b.personnel


def test_a_different_seed_produces_a_different_force():
    a = generate_force(units=2, strength=10, days=90, seed=7)
    b = generate_force(units=2, strength=10, days=90, seed=8)
    assert a.records != b.records


def test_every_record_is_normalised_into_the_unit_interval(force):
    assert all(0.0 <= r.value <= 1.0 for r in force.records)


def test_records_only_exist_for_consented_domains(force):
    """Consent is decided per person, and the generator honours it at source."""
    for record in force.records:
        assert record.domain in record.consent_scope


def test_some_personnel_decline_the_self_assessment_channel(force):
    consented = {p.service_number for p in force.personnel}
    have_self_report = {r.pid for r in force.records if r.domain == "self_report"}
    assert 0 < len(have_self_report) < len(consented), (
        "a force where everybody self-reports is not a force worth designing for"
    )


def test_duty_moves_in_blocks_not_daily_noise(force):
    """Rosters are planned in blocks. Count runs of identical values: white noise
    would produce almost none."""
    series = defaultdict(list)
    for record in sorted(force.records, key=lambda r: (r.pid, r.observed_at)):
        if record.domain == "duty_roster":
            series[record.pid].append(record.value)

    run_lengths = []
    for values in series.values():
        run = 1
        for a, b in zip(values, values[1:], strict=False):
            if a == b:
                run += 1
            else:
                run_lengths.append(run)
                run = 1
        run_lengths.append(run)
    mean_run = sum(run_lengths) / len(run_lengths)
    assert mean_run > 3.0, f"duty roster looks like daily noise (mean run {mean_run:.1f})"


def test_deployments_are_contiguous_tours(force):
    by_pid = defaultdict(list)
    for record in sorted(force.records, key=lambda r: (r.pid, r.observed_at)):
        if record.domain == "deployment":
            by_pid[record.pid].append(record.value)

    deployed_runs = []
    for values in by_pid.values():
        run = 0
        for v in values:
            if v > 0.5:
                run += 1
            elif run:
                deployed_runs.append(run)
                run = 0
        if run:
            deployed_runs.append(run)
    assert deployed_runs, "nobody was deployed at all"
    mean_tour = sum(deployed_runs) / len(deployed_runs)
    assert mean_tour > 14, f"tours average {mean_tour:.0f} days; that is not a deployment"


def test_self_assessment_is_sparse_because_it_is_an_event_not_a_stream(force):
    counts = Counter(r.domain for r in force.records)
    assert counts["self_report"] < counts["duty_roster"]


def test_one_unit_is_under_operational_surge_and_the_others_are_not(force):
    surged = [u for u in force.units if u.surge_days]
    assert len(surged) == 1
    assert len(surged[0].surge_days) > 30


def test_the_surge_lifts_the_whole_unit_together(force):
    """This is what the op-tempo confounder has to be able to see: on surge days
    the unit's operational domains move together, for everybody in it."""
    surged = next(u for u in force.units if u.surge_days)
    calm = next(u for u in force.units if not u.surge_days)

    def mean_on_surge_days(unit_id):
        vals = [
            r.value for r in force.records
            if r.unit_id == unit_id
            and r.domain == "duty_roster"
            and r.observed_at.date() in surged.surge_days
        ]
        return sum(vals) / len(vals)

    assert mean_on_surge_days(surged.unit_id) > mean_on_surge_days(calm.unit_id) + 0.10


def test_strain_is_a_long_right_tail_so_the_positive_class_stays_rare(force):
    strains = sorted(p.strain for p in force.personnel)
    median = strains[len(strains) // 2]
    assert median < 0.35, "most personnel must be fine, or the problem is not real"
    assert max(strains) > 0.6, "somebody has to be under real strain"


def test_higher_strain_shows_up_in_the_operational_record(force):
    """Not a strong effect, and it should not be. If strain were legible from a
    single domain, none of the four gates would be needed."""
    by_pid = defaultdict(list)
    for record in force.records:
        if record.domain == "workload":
            by_pid[record.pid].append(record.value)
    strain = {p.service_number: p.strain for p in force.personnel}

    ranked = sorted(by_pid, key=lambda pid: strain[pid])
    low = ranked[: len(ranked) // 4]
    high = ranked[-len(ranked) // 4 :]

    def mean(pids):
        vals = [v for pid in pids for v in by_pid[pid]]
        return sum(vals) / len(vals)

    assert mean(high) > mean(low)


def test_every_connector_domain_is_represented(force):
    present = {r.domain for r in force.records}
    assert present == set(CONNECTOR_DOMAINS)


def test_the_generator_never_produces_a_voice_record():
    """Voice comes from a session a person chose to start, in front of them.
    There is no records system to pull it from and there must not be one — a
    connector that could fetch somebody's voice overnight is a surveillance
    capability, whatever tier it is given."""
    from samvedna.config.weights import ALL_DOMAINS, SESSION_DOMAINS

    small = generate_force(units=1, strength=6, days=200, seed=3)
    assert "voice" in ALL_DOMAINS
    assert "voice" in SESSION_DOMAINS
    assert all(r.domain != "voice" for r in small.records)


def test_the_window_covers_the_baseline_plus_the_scoring_period(force):
    days = {r.observed_at.date() for r in force.records}
    assert max(days) == force.as_of
    assert (max(days) - min(days)) >= timedelta(days=180)


def test_no_service_number_looks_like_a_real_identifier(force):
    """Synthetic, and obviously so. A generator that produced plausible real
    service numbers would be a liability the first time a file leaked."""
    for person in force.personnel:
        assert person.service_number.startswith("UNIT-")
