"""Phase 8 ship gate: a full nightly run, end to end, with every degradation path.

These tests run the real pipeline over a real synthetic force. They are slower
than the L3 tests on purpose — this is the layer where wiring goes wrong, and
wiring is not something a pure unit test can catch.
"""
from __future__ import annotations

import pytest

from samvedna.analytics.reviewers.confounder_check import ConfounderCheck
from samvedna.analytics.reviewers.panel import Panel
from samvedna.analytics.reviewers.risk_advocate import RiskAdvocate
from samvedna.analytics.reviewers.welfare_context import WelfareContext
from samvedna.config.weights import ALL_DOMAINS
from samvedna.core.machine import IllegalTransition
from samvedna.disclosure.audit import Ledger
from samvedna.disclosure.consent import ConsentRegistry
from samvedna.ingest.connectors.replay import connectors_for
from samvedna.ingest.generator import generate_force
from samvedna.ingest.pseudonymise import Pseudonymiser
from samvedna.pipeline.dag import run_nightly

SALT = "nightly-test-salt"


class Broken:
    def __init__(self, name):
        self.name = name

    def review(self, ctx):
        raise RuntimeError("disabled")


def panel_without(name=None):
    reviewers = {
        "risk_advocate": RiskAdvocate(),
        "confounder_check": ConfounderCheck(),
        "welfare_context": WelfareContext(),
    }
    if name:
        reviewers[name] = Broken(name)
    return Panel(tuple(reviewers.values()))


@pytest.fixture(scope="module")
def world():
    force = generate_force(units=3, strength=35, seed=4242)
    ps = Pseudonymiser(SALT, on=force.as_of)
    return force, ps


def fresh_registry(force, ps):
    registry = ConsentRegistry()
    for person in force.personnel:
        registry.enrol(ps.pid(person.service_number), ALL_DOMAINS, welfare_contact=True)
    return registry


def _or(value, default_factory):
    """`value or default()` is wrong here: an empty Ledger is falsy."""
    return default_factory() if value is None else value


def go(force, ps, **kw):
    return run_nightly(
        connectors=connectors_for(force, drop=kw.pop("drop", None),
                                  failed=kw.pop("failed", ())),
        pseudonymiser=ps,
        consent=_or(kw.pop("consent", None), lambda: fresh_registry(force, ps)),
        ledger=_or(kw.pop("ledger", None), Ledger),
        as_of=force.as_of,
        panel=_or(kw.pop("panel", None), panel_without),
        model_dir=kw.pop("model_dir", "/nonexistent"),
        **kw,
    )


# ------------------------------------------------------------ the full run --
def test_a_full_nightly_run_completes_and_produces_a_funnel(world):
    record = go(*world)
    assert record.status == "COMPLETE"
    assert record.screened > 0
    assert record.deviating > 0
    assert record.screened >= record.deviating >= record.escalated
    assert "screened" in record.headline and "escalated" in record.headline


def test_every_stage_is_recorded_with_timings_and_row_counts(world):
    record = go(*world)
    names = [s.name for s in record.stages]
    assert names == [
        "1-ingest", "2-protect", "3-features", "4-deviate", "5-score",
        "6-review", "7-gate",
    ]
    assert all(s.seconds >= 0 for s in record.stages)
    assert record.stages[0].rows_out > 0


def test_the_run_record_contains_no_identity_anywhere(world):
    """It is meant to be safe to hand to an auditor whole."""
    force, ps = world
    record = go(force, ps)
    numbers = {p.service_number for p in force.personnel}
    blob = str(record.to_summary()) + "".join(c.pid + c.unit_id for c in record.cases)
    for number in numbers:
        assert number not in blob


def test_every_pid_ends_in_a_legal_terminal_state(world):
    record = go(*world)
    legal = {"ESCALATED", "MONITORED", "CLEARED"}
    assert {c.state for c in record.cases} <= legal


def test_an_illegal_state_transition_raises_rather_than_warning():
    from samvedna.core.machine import assert_transition

    with pytest.raises(IllegalTransition):
        assert_transition("SCORED", "ESCALATED")


