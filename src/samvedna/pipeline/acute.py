"""Workflow E — the acute-risk path. Time-critical, and it does not wait for 02:00.

The rest of this system is built to say less. This one path is built to say
something immediately, and the tension is deliberate: gate logic optimises for
precision, and precision is the wrong objective when a person has just told the
app they are in trouble.

Four rules, none of which may be traded away:

1. **Triggered by the instrument, not by a model.** PHQ-9 item 9 endorsed is a
   person telling us something directly. A model deciding somebody is in acute
   distress is a model making a clinical judgement it has no standing to make.
2. **Routed to a mental-health authority, never to the commanding officer.** An
   acute disclosure reaching a person's chain of command is the single outcome
   most likely to stop the next person disclosing anything.
3. **The person sees support immediately**, in the app, before anybody else has
   acted. Not a confirmation that their form was submitted — help.
4. **Logged as an OVERRIDE with its reason**, and the gates it bypassed are still
   computed and recorded, so an officer can see afterwards what the arithmetic
   would have said.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from samvedna.core.types import CaseContext, InstrumentResponse, Verdict
from samvedna.core.verdict import acute_items_in, decide
from samvedna.disclosure.audit import Ledger, LedgerWriteFailed

__all__ = [
    "HELP_RESOURCES",
    "SLA_HOURS",
    "SUPPORT_MESSAGE",
    "AcuteRoute",
    "handle_submission",
    "submit",
]

# Acknowledged same working day (PART 6.7). Expressed in hours so the SLA is
# measurable rather than aspirational.
SLA_HOURS = 12

SUPPORT_MESSAGE = (
    "Thank you for telling us. What you have described is taken seriously, and "
    "someone qualified will contact you today.\n\n"
    "This does not go to your commanding officer, it does not go on your record, "
    "and it will not affect your posting, promotion or ACR.\n\n"
    "You do not have to wait for that call. The numbers below are available now."
)

HELP_RESOURCES: tuple[tuple[str, str], ...] = (
    ("Unit medical officer", "available through the unit exchange, at any hour"),
    (
        "Designated mental-health authority",
        "contactable directly, without going through the unit",
    ),
    (
        "Trusted colleague or buddy",
        "the person you would tell first, if you were going to tell anyone",
    ),
)


@dataclass(frozen=True, slots=True)
class AcuteRoute:
    """What happened, and what the person was shown."""

    pid: str
    triggered_by: tuple[str, ...]
    instrument: str
    verdict: Verdict
    routed_to: str
    acknowledge_by: datetime
    shown_to_person: str
    resources: tuple[tuple[str, str], ...]
    ledger_seq: int

    @property
    def routed_to_command(self) -> bool:
        """Must always be False. Asserted in the test suite."""
        return "command" in self.routed_to


def handle_submission(
    response: InstrumentResponse,
    ctx: CaseContext,
    ledger: Ledger,
    *,
    now: datetime | None = None,
) -> AcuteRoute | None:
    """Called the moment a self-assessment is submitted, not by the nightly DAG.

    Returns an `AcuteRoute` when an acute item fired, or None when the response
    joins the ordinary pipeline. Raises `LedgerWriteFailed` if the override
    cannot be recorded — an unlogged override is not an override, it is an
    untraceable escalation.

    The SLA clock starts when the **person submitted**, not when the system got
    round to processing it. Measuring from processing time lets a queue delay
    silently consume the window a person is waiting inside, and in the first run
    of this path it produced an acknowledge-by timestamp in the past.
    """
    items = acute_items_in(response)
    if not items:
        return None

    at = now or response.taken_at
    acute_ctx = CaseContext(
        pid=ctx.pid,
        unit_id=ctx.unit_id,
        as_of=ctx.as_of,
        deviations=ctx.deviations,
        consent=ctx.consent,
        unit=ctx.unit,
        risk=ctx.risk,
        reviewers=ctx.reviewers,
        active_interventions=ctx.active_interventions,
        suppressed_drivers=ctx.suppressed_drivers,
        acute_items=items,
        clinician_concern=ctx.clinician_concern,
    )
    verdict = decide(acute_ctx)

    entry = ledger.append(
        actor="system:acute_path",
        action="override.applied",
        subject_pid=ctx.pid,
        unit_id=ctx.unit_id,
        purpose="welfare:acute_risk",
        detail={
            "instrument": response.instrument,
            # The item that fired, never the answers.
            "acute_items": ",".join(items),
            "bypassed_gates": ",".join(
                name for name, gate in verdict.gates.items() if not gate.passed
            ),
            "routed_to": "mental_health_authority",
            "reason": verdict.override_reason,
            "acknowledge_by_hours": SLA_HOURS,
        },
        at=at,
    )

    return AcuteRoute(
        pid=ctx.pid,
        triggered_by=items,
        instrument=response.instrument,
        verdict=verdict,
        routed_to="mental_health_authority",
        acknowledge_by=at + timedelta(hours=SLA_HOURS),
        shown_to_person=SUPPORT_MESSAGE,
        resources=HELP_RESOURCES,
        ledger_seq=entry.seq,
    )


def submit(
    response: InstrumentResponse,
    ctx: CaseContext,
    ledger: Ledger,
    *,
    now: datetime | None = None,
) -> tuple[AcuteRoute | None, str]:
    """The full submission handler. Never lets a ledger failure swallow the route.

    If the ledger write fails the person is still shown support — withholding
    help because a database was unavailable would be the worst possible reading
    of "fail closed" — but the route is not returned, so nothing is dispatched
    without an audit record, and the caller is told to escalate manually.
    """
    try:
        route = handle_submission(response, ctx, ledger, now=now)
    except LedgerWriteFailed as exc:
        return None, (
            f"{SUPPORT_MESSAGE}\n\n[system: this disclosure could not be recorded "
            f"({exc}). It has NOT been routed automatically. Contact the "
            f"designated mental-health authority directly.]"
        )
    if route is None:
        return None, ""
    return route, route.shown_to_person
