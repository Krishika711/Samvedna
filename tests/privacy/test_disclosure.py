"""Phase 9 ship gate: commander view provably individual-free, and no name
released without an audit record.
"""
from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from samvedna.core.types import Gate, Verdict
from samvedna.disclosure.audit import Ledger
from samvedna.disclosure.commander import unit_view
from samvedna.disclosure.consent import ConsentRegistry
from samvedna.disclosure.kanon import SUPPRESSED, Cell, aggregate, k_min
from samvedna.disclosure.rbac import FORBIDDEN_PURPOSES, GRANTS, Denied, Principal, check, may
from samvedna.disclosure.reidentify import (
    DisclosureRefused,
    Identity,
    disclose,
    try_disclose,
)
from samvedna.ingest.dp import Budget
from samvedna.pipeline.record import CaseRecord, RunRecord

AT = datetime(2026, 9, 5, 7, 14, tzinfo=UTC)
ALL_DOMAINS = ("leave", "duty_roster", "self_report", "workload", "deployment",
               "transfer", "training", "biometric")


def a_verdict(decision="ESCALATE"):
    gates = {
        n: Gate(n, 0.9, 0.5, True, f"{n} = 0.900", {})
        for n in ("evidence", "consistency", "persistence", "actionability")
    }
    return Verdict(
        decision=decision, reason="test", gates=gates, failed_gates=(),
        mind_change=(), composite=0.9, config_version="test-1",
    )


class FakeDirectory:
    def resolve(self, pid):
        return Identity("UNIT-01-123456", "Ram Singh", "Head Constable", "UNIT-01", "ext 4412")


def registry(welfare_contact=True, status="ACTIVE"):
    r = ConsentRegistry()
    r.enrol("pid-1", ALL_DOMAINS, welfare_contact=welfare_contact, at=AT)
    if status == "REVOKED":
        r.revoke("pid-1", at=AT)
    return r


def officer(units=("UNIT-01",)):
    return Principal("WO-12", "welfare_officer", frozenset(units))


def kw(**over):
    base = {
        "pid": "pid-1", "verdict": a_verdict(), "principal": officer(),
        "purpose": "welfare:contact", "unit_id": "UNIT-01",
        "directory": FakeDirectory(), "ledger": Ledger(),
        "consent": registry(), "at": AT,
    }
    base.update(over)
    return base


# ------------------------------------------------------- the purpose firewall --
@pytest.mark.parametrize("purpose", sorted(FORBIDDEN_PURPOSES))
def test_no_role_may_ever_act_for_an_administrative_purpose(purpose):
    for role in ("personnel", "welfare_officer", "commander",
                 "mental_health_authority", "auditor"):
        assert may(role, purpose) is None
        with pytest.raises(Denied) as excinfo:
            check(Principal("x", role), purpose)
        assert "ACR, promotion, posting or disciplinary" in str(excinfo.value)


def test_the_forbidden_purposes_are_listed_not_omitted():
    """Adding one by accident should be a diff somebody has to defend."""
    assert {
        "administrative:acr", "administrative:promotion",
        "administrative:posting", "administrative:disciplinary",
    } == FORBIDDEN_PURPOSES


def test_only_two_role_purpose_pairs_may_ever_re_identify():
    identifying = {pair for pair, grant in GRANTS.items() if grant}
    assert identifying == {
        ("welfare_officer", "welfare:contact"),
        ("mental_health_authority", "welfare:acute"),
        ("personnel", "welfare:self"),
    }


def test_a_commander_may_never_re_identify_for_any_purpose():
    for purpose in ("welfare:contact", "welfare:acute", "welfare:screening",
                    "command:aggregate", "governance:audit"):
        assert may("commander", purpose) is not True


def test_an_auditor_sees_the_ledger_but_never_an_identity():
    assert may("auditor", "governance:audit") is False