def test_the_ledger_records_a_verdict_for_every_deviating_pid(world):
    force, ps = world
    ledger = Ledger()
    record = go(force, ps, ledger=ledger)
    verdicts = ledger.for_action("verdict.recorded")
    assert len(verdicts) == record.deviating
    assert ledger.verify()[0]
    assert ledger.for_action("run.started")
    assert ledger.for_action("run.completed") or ledger.for_action("run.partial")


def test_the_caseload_is_escalate_only_and_ranked_by_composite(world):
    record = go(*world)
    caseload = record.caseload()
    assert all(c.verdict.names_a_person for c in caseload)
    composites = [c.composite for c in caseload if c.decision == "ESCALATE"]
    assert composites == sorted(composites, reverse=True)


def test_monitor_cases_carry_a_mind_change_and_name_nobody(world):
    record = go(*world)
    monitored = record.monitored()
    assert monitored
    for case in monitored:
        assert not case.verdict.names_a_person
        assert case.verdict.recommended == ()
        assert case.verdict.mind_change


# ---------------------------------------------------- degradation (PART 8.8) --
def test_a_partial_connector_marks_the_run_partial_and_says_which(world):
    record = go(*world, drop={"leave": 0.45})
    assert record.status == "PARTIAL"
    assert "leave" in record.degraded_connectors
    assert record.stages[0].status == "partial"


def test_a_failed_connector_excludes_its_domain_and_never_imputes(world):
    record = go(*world, failed=("leave",))
    assert "leave" in record.degraded_connectors
    for case in record.cases:
        if case.verdict:
            assert "leave" not in case.verdict.gates["evidence"].inputs["domains"]


def test_a_degradation_never_produces_MORE_escalations_than_a_clean_run(world):
    """The invariant: every degradation moves the system toward saying less."""
    clean = go(*world).escalated
    for kw in ({"drop": {"leave": 0.45}}, {"failed": ("workload",)},
               {"panel": panel_without("welfare_context")}):
        assert go(*world, **kw).escalated <= clean, kw


def test_without_the_confounder_check_the_run_produces_no_escalate_at_all(world):
    """§8.12 criterion 5, on a real run over a real force."""
    record = go(*world, panel=panel_without("confounder_check"))
    assert record.escalated == 0
    assert record.escalation_frozen
    assert "confounder_check" in record.unavailable_reviewers
    assert "heard only the case for concern" in record.freeze_reason
    assert record.count("MONITOR") > 0, "MONITOR is still recorded while frozen"


def test_model_drift_freezes_escalation_system_wide_and_logs_it(world):
    force, ps = world
    ledger = Ledger()
    record = go(force, ps, ledger=ledger, drift_exceeded=True)
    assert record.escalated == 0
    assert record.escalation_frozen
    assert "drift" in record.freeze_reason
    assert ledger.for_action("model.frozen")


def test_a_frozen_run_still_computes_and_records_every_gate(world):
    """Escalation is withheld; the arithmetic is not skipped."""
    record = go(*world, drift_exceeded=True)
    passing_all = [
        c for c in record.cases
        if c.verdict and all(g.passed for g in c.verdict.gates.values())
    ]
    assert passing_all, "some case should have passed all four gates"
    assert all(c.decision == "MONITOR" for c in passing_all)


# ------------------------------------------------------------- the model --
@pytest.mark.slow
def test_the_model_never_changes_who_is_named(world):
    """The precise claim, verified on a real run.

    A missing model does change some verdicts from MONITOR to NO_FLAG, because
    SHAP driver names widen what the intervention playbook can match. Neither
    outcome names anybody, and the set of people who ARE named is identical —
    which is the property that has to hold.
    """
    from pathlib import Path

    model_dir = Path(__file__).resolve().parent.parent.parent / "artefacts" / "models"
    if not (model_dir / "tabular.pkl").exists():
        pytest.skip("no trained model; run tools/train_tabular.py")

    without = go(*world, model_dir="/nonexistent")
    with_model = go(*world, model_dir=str(model_dir))

    assert {c.pid for c in without.caseload()} == {c.pid for c in with_model.caseload()}


