"""The four gates. Pure arithmetic, and the reason this system is defensible.

No model calls, no network, no database, no clock. Same input, same output,
always. Every gate returns every input term it was computed from, and a formula
string with the actual numbers substituted — because "the computer says 0.72" is
not something an officer can defend to the jawan sitting opposite them, and
"0.50x0.750 + 0.30x1.000 + 0.20x0 = 0.675, threshold 0.65" is.

Read this module as arithmetic. If a line of it needs a paragraph to justify,
the line is wrong.
"""
from __future__ import annotations

from samvedna.config.thresholds import GATE_THRESHOLDS
from samvedna.config.weights import (
    ACTIONABILITY_CAPACITY_FLOOR,
    ACTIONABILITY_CAPACITY_SPAN,
    COMPOSITE_EXP_ACTIONABILITY,
    COMPOSITE_EXP_CONSISTENCY,
    COMPOSITE_EXP_EVIDENCE,
    COMPOSITE_EXP_PERSISTENCE,
    EVIDENCE_BREADTH_TARGET,
    EVIDENCE_VOLUME_SATURATION,
    EVIDENCE_W_BREADTH,
    EVIDENCE_W_HAS_T1,
    EVIDENCE_W_VOLUME,
    PERSISTENCE_WEIGHTS,
)
from samvedna.config.windows import PERSISTENCE_WINDOWS_DAYS
from samvedna.core import confounders as confounder_rules
from samvedna.core import interventions as intervention_matcher
from samvedna.core.types import CaseContext, ConfounderHit, DomainDeviation, Gate, GateName

__all__ = [
    "GATE_ORDER",
    "consented_deviations",
    "evidence",
    "consistency",
    "persistence",
    "actionability",
    "evaluate",
    "composite",
]

GATE_ORDER: tuple[GateName, ...] = ("evidence", "consistency", "persistence", "actionability")

def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def consented_deviations(ctx: CaseContext) -> tuple[DomainDeviation, ...]:
    """Deviations the person's consent actually covers.

    Ingest already drops unconsented domains, so in a healthy run this filter is
    a no-op. It exists anyway: a consent bug upstream must fail closed, and the
    cheapest place to guarantee that is the layer that cannot be bypassed.
    """
    return tuple(d for d in ctx.deviations if ctx.consent.covers(d.domain))


# ------------------------------------------------------------------ evidence --
def evidence(ctx: CaseContext) -> Gate:
    """Is there enough corroborated signal to be talking about a person at all?

    The two `min()` caps are what stop a single noisy domain from ever clearing
    the gate. One T3 domain on its own scores 0.183; one T2 scores 0.246. Neither
    is close to 0.65, and no amount of severity in that one domain changes it,
    because volume saturates and breadth is a count. Escalation requires breadth,
    by construction.

    `has_t1` is worth a fifth of the gate on its own. That is the incentive
    design that makes the personnel app worth opening: a voluntary self-
    assessment is the single most valuable thing a jawan can contribute, and it
    is the only input they control.
    """
    devs = consented_deviations(ctx)
    weighted_volume = sum(d.weight for d in devs)
    distinct = len({d.domain for d in devs})
    has_t1 = 1 if any(d.tier == "T1" for d in devs) else 0

    volume = min(1.0, weighted_volume / EVIDENCE_VOLUME_SATURATION)
    breadth = min(1.0, distinct / EVIDENCE_BREADTH_TARGET)
    value = _clamp(
        EVIDENCE_W_VOLUME * volume + EVIDENCE_W_BREADTH * breadth + EVIDENCE_W_HAS_T1 * has_t1
    )
    threshold = GATE_THRESHOLDS["evidence"]
    return Gate(
        name="evidence",
        value=value,
        threshold=threshold,
        passed=value >= threshold,
        formula=(
            f"evidence = {EVIDENCE_W_VOLUME:.2f}x{volume:.3f} "
            f"+ {EVIDENCE_W_BREADTH:.2f}x{breadth:.3f} "
            f"+ {EVIDENCE_W_HAS_T1:.2f}x{has_t1} = {value:.3f}"
        ),
        inputs={
            "weighted_volume": round(weighted_volume, 4),
            "saturation": EVIDENCE_VOLUME_SATURATION,
            "volume": round(volume, 4),
            "distinct_domains": distinct,
            "breadth_target": EVIDENCE_BREADTH_TARGET,
            "breadth": round(breadth, 4),
            "has_t1": bool(has_t1),
            "domains": ",".join(sorted(d.domain for d in devs)),
        },
    )