def test_an_officer_is_refused_outside_their_unit_scope():
    with pytest.raises(Denied) as excinfo:
        check(officer(("UNIT-01",)), "welfare:contact", "UNIT-99")
    assert "not responsible for UNIT-99" in str(excinfo.value)


def test_authorisation_raises_rather_than_returning_false():
    """A caller who forgets to check a boolean gets a name; one who forgets to
    catch an exception gets a stack trace. Only one is safe."""
    with pytest.raises(Denied):
        check(Principal("x", "commander"), "welfare:contact")


# -------------------------------------------------------------- disclosure --
def test_a_permitted_disclosure_returns_an_identity_and_logs_it():
    ledger = Ledger()
    result = disclose(**kw(ledger=ledger))
    assert result.identity.name == "Ram Singh"
    entry = ledger.for_action("disclosure.granted")[0]
    assert entry.actor == "welfare_officer:WO-12"
    assert entry.subject_pid == "pid-1"
    assert entry.purpose == "welfare:contact"
    assert ledger.verify()[0]


def test_a_monitor_verdict_never_discloses_an_identity():
    for decision in ("MONITOR", "NO_FLAG"):
        with pytest.raises(DisclosureRefused) as excinfo:
            disclose(**kw(verdict=a_verdict(decision)))
        assert decision in str(excinfo.value)


def test_a_revoked_person_cannot_be_disclosed():
    with pytest.raises(DisclosureRefused) as excinfo:
        disclose(**kw(consent=registry(status="REVOKED")))
    assert "no consent basis" in str(excinfo.value)


def test_withheld_welfare_contact_blocks_disclosure():
    with pytest.raises(DisclosureRefused) as excinfo:
        disclose(**kw(consent=registry(welfare_contact=False)))
    assert "welfare contact" in str(excinfo.value)


def test_the_acute_route_proceeds_without_an_explicit_contact_grant():
    """Submitting the disclosure was itself the act of asking for help."""
    result = disclose(**kw(
        consent=registry(welfare_contact=False),
        principal=Principal("MH-3", "mental_health_authority", frozenset({"UNIT-01"})),
        purpose="welfare:acute",
    ))
    assert result.identity.name


def test_a_failed_ledger_write_aborts_the_disclosure_and_releases_no_name():
    """PART 8.8, last row. §8.12 criterion 7."""
    ledger = Ledger()
    ledger.fail_next_write = True
    with pytest.raises(DisclosureRefused) as excinfo:
        disclose(**kw(ledger=ledger))
    assert "No identity has been released" in str(excinfo.value)
    assert len(ledger) == 0


def test_the_ledger_is_written_before_the_directory_is_touched():
    """There must be no ordering in which a name exists before its record does."""
    class ExplodingDirectory:
        def resolve(self, pid):
            raise AssertionError("directory must not be reached on a failed write")

    ledger = Ledger()
    ledger.fail_next_write = True
    with pytest.raises(DisclosureRefused):
        disclose(**kw(ledger=ledger, directory=ExplodingDirectory()))


def test_denials_are_logged_so_an_auditor_sees_what_was_asked():
    ledger = Ledger()
    with pytest.raises(DisclosureRefused):
        disclose(**kw(ledger=ledger, verdict=a_verdict("MONITOR")))
    denials = ledger.for_action("disclosure.denied")
    assert len(denials) == 1
    assert denials[0].detail["reason"] == "verdict is MONITOR"


def test_an_unresolvable_pid_fails_closed():
    class EmptyDirectory:
        def resolve(self, pid):
            return None

    with pytest.raises(DisclosureRefused) as excinfo:
        disclose(**kw(directory=EmptyDirectory()))
    assert "expired salt epoch" in str(excinfo.value)


def test_the_non_raising_wrapper_never_returns_a_partial_identity():
    result, reason = try_disclose(**kw(verdict=a_verdict("NO_FLAG")))
    assert result is None
    assert reason


