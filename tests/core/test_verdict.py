"""Verdict precedence, the safety override, and the composite that decides nothing."""
from __future__ import annotations

import pytest
from tests.conftest import case, consent, deviation, unit

from samvedna.core.gates import composite, evaluate
from samvedna.core.interventions import BY_CODE
from samvedna.core.verdict import decide

SUSTAINED = {7: 1.0, 30: 1.0, 90: 0.9}
BLIP = {7: 1.0, 30: 7 / 30, 90: 7 / 90}


def escalating():
    return case(
        deviation("self_report", breach=SUSTAINED),
        deviation("leave", breach=SUSTAINED),
        deviation("duty_roster", breach=SUSTAINED),
    )


# ------------------------------------------------------------- precedence --
def test_all_gates_pass_gives_escalate():
    v = decide(escalating())
    assert v.decision == "ESCALATE"
    assert v.failed_gates == ()
    assert v.recommended, "an ESCALATE must carry a recommended action"


def test_consent_absent_for_all_domains_beats_every_other_reason():
    """Checked first: irrecoverable before recoverable. The person is not
    described as 'not yet sustained', which would invite waiting for them."""
    v = decide(
        case(
            deviation("self_report", breach=BLIP),
            consent_state=consent(scope=(), status="REVOKED"),
        )
    )
    assert v.decision == "NO_FLAG"
    assert "consent" in v.reason


def test_actionability_failure_beats_persistence_failure():
    v = decide(
        case(
            deviation("leave", breach=BLIP),
            deviation("duty_roster", breach=BLIP),
            consent_state=consent(welfare_contact=False),
        )
    )
    assert v.decision == "NO_FLAG"
    assert "action" in v.reason


def test_persistence_failure_gives_monitor_not_no_flag():
    v = decide(
        case(
            deviation("self_report", breach=BLIP),
            deviation("leave", breach=BLIP),
            deviation("duty_roster", breach=BLIP),
        )
    )
    assert v.decision == "MONITOR"
    assert v.reason == "not yet sustained"


def test_confounded_evidence_gives_monitor_and_names_nobody():
    """The demo case: sustained, multi-domain, but the unit is deployed."""
    v = decide(
        case(
            deviation("self_report", breach=SUSTAINED),
            deviation("leave", breach=SUSTAINED),
            deviation("duty_roster", breach=SUSTAINED),
            unit_state=unit(
                deviating={"self_report": 0.45, "leave": 0.52, "duty_roster": 0.61}
            ),
        )
    )
    assert v.decision == "MONITOR"
    assert v.gates["consistency"].value == pytest.approx(0.694, abs=5e-4)
    assert not v.names_a_person
    assert v.recommended == (), "MONITOR must not carry a recommendation"
    assert v.mind_change, "MONITOR must say what would change its mind"


def test_thin_evidence_gives_monitor():
    v = decide(case(deviation("leave", breach=SUSTAINED)))
    assert v.decision == "MONITOR"


def test_escalation_freeze_downgrades_to_monitor():
    v = decide(escalating(), escalation_frozen=True)
    assert v.decision == "MONITOR"
    assert "frozen" in v.reason
    assert all(g.passed for g in v.gates.values())


# --------------------------------------------------------- safety override --
def test_acute_item_bypasses_persistence_and_evidence():
    v = decide(case(deviation("self_report", breach=BLIP), acute=("item_9",)))
    assert v.decision == "IMMEDIATE_ESCALATE"
    assert v.override
    assert v.override_reason
    assert not v.gates["persistence"].passed, "the gates it bypassed are still recorded"


def test_acute_routes_to_a_mental_health_authority_never_the_unit():
    v = decide(case(deviation("self_report", breach=BLIP), acute=("item_9",)))
    assert v.recommended[0].authority == "mental_health"
    assert v.recommended[0].code == "MH-URGENT"


def test_clinician_concern_also_overrides():
    v = decide(case(deviation("leave", breach=BLIP), clinician_concern=True))
    assert v.decision == "IMMEDIATE_ESCALATE"
    assert v.override


def test_override_is_triggered_by_the_instrument_not_a_model_score():
    from datetime import UTC, datetime

    from samvedna.core.types import InstrumentResponse, RiskAssessment
    from samvedna.core.verdict import acute_items_in

    terrifying_model = RiskAssessment(
        pid="pid-test", score=0.999, horizon_days=60,
        drivers=(("self_report", 0.9),), model_version="v1",
    )
    v = decide(case(deviation("leave", breach=BLIP), risk=terrifying_model))
    assert v.decision != "IMMEDIATE_ESCALATE", "a score must never trigger the override"

    response = InstrumentResponse(
        pid="pid-test", instrument="PHQ9", taken_at=datetime(2026, 9, 4, tzinfo=UTC),
        items={"item_1": 1, "item_9": 1}, total=11, cutoff=10,
    )
    assert acute_items_in(response) == ("item_9",)


def test_a_zero_item_9_does_not_trigger_the_override():
    from datetime import UTC, datetime

    from samvedna.core.types import InstrumentResponse
    from samvedna.core.verdict import acute_items_in

    response = InstrumentResponse(
        pid="pid-test", instrument="PHQ9", taken_at=datetime(2026, 9, 4, tzinfo=UTC),
        items={"item_1": 3, "item_9": 0}, total=20, cutoff=10,
    )
    assert acute_items_in(response) == ()


# ---------------------------------------------------------- the composite --
def test_composite_is_display_only_and_changes_no_decision():
    ctx = escalating()
    v = decide(ctx)
    gates, _ = evaluate(ctx)
    assert v.composite == pytest.approx(composite(gates))
    # A geometric mean: one weak gate visibly drags it down.
    assert 0.0 <= v.composite <= 1.0


def test_composite_geometric_mean_punishes_a_weak_gate_more_than_arithmetic():
    from samvedna.core.types import Gate

    def g(name, value):
        return Gate(name, value, 0.5, value >= 0.5, "", {})

    weak = {"evidence": g("evidence", 1.0), "consistency": g("consistency", 1.0),
            "persistence": g("persistence", 1.0), "actionability": g("actionability", 0.1)}
    geometric = composite(weak)
    arithmetic = (1.0 + 1.0 + 1.0 + 0.1) / 4
    assert geometric < arithmetic


def test_config_version_is_stamped_on_every_verdict():
    from samvedna.config.thresholds import CONFIG_VERSION

    for v in (decide(escalating()), decide(case(deviation("leave", breach=BLIP)))):
        assert v.config_version == CONFIG_VERSION


def test_identical_input_yields_an_identical_verdict():
    a, b = decide(escalating()), decide(escalating())
    assert a == b


def test_duplicate_intervention_closes_the_cycle_as_no_flag():
    v = decide(
        case(
            deviation("self_report", breach=SUSTAINED),
            deviation("leave", breach=SUSTAINED),
            deviation("duty_roster", breach=SUSTAINED),
            active=(BY_CODE["WLF-LEAVE"],),
        )
    )
    assert v.decision == "NO_FLAG"