# --------------------------------------------------------------- consistency --
def consistency(ctx: CaseContext, hits: tuple[ConfounderHit, ...] | None = None) -> Gate:
    """Do the domains agree with each other, or is one anomaly shouting?

    `sup(d)` deliberately excludes d itself. A domain must be corroborated by
    *other* domains; letting it corroborate itself would reintroduce exactly the
    self-supporting single signal the evidence gate's breadth term exists to
    reject, and would mean a lone domain scored 1.000 for agreeing with nobody.
    Under that rule a single deviating domain scores 0 — which is correct. One
    domain has no corroboration, so consistency is not "high", it is undefined in
    the direction of nothing, and the safe reading of nothing is zero.

    **Support is discounted by the supporting domain's own unshared benign
    explanation, and the denominator is the support that was theoretically
    available.** Both halves are needed, and the second one is why the naive
    formula leaked.

    Measured on the synthetic force: a jawan in a surged unit deviating in
    deployment, duty_roster, leave and workload, where the surge explains the
    last three. The naive formula scored `deployment` at 2.10/(2.10 + 0) =
    **1.000** — full marks for being corroborated by three domains that agree
    with each other only because they share a cause. That is the ecological
    fallacy with a threshold attached, and it escalated five people in the one
    unit whose whole situation was already explained.

    Two domains explained by the same surge are not independent witnesses. So a
    supporting domain contributes `w(e) x (1 - unshared_mass(e, d))`, where
    unshared mass counts only the rules hitting `e` that do **not** also hit `d`
    — and `agree(d)` divides by the *undiscounted* support, so a domain propped
    up by discounted evidence cannot still score 1.000 merely because nothing
    contradicted it.

    Every published calibration row is preserved exactly: when all domains share
    the same confounder nothing is unshared, so PART 6.65 row 7 still computes to
    25/36 = 0.694.
    """
    devs = consented_deviations(ctx)
    if hits is None:
        hits = confounder_rules.detect(ctx)
    mass = confounder_rules.mass_by_domain(hits)
    rules = confounder_rules.rules_by_domain(hits)

    per_domain: dict[str, float] = {}
    terms: list[str] = []
    for d in devs:
        own_rules = rules.get(d.domain, {})
        agreeing = [o for o in devs if o.domain != d.domain and o.direction == d.direction]
        sup_available = sum(o.weight for o in agreeing)
        sup_credible = 0.0
        for other in agreeing:
            unshared = sum(
                m for rule, m in rules.get(other.domain, {}).items() if rule not in own_rules
            )
            sup_credible += other.weight * max(0.0, 1.0 - min(1.0, unshared))
        con = sum(o.weight for o in devs if o.direction != d.direction)
        con += mass.get(d.domain, 0.0)
        denominator = sup_available + con
        agree = 0.0 if denominator == 0 else sup_credible / denominator
        per_domain[d.domain] = agree
        terms.append(
            f"{d.domain}: {sup_credible:.2f}/({sup_available:.2f}+{con:.2f})={agree:.3f}"
        )

    value = _clamp(sum(per_domain.values()) / len(per_domain)) if per_domain else 0.0
    threshold = GATE_THRESHOLDS["consistency"]
    return Gate(
        name="consistency",
        value=value,
        threshold=threshold,
        passed=value >= threshold,
        formula=(
            f"consistency = mean({', '.join(f'{v:.3f}' for v in per_domain.values())})"
            f" = {value:.3f}" if per_domain else "consistency = 0.000 (no deviating domain)"
        ),
        inputs={
            "per_domain": " | ".join(terms),
            "confounder_mass": " | ".join(f"{k}={v:.2f}" for k, v in sorted(mass.items())),
            "confounders": ",".join(sorted({h.rule for h in hits})),
            "n_domains": len(per_domain),
        },
    )


# --------------------------------------------------------------- persistence --
def persistence(ctx: CaseContext) -> Gate:
    """Sustained, not a blip.

    Weighted toward the 30-day window: long enough to exclude a bad week, short
    enough to act before a crisis. A single acute event cannot clear this gate —
    and must not have to, which is why the safety override in `verdict.py`
    bypasses it entirely rather than weakening it.

    Across several deviating domains the per-window fractions are combined by
    domain weight, so a sustained T1 breach counts for more than a sustained T3
    one. With a single domain this reduces exactly to that domain's fractions.
    """
    devs = consented_deviations(ctx)
    windows: dict[int, float] = {}
    for days in PERSISTENCE_WINDOWS_DAYS:
        # Only domains that were actually observed over this window. A domain
        # with no entry for a window is *unknown* there, not zero, and the
        # difference is the whole of this loop.
        #
        # This used to read `d.daily_breach.get(days, 0.0)` over every domain,
        # so a domain with no 30-day history contributed nothing to the
        # numerator while still contributing its full weight to the
        # denominator — diluting every domain that *did* have history. The
        # effect was backwards in the worst possible way: a jawan who submitted
        # a severe self-assessment, which is one day old by definition and
        # carries the highest tier weight, pushed their own persistence from
        # 0.650 (passing) to 0.505 (failing). Reporting distress made the system
        # less likely to act.
        #
        # This is the same rule the ingest layer already states: a connector
        # that returns nothing must not read as a low value, and
        # `breach_fraction` divides by the window length rather than the row
        # count for exactly this reason. Persistence was the one place it was
        # not applied.
        observed = [d for d in devs if days in d.daily_breach]
        observed_weight = sum(d.weight for d in observed)
        if observed_weight == 0:
            # Nothing was observed over this window by any domain. Zero is the
            # honest value: there is no evidence of persistence at this length,
            # which is different from evidence of its absence but produces the
            # same — conservative — answer.
            windows[days] = 0.0
            continue
        windows[days] = sum(
            d.weight * _clamp(d.daily_breach[days]) for d in observed
        ) / observed_weight

    value = _clamp(sum(PERSISTENCE_WEIGHTS[d] * windows[d] for d in PERSISTENCE_WINDOWS_DAYS))
    threshold = GATE_THRESHOLDS["persistence"]
    return Gate(
        name="persistence",
        value=value,
        threshold=threshold,
        passed=value >= threshold,
        formula=(
            " + ".join(
                f"{PERSISTENCE_WEIGHTS[d]:.2f}x{windows[d]:.3f}"
                for d in PERSISTENCE_WINDOWS_DAYS
            )
            + f" = {value:.3f}"
        ),
        inputs={
            **{f"w{d}d": round(windows[d], 4) for d in PERSISTENCE_WINDOWS_DAYS},
            "weighted_over_domains": len(devs),
        },
    )