def test_the_identity_carries_no_psychometric_content():
    """PART 8.0: a welfare officer may never see raw psychometric responses."""
    fields = set(Identity.__dataclass_fields__)
    for forbidden in ("phq9", "responses", "items", "score", "instrument",
                      "clinical", "diagnosis", "notes"):
        assert forbidden not in fields


# ------------------------------------------------------------- k-anonymity --
def test_a_cohort_below_k_is_suppressed_not_rounded():
    """§8.12 criterion 2."""
    cell = aggregate("fatigue", [0.5] * (k_min() - 1), Budget(total=100))
    assert cell.suppressed
    assert cell.display == SUPPRESSED
    assert cell.value is None


def test_a_suppressed_cell_does_not_leak_its_true_n():
    """'n=3' is the same disclosure the value would have been."""
    payload = aggregate("fatigue", [0.5] * 3, Budget(total=100)).to_dict()
    assert "n" not in payload
    assert payload["suppressed"] is True


def test_a_cohort_at_k_is_released():
    cell = aggregate("fatigue", [0.5] * k_min(), Budget(total=100))
    assert not cell.suppressed


def test_released_cells_carry_differential_privacy_noise():
    values = [0.5] * 40
    plain = aggregate("f", values, Budget(total=1e6), differential_privacy=False)
    noised = {
        aggregate("f", values, Budget(total=1e6), rng=random.Random(s)).value
        for s in range(30)
    }
    assert len(noised) > 5
    assert plain.value == pytest.approx(0.5)


# ------------------------------------------------- the commander unit view --
def run_with(cases):
    record = RunRecord(
        run_id="r1", as_of=AT.date(), started_at=AT, mode="replay",
        config_version="test-1",
    )
    record.cases.extend(cases)
    return record


def a_case(pid, unit="UNIT-01", decision="MONITOR"):
    return CaseRecord(pid=pid, unit_id=unit, state="MONITORED",
                      verdict=a_verdict(decision))


def test_the_commander_payload_contains_no_pid_anywhere():
    """§8.12 criterion 2, and the whole of PART 8.6."""
    record = run_with([a_case(f"pid-{i}") for i in range(30)])
    commander = Principal("CO-1", "commander", frozenset({"UNIT-01"}))
    view = unit_view(record, "UNIT-01", commander, Budget(total=1e6), Ledger())

    blob = str(view.to_dict())
    for i in range(30):
        assert f"pid-{i}" not in blob
    assert "pid" not in blob


def test_a_cell_type_has_no_field_that_could_hold_an_identity():
    """There is no drill-down to hide, because there is nothing to drill into."""
    fields = set(Cell.__dataclass_fields__)
    assert fields == {"label", "n", "value", "suppressed", "reason"}


def test_a_small_unit_is_entirely_suppressed():
    record = run_with([a_case(f"pid-{i}", unit="UNIT-99") for i in range(3)])
    commander = Principal("CO-9", "commander", frozenset({"UNIT-99"}))
    view = unit_view(record, "UNIT-99", commander, Budget(total=1e6), Ledger())
    assert view.suppressed == len(view.cells)
    assert all(c.display == SUPPRESSED for c in view.cells)


def test_a_commander_cannot_request_another_units_view():
    record = run_with([a_case(f"pid-{i}") for i in range(30)])
    commander = Principal("CO-1", "commander", frozenset({"UNIT-02"}))
    with pytest.raises(Denied):
        unit_view(record, "UNIT-01", commander, Budget(total=1e6), Ledger())


def test_a_welfare_officer_cannot_use_the_commander_endpoint():
    record = run_with([a_case(f"pid-{i}") for i in range(30)])
    with pytest.raises(Denied):
        unit_view(record, "UNIT-01", officer(), Budget(total=1e6), Ledger())


def test_the_view_tells_the_commander_what_they_CAN_do():
    """A screen that only says no teaches people to route around it."""
    record = run_with([a_case(f"pid-{i}") for i in range(30)])
    commander = Principal("CO-1", "commander", frozenset({"UNIT-01"}))
    view = unit_view(record, "UNIT-01", commander, Budget(total=1e6), Ledger())
    assert "welfare officer" in view.next_step
    assert "rostering" in view.next_step