def test_the_run_completes_with_no_model_at_all(world):
    record = go(*world, model_dir="/nonexistent")
    assert record.status == "COMPLETE"
    assert record.model_version == "unavailable"
    assert record.stages[4].status == "partial"
    assert "gates do not require one" in record.stages[4].detail


# ---------------------------------------------------------------- consent --
def test_a_revoked_pid_does_not_appear_in_the_next_run(world):
    force, ps = world
    registry = fresh_registry(force, ps)
    victim = ps.pid(force.personnel[0].service_number)
    registry.revoke(victim)

    record = go(force, ps, consent=registry)
    assert victim not in {c.pid for c in record.cases}


def test_a_person_who_refuses_welfare_contact_is_analysed_but_never_surfaced(world):
    force, ps = world
    registry = ConsentRegistry()
    for person in force.personnel:
        registry.enrol(ps.pid(person.service_number), ALL_DOMAINS, welfare_contact=False)

    record = go(force, ps, consent=registry)
    assert record.deviating > 0, "they are still analysed"
    assert record.escalated == 0, "and never surfaced"


def test_reproducibility_the_same_inputs_give_the_same_verdicts(world):
    force, ps = world
    a, b = go(force, ps), go(force, ps)
    assert {c.pid: c.decision for c in a.cases} == {c.pid: c.decision for c in b.cases}
    assert a.config_version == b.config_version


# ------------------------- horizon and rhythm reach the officer -------------
@pytest.mark.slow
def test_a_run_carries_a_horizon_when_a_survival_model_exists(world):
    """"Risk by when" is what makes a case schedulable. A welfare officer plans
    a week; a score of 0.71 does not tell them which week."""
    from pathlib import Path

    model_dir = Path(__file__).resolve().parent.parent.parent / "artefacts" / "models"
    if not (model_dir / "survival.pkl").exists():
        pytest.skip("no survival model; run tools/train_tabular.py")

    record = go(*world, model_dir=str(model_dir))
    scored = [c for c in record.cases if c.verdict and c.horizon]
    assert scored, "no case carried a horizon"
    for case in scored:
        values = [case.horizon[d] for d in sorted(case.horizon)]
        assert values == sorted(values), "cumulative risk must be monotone"
        assert all(0.0 <= v <= 1.0 for v in values)
        assert case.horizon_phrase


def test_roster_rhythm_is_computed_with_or_without_a_model(world):
    """Rhythm is arithmetic over the duty series, not a model output, so a
    missing model must not take it with it."""
    record = go(*world, model_dir="/nonexistent")
    assert record.model_version == "unavailable"
    with_rhythm = [c for c in record.cases if c.rhythm_phrase]
    assert with_rhythm, "rhythm should survive a missing model"
    for case in with_rhythm:
        assert "day" in case.rhythm_phrase or "no duty days" in case.rhythm_phrase


def test_a_horizon_never_changes_a_verdict(world):
    """A three-day horizon does not lower a threshold or shorten a window. The
    only path that bypasses gates is the acute override, and that is triggered
    by an instrument."""
    from pathlib import Path

    model_dir = Path(__file__).resolve().parent.parent.parent / "artefacts" / "models"
    if not (model_dir / "survival.pkl").exists():
        pytest.skip("no survival model")

    without = go(*world, model_dir="/nonexistent")
    with_models = go(*world, model_dir=str(model_dir))
    assert {c.pid for c in without.caseload()} == {c.pid for c in with_models.caseload()}


def test_the_run_record_summary_still_carries_no_identity(world):
    """The horizon and rhythm fields must not have smuggled one in."""
    force, ps = world
    record = go(force, ps, model_dir="/nonexistent")
    numbers = {p.service_number for p in force.personnel}
    blob = str(record.to_summary()) + "".join(
        c.pid + c.unit_id + c.rhythm_phrase + c.horizon_phrase for c in record.cases
    )
    for number in numbers:
        assert number not in blob