# -------------------------------------------------------------- actionability --
def actionability(ctx: CaseContext) -> Gate:
    """Is there a welfare action that fits, that is not already being taken?

    Multiplicative, not a weighted sum, and this is not a style preference.
    Three of the four terms are hard vetoes: no matching action, an already
    active one, or absent consent must each force the gate to exactly zero. A
    weighted sum cannot express a veto — with plausible weights
    (0.40 match + 0.25 not_duplicate + 0.15 consent + 0.20 capacity) a person who
    has given **no consent to be contacted** still scores 0.85 and sails through
    a 0.50 threshold. The gate would leak, quietly, in the one direction that
    matters. Do not "simplify" this back into an average.

    Capacity is the single soft term. An exhausted welfare cell lowers the gate
    to 0.75 but must not block, because a genuine case still deserves to be
    recorded and queued for the next cycle.
    """
    candidates = intervention_matcher.match(ctx)
    duplicate = intervention_matcher.duplicate_of(ctx, candidates)

    match_term = 1 if candidates else 0
    not_duplicate = 0 if duplicate is not None else 1
    consent_ok = 1 if ctx.consent.welfare_contact and ctx.consent.status in (
        "ACTIVE",
        "PARTIAL",
    ) else 0
    capacity = 1 if ctx.unit.welfare_capacity_available else 0
    capacity_term = ACTIONABILITY_CAPACITY_FLOOR + ACTIONABILITY_CAPACITY_SPAN * capacity

    value = _clamp(match_term * not_duplicate * consent_ok * capacity_term)
    threshold = GATE_THRESHOLDS["actionability"]
    return Gate(
        name="actionability",
        value=value,
        threshold=threshold,
        passed=value >= threshold,
        formula=(
            f"actionability = {match_term} x {not_duplicate} x {consent_ok} "
            f"x ({ACTIONABILITY_CAPACITY_FLOOR:.2f} + "
            f"{ACTIONABILITY_CAPACITY_SPAN:.2f}x{capacity}) = {value:.3f}"
        ),
        inputs={
            "match": bool(match_term),
            "not_duplicate": bool(not_duplicate),
            "consent_ok": bool(consent_ok),
            "capacity": bool(capacity),
            "matched": ",".join(i.code for i in candidates),
            "duplicate_of": duplicate.code if duplicate else "",
        },
    )


# ---------------------------------------------------------------- aggregation --
def evaluate(ctx: CaseContext) -> tuple[dict[GateName, Gate], tuple[ConfounderHit, ...]]:
    """All four gates, plus the confounder hits that fed consistency."""
    hits = confounder_rules.detect(ctx)
    gates: dict[GateName, Gate] = {
        "evidence": evidence(ctx),
        "consistency": consistency(ctx, hits),
        "persistence": persistence(ctx),
        "actionability": actionability(ctx),
    }
    return gates, hits


def composite(gates: dict[GateName, Gate]) -> float:
    """DISPLAY ONLY. Never gates anything; `verdict.py` must not read this.

    A weighted geometric mean, so one weak gate visibly drags the number down. An
    arithmetic mean would let three strong gates hide a fatal fourth, which is
    precisely the failure mode a caseload ranking must not have.
    """
    exponents = {
        "evidence": COMPOSITE_EXP_EVIDENCE,
        "consistency": COMPOSITE_EXP_CONSISTENCY,
        "persistence": COMPOSITE_EXP_PERSISTENCE,
        "actionability": COMPOSITE_EXP_ACTIONABILITY,
    }
    result = 1.0
    for name, exponent in exponents.items():
        result *= gates[name].value ** exponent
    return _clamp(result)