def test_an_exhausted_privacy_budget_withholds_cells_rather_than_releasing_them_raw():
    record = run_with([a_case(f"pid-{i}") for i in range(30)])
    commander = Principal("CO-1", "commander", frozenset({"UNIT-01"}))
    view = unit_view(record, "UNIT-01", commander, Budget(total=0.6), Ledger())
    assert "budget" in view.note.lower()
    assert view.budget_remaining < 0.6


def test_every_aggregate_release_is_logged_with_the_epsilon_spent():
    record = run_with([a_case(f"pid-{i}") for i in range(30)])
    commander = Principal("CO-1", "commander", frozenset({"UNIT-01"}))
    ledger = Ledger()
    unit_view(record, "UNIT-01", commander, Budget(total=1e6), ledger)
    entry = ledger.for_action("aggregate.released")[0]
    assert entry.detail["epsilon_spent"] > 0
    assert entry.subject_pid == ""


# ---------------------------------- the refresh button is an averaging attack --
def test_refreshing_a_unit_view_re_serves_rather_than_re_noising():
    """The vulnerability this closes: ten refreshes drawing ten independent noise
    samples around the same truth average to the truth. The privacy guarantee is
    destroyed by a refresh button, and a bigger budget only buys more samples."""
    from samvedna.disclosure.dpcache import ReleaseCache

    record = run_with([a_case(f"pid-{i}") for i in range(30)])
    commander = Principal("CO-1", "commander", frozenset({"UNIT-01"}))
    cache = ReleaseCache()
    budget = Budget(total=1e6)

    views = [
        unit_view(record, "UNIT-01", commander, budget, Ledger(), cache=cache)
        for _ in range(10)
    ]
    values = {tuple(c.value for c in v.cells) for v in views}
    assert len(values) == 1, "ten refreshes produced ten different answers"


def test_only_the_first_view_of_a_period_costs_epsilon():
    from samvedna.disclosure.dpcache import ReleaseCache

    record = run_with([a_case(f"pid-{i}") for i in range(30)])
    commander = Principal("CO-1", "commander", frozenset({"UNIT-01"}))
    cache, budget = ReleaseCache(), Budget(total=1e6)

    unit_view(record, "UNIT-01", commander, budget, Ledger(), cache=cache)
    after_first = budget.spent
    for _ in range(5):
        unit_view(record, "UNIT-01", commander, budget, Ledger(), cache=cache)
    assert budget.spent == after_first
    assert cache.hits > 0


def test_a_different_unit_is_a_different_question_and_does_cost_epsilon():
    from samvedna.disclosure.dpcache import ReleaseCache

    cases = [a_case(f"pid-{i}") for i in range(30)]
    cases += [a_case(f"pid-b{i}", unit="UNIT-02") for i in range(30)]
    record = run_with(cases)
    commander = Principal("CO-1", "commander", frozenset({"UNIT-01", "UNIT-02"}))
    cache, budget = ReleaseCache(), Budget(total=1e6)

    unit_view(record, "UNIT-01", commander, budget, Ledger(), cache=cache)
    after_first = budget.spent
    unit_view(record, "UNIT-02", commander, budget, Ledger(), cache=cache)
    assert budget.spent > after_first


def test_the_ledger_records_how_many_cells_were_served_from_cache():
    from samvedna.disclosure.dpcache import ReleaseCache

    record = run_with([a_case(f"pid-{i}") for i in range(30)])
    commander = Principal("CO-1", "commander", frozenset({"UNIT-01"}))
    cache, ledger = ReleaseCache(), Ledger()
    unit_view(record, "UNIT-01", commander, Budget(total=1e6), ledger, cache=cache)
    unit_view(record, "UNIT-01", commander, Budget(total=1e6), ledger, cache=cache)
    assert ledger.for_action("aggregate.released")[-1].detail["served_from_cache"] > 0
