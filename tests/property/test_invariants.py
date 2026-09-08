"""Property invariants from PART 13, checked with Hypothesis.

Unit tests confirm the numbers the design was published with. These confirm the
*shape* of the arithmetic across inputs nobody thought to write down — which is
where a gate engine actually breaks, because the failure mode is never the case
you had in mind.
"""
from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tests.conftest import case, consent, deviation, unit

from samvedna.config.weights import ALL_DOMAINS
from samvedna.core.gates import actionability, consistency, evidence, persistence
from samvedna.core.interventions import PLAYBOOK
from samvedna.core.verdict import decide

SETTINGS = settings(
    max_examples=200,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)

domains = st.sampled_from(ALL_DOMAINS)
domain_sets = st.lists(domains, min_size=1, max_size=6, unique=True)
fractions = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
directions = st.sampled_from(["elevated", "reduced"])
triples = st.tuples(fractions, fractions, fractions)


def devs(names, direction="elevated", breach=None, missing=0.0):
    return [deviation(n, direction=direction, breach=breach, missing=missing) for n in names]


@SETTINGS
@given(names=domain_sets, extra=domains)
def test_adding_a_corroborating_domain_never_lowers_evidence(names, extra):
    before = evidence(case(*devs(names))).value
    after = evidence(case(*devs(sorted(set(names) | {extra})))).value
    assert after >= before - 1e-12


@SETTINGS
@given(names=domain_sets, fraction=st.floats(min_value=0.40, max_value=1.0))
def test_adding_a_confounder_never_raises_consistency(names, fraction):
    clean = consistency(case(*devs(names))).value
    confounded = consistency(
        case(*devs(names), unit_state=unit(deviating=dict.fromkeys(names, fraction)))
    ).value
    assert confounded <= clean + 1e-12


@SETTINGS
@given(names=domain_sets, missing=st.floats(min_value=0.21, max_value=1.0))
def test_a_data_gap_never_raises_consistency(names, missing):
    clean = consistency(case(*devs(names))).value
    gapped = consistency(case(*devs(names, missing=missing))).value
    assert gapped <= clean + 1e-12


@SETTINGS
@given(
    names=domain_sets,
    a=triples,
    delta=st.floats(min_value=0.0, max_value=1.0),
)
def test_extending_a_breach_never_lowers_persistence(names, a, delta):
    base = {7: a[0], 30: a[1], 90: a[2]}
    extended = {k: min(1.0, v + delta) for k, v in base.items()}
    before = persistence(case(*devs(names, breach=base))).value
    after = persistence(case(*devs(names, breach=extended))).value
    assert after >= before - 1e-12


@SETTINGS
@given(names=domain_sets, item=st.sampled_from(PLAYBOOK))
def test_an_active_duplicate_never_raises_actionability(names, item):
    before = actionability(case(*devs(names))).value
    after = actionability(case(*devs(names), active=(item,))).value
    assert after <= before + 1e-12


@SETTINGS
@given(names=domain_sets, direction=directions, breach=triples)
def test_identical_input_always_yields_an_identical_verdict(names, direction, breach):
    b = {7: breach[0], 30: breach[1], 90: breach[2]}
    ctx = case(*devs(names, direction=direction, breach=b))
    assert decide(ctx) == decide(ctx)


@SETTINGS
@given(names=domain_sets, breach=triples)
def test_the_composite_never_affects_the_decision(names, breach):
    """Perturbing only the display composite cannot move the verdict, because
    nothing downstream of `composite()` is read by `decide()`."""
    from dataclasses import replace

    b = {7: breach[0], 30: breach[1], 90: breach[2]}
    ctx = case(*devs(names, breach=b))
    v = decide(ctx)
    tampered = replace(v, composite=1.0 - v.composite)
    assert tampered.decision == v.decision


@SETTINGS
@given(names=domain_sets, breach=triples, contact=st.booleans())
def test_no_escalate_without_consent_covering_a_deviating_domain(names, breach, contact):
    b = {7: breach[0], 30: breach[1], 90: breach[2]}
    ctx = case(
        *devs(names, breach=b),
        consent_state=consent(scope=(), welfare_contact=contact, status="REVOKED"),
    )
    v = decide(ctx)
    assert not v.names_a_person


@SETTINGS
@given(names=domain_sets, breach=triples)
def test_every_gate_value_stays_inside_the_unit_interval(names, breach):
    b = {7: breach[0], 30: breach[1], 90: breach[2]}
    v = decide(case(*devs(names, breach=b)))
    for gate in v.gates.values():
        assert 0.0 <= gate.value <= 1.0
    assert 0.0 <= v.composite <= 1.0


@SETTINGS
@given(names=domain_sets, breach=triples)
def test_an_escalate_always_carries_a_recommendation_and_no_mind_change(names, breach):
    b = {7: breach[0], 30: breach[1], 90: breach[2]}
    v = decide(case(*devs(names, breach=b)))
    if v.decision == "ESCALATE":
        assert v.recommended
        assert v.mind_change == ()
    if v.decision in ("MONITOR", "NO_FLAG"):
        assert v.recommended == ()


@SETTINGS
@given(names=domain_sets, breach=triples)
def test_a_failed_gate_always_produces_a_mind_change_item_unless_overridden(names, breach):
    b = {7: breach[0], 30: breach[1], 90: breach[2]}
    v = decide(case(*devs(names, breach=b)))
    if not v.override and v.failed_gates:
        assert {i.gate for i in v.mind_change} == set(v.failed_gates)
