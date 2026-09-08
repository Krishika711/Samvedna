"""Mind-change items must be concrete, computed, and checkable by an officer.

The failure mode this guards against is a system that says "more data would
help". Every item here is derived by solving a gate for its shortfall, and every
`would_change_if` string names something the officer could go and verify.
"""
from __future__ import annotations

import re

from tests.conftest import case, consent, deviation, unit

from samvedna.core.verdict import decide

SUSTAINED = {7: 1.0, 30: 1.0, 90: 0.9}
BLIP = {7: 1.0, 30: 7 / 30, 90: 7 / 90}

VAGUE = ("more data", "further information", "additional context", "review needed",
         "unclear", "possibly", "might be", "consider whether")


def all_text(v):
    return " ".join(
        [*(s for i in v.mind_change for s in i.failed_because),
         *(s for i in v.mind_change for s in i.would_change_if)]
    ).lower()


def test_no_item_is_vague():
    v = decide(case(deviation("leave", breach=BLIP)))
    text = all_text(v)
    for phrase in VAGUE:
        assert phrase not in text, f"vague mind-change text: {phrase!r}"


def test_every_item_carries_a_number():
    v = decide(case(deviation("leave", breach=BLIP)))
    assert v.mind_change
    for item in v.mind_change:
        assert item.current <= item.required
        joined = " ".join(item.failed_because + item.would_change_if)
        assert re.search(r"\d", joined), f"no number in {item.gate} item"


def test_evidence_shortfall_offers_a_self_assessment_worth_0_20():
    v = decide(
        case(
            deviation("leave", breach=SUSTAINED),
            deviation("duty_roster", breach=SUSTAINED),
        )
    )
    ev = [i for i in v.mind_change if i.gate == "evidence"]
    assert ev, "the evidence gate failed and must produce an item"
    text = " ".join(ev[0].would_change_if)
    assert "self-assessment" in text and "0.20" in text


def test_evidence_shortfall_states_how_many_further_domains():
    v = decide(case(deviation("transfer", breach=SUSTAINED)))
    ev = [i for i in v.mind_change if i.gate == "evidence"][0]
    assert any(re.search(r"\d+ (more distinct|further service-record)", s)
               for s in ev.would_change_if)


def test_consistency_shortfall_names_the_confounder_and_its_mass():
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
    item = [i for i in v.mind_change if i.gate == "consistency"][0]
    text = " ".join(item.would_change_if)
    assert "op-tempo" in text and "0.70" in text
    assert "deployment cycle ends" in text
    assert item.recoverable


def test_persistence_shortfall_computes_how_many_more_days():
    v = decide(
        case(
            deviation("self_report", breach=BLIP),
            deviation("leave", breach=BLIP),
            deviation("duty_roster", breach=BLIP),
        )
    )
    item = [i for i in v.mind_change if i.gate == "persistence"][0]
    match = re.search(r"a further (\d+) days?", " ".join(item.would_change_if))
    assert match, item.would_change_if
    assert 1 <= int(match.group(1)) <= 30


def test_actionability_shortfall_says_consent_is_the_persons_to_give():
    v = decide(
        case(deviation("leave", breach=SUSTAINED), consent_state=consent(welfare_contact=False))
    )
    item = [i for i in v.mind_change if i.gate == "actionability"][0]
    text = " ".join(item.would_change_if)
    assert "extends consent to welfare contact" in text
    assert "will not ask again" in text


def test_an_active_intervention_is_marked_irrecoverable_and_sorted_last():
    from samvedna.core.interventions import BY_CODE

    v = decide(
        case(
            deviation("leave", breach=BLIP),
            deviation("transfer", breach=BLIP),
            active=(BY_CODE["WLF-LEAVE"],),
        )
    )
    item = [i for i in v.mind_change if i.gate == "actionability"][0]
    assert not item.recoverable
    assert v.mind_change[-1].gate == "actionability"


def test_passing_gates_produce_no_items():
    v = decide(
        case(
            deviation("self_report", breach=SUSTAINED),
            deviation("leave", breach=SUSTAINED),
            deviation("duty_roster", breach=SUSTAINED),
        )
    )
    assert v.decision == "ESCALATE"
    assert v.mind_change == ()


def test_mind_change_is_deterministic():
    ctx = case(deviation("leave", breach=BLIP))
    assert decide(ctx).mind_change == decide(ctx).mind_change
