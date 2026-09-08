"""The decision. Deterministic arithmetic, in a fixed order, with no model in it.

Precedence is the whole design. Irrecoverable conditions are checked before
recoverable ones, so a person with no consent basis is closed as NO_FLAG and is
never described as "not yet sustained" — which would be both wrong and an
invitation to wait for them to become escalatable.

    IF   consent absent for all deviating domains  -> NO_FLAG   "no consent basis"
    ELSE IF actionability failed                   -> NO_FLAG   "no available action"
    ELSE IF persistence failed                     -> MONITOR   "not yet sustained"
    ELSE IF evidence OR consistency failed         -> MONITOR   "insufficient/confounded"
    ELSE                                           -> ESCALATE

MONITOR keeps the pid under observation with no identity disclosed and no alert
raised. It is a first-class outcome, not a failure — most nights, on most people,
it is the right answer.
"""
from __future__ import annotations

from samvedna.config.thresholds import ACUTE_ITEM_MIN_VALUE, CONFIG_VERSION
from samvedna.core import gates as gate_engine
from samvedna.core import interventions as intervention_matcher
from samvedna.core import mindchange
from samvedna.core.types import (
    CaseContext,
    Gate,
    GateName,
    InstrumentResponse,
    Verdict,
)

__all__ = ["decide", "acute_items_in", "SAFETY_OVERRIDE_REASON"]

SAFETY_OVERRIDE_REASON = (
    "acute-risk item endorsed on a validated instrument, or a direct concern "
    "raised by an authorised clinician"
)


def acute_items_in(response: InstrumentResponse) -> tuple[str, ...]:
    """Acute items endorsed on one instrument response.

    Triggered by the *instrument*, never by a model score. That distinction is
    load-bearing: a model deciding somebody is in acute distress is a model
    making a clinical judgement, whereas PHQ-9 item 9 being endorsed is a person
    telling us something directly, and the correct response to being told is to
    act rather than to weigh it.
    """
    from samvedna.config.thresholds import ACUTE_ITEMS

    watched = ACUTE_ITEMS.get(response.instrument, ())
    return tuple(
        item for item in watched if response.items.get(item, 0) > ACUTE_ITEM_MIN_VALUE
    )


def _override_verdict(ctx: CaseContext, gates: dict[GateName, Gate]) -> Verdict:
    """Bypass the persistence and evidence gates. Route, log, and never swallow.

    Gate logic optimises for precision, and precision is the wrong objective when
    somebody has just told the app they are in trouble. Acute risk does not wait
    for a 30-day window, so this path exists — narrow, instrument-triggered, fully
    logged, and routed to a mental-health authority rather than to the unit.
    """
    matched = tuple(
        i for i in intervention_matcher.match(ctx) if i.authority == "mental_health"
    ) or intervention_matcher.match(ctx)
    trigger = (
        f"acute item(s) {', '.join(ctx.acute_items)}" if ctx.acute_items
        else "clinician concern raised"
    )
    return Verdict(
        decision="IMMEDIATE_ESCALATE",
        reason=f"safety override: {trigger}",
        gates=gates,
        failed_gates=tuple(n for n, g in gates.items() if not g.passed),
        mind_change=(),
        composite=gate_engine.composite(gates),
        recommended=matched,
        override=True,
        override_reason=SAFETY_OVERRIDE_REASON,
        config_version=CONFIG_VERSION,
    )


def decide(ctx: CaseContext, *, escalation_frozen: bool = False) -> Verdict:
    """The only function in the system that produces a decision.

    `escalation_frozen` is set by the orchestrator when the Confounder Check
    reviewer is unavailable or the model has drifted past threshold (PART 8.8).
    A frozen run still records MONITOR — every degradation moves the system
    toward saying *less*, never toward saying more with lower confidence.
    """
    gates, hits = gate_engine.evaluate(ctx)
    failed = tuple(name for name in gate_engine.GATE_ORDER if not gates[name].passed)
    display_composite = gate_engine.composite(gates)

    # The safety override is checked before everything, including consent to
    # analysis: a person who has just disclosed acute risk in the app has, by the
    # act of submitting it, consented to that disclosure being acted on.
    if ctx.acute_items or ctx.clinician_concern:
        return _override_verdict(ctx, gates)

    items = mindchange.compute(ctx, gates, hits)

    def _verdict(decision, reason, recommended=()):  # type: ignore[no-untyped-def]
        return Verdict(
            decision=decision,
            reason=reason,
            gates=gates,
            failed_gates=failed,
            mind_change=items,
            composite=display_composite,
            recommended=recommended,
            config_version=CONFIG_VERSION,
        )

    consented = gate_engine.consented_deviations(ctx)
    if not consented:
        return _verdict("NO_FLAG", "no consent basis for any deviating domain")

    if not gates["actionability"].passed:
        return _verdict("NO_FLAG", "no available or non-duplicate welfare action")

    if not gates["persistence"].passed:
        return _verdict("MONITOR", "not yet sustained")

    if not gates["evidence"].passed or not gates["consistency"].passed:
        return _verdict("MONITOR", "insufficient or confounded evidence")

    if escalation_frozen:
        return _verdict(
            "MONITOR",
            "all gates passed but escalation is frozen for this run "
            "(reviewer unavailable or model drift beyond threshold)",
        )

    return _verdict("ESCALATE", "all four gates passed", intervention_matcher.match(ctx))
