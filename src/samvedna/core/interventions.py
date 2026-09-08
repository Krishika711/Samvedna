"""Matching a verdict's drivers to a welfare action that actually fits.

A flag nobody can act on is noise, and noise erodes trust faster than a missed
case. So the actionability gate asks a blunt question — is there something a
welfare officer could *do* about this, that is not already being done? — and this
module answers it deterministically from a playbook.

The playbook is data, not code, so a welfare directorate can extend it without a
release. Matching is on driver keys, which are domain names and feature names
from the attribution step, never on prose.
"""
from __future__ import annotations

from samvedna.config.windows import INTERVENTION_ACTIVE_DAYS
from samvedna.core.types import CaseContext, Intervention

__all__ = ["PLAYBOOK", "match", "duplicate_of", "INTERVENTION_ACTIVE_DAYS"]


# `addresses` entries are matched as substrings of a driver key, so
# "leave" catches "leave_denied_rate_30d" as well as the bare domain name.
PLAYBOOK: tuple[Intervention, ...] = (
    Intervention(
        code="WLF-REST",
        title="Rest and rotation review",
        rationale=(
            "Sustained duty density and denied leave are the two service-record "
            "patterns that respond fastest to a rotation change."
        ),
        addresses=("duty_roster", "consecutive_duty", "workload", "leave"),
    ),
    Intervention(
        code="WLF-LEAVE",
        title="Leave sanction review with the unit adjutant",
        rationale=(
            "Repeated leave denial is actionable at unit level and is one of the "
            "few drivers a welfare officer can resolve the same week."
        ),
        addresses=("leave", "leave_denied"),
    ),
    Intervention(
        code="WLF-FAMILY",
        title="Family liaison and compassionate posting review",
        rationale=(
            "Long deployment away from station combined with transfer churn is a "
            "family-separation pattern, not a duty-load pattern."
        ),
        addresses=("deployment", "transfer", "separation"),
    ),
    Intervention(
        code="WLF-PEER",
        title="Peer-support conversation (buddy system)",
        rationale=(
            "Low-intensity, non-clinical, and the least stigmatising first contact "
            "available when the drivers are broad rather than acute."
        ),
        addresses=("self_report", "workload", "duty_roster", "training"),
    ),
    Intervention(
        code="WLF-COUNSEL",
        title="Referral to unit counselling cell",
        rationale=(
            "A validated instrument above cut-off is a direct, consented signal "
            "and warrants a trained conversation rather than a roster change."
        ),
        addresses=("self_report", "phq9", "gad7", "mbi"),
        authority="unit_welfare",
    ),
    Intervention(
        code="MH-URGENT",
        title="Same-day contact by the designated mental-health authority",
        rationale=(
            "Acute-risk item endorsed on a validated instrument. This routes to a "
            "mental-health authority, never to the commanding officer."
        ),
        addresses=("acute", "phq9_item_9", "clinician_concern"),
        authority="mental_health",
    ),
    Intervention(
        code="WLF-TRAINING-LOAD",
        title="Training load rescheduling",
        rationale="Training assignments are movable in a way operational duty is not.",
        addresses=("training", "course_load"),
    ),
)

BY_CODE = {item.code: item for item in PLAYBOOK}


def _matches(item: Intervention, driver_keys: tuple[str, ...]) -> bool:
    return any(token in key for key in driver_keys for token in item.addresses)


def driver_keys(ctx: CaseContext) -> tuple[str, ...]:
    """The driver vocabulary a case is matched on.

    Deviating domain names always count. Model attributions are added when the
    model was available — but a case must remain matchable without them, because
    the risk model is an input to the decision and never a precondition for it.
    Drivers suppressed by an accepted confounder annotation (Workflow G) are
    dropped here, which is what makes contesting a flag mean something.
    """
    keys = [d.domain for d in ctx.deviations]
    if ctx.risk is not None and ctx.risk.status == "ok":
        keys.extend(name for name, _ in ctx.risk.drivers)
    if ctx.acute_items:
        keys.extend(["acute", *ctx.acute_items])
    if ctx.clinician_concern:
        keys.append("clinician_concern")
    return tuple(k for k in keys if k not in ctx.suppressed_drivers)


def match(ctx: CaseContext) -> tuple[Intervention, ...]:
    """Every playbook action that speaks to at least one live driver."""
    keys = driver_keys(ctx)
    if not keys:
        return ()
    matched = [item for item in PLAYBOOK if _matches(item, keys)]
    # Acute routing outranks everything else in the caseload ordering.
    matched.sort(key=lambda i: (i.authority != "mental_health", i.code))
    return tuple(matched)


def duplicate_of(ctx: CaseContext, candidates: tuple[Intervention, ...]) -> Intervention | None:
    """An already-active intervention that already covers these drivers.

    Re-flagging somebody who is already under active counselling is the single
    fastest way to lose the force's confidence, so this is a hard veto in the
    actionability gate rather than a ranking penalty.
    """
    active_codes = {i.code for i in ctx.active_interventions}
    for candidate in candidates:
        if candidate.code in active_codes:
            return candidate
    active_topics = {token for i in ctx.active_interventions for token in i.addresses}
    for candidate in candidates:
        if active_topics.issuperset(set(candidate.addresses)):
            return candidate
    return None
