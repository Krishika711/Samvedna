"""Alert dispatch — and the queue that a revocation must be able to empty.

An alert is the moment this system stops being analysis and starts being an
approach to a real person. Three properties follow, and each is a rule here
rather than a convention:

**Queued, not sent.** A verdict reached at 02:00 does not wake anybody. It sits
in a queue until the officer opens their console at 07:00, and the gap between
those two times is the window in which a revocation can still cancel it. PART
8.12 criterion 1 requires exactly that, and it is only possible because
dispatch is deferred.

**Cancellable, and cancellation leaves no residue.** When somebody withdraws
consent, an undelivered alert about them is not marked withdrawn — it is
removed. A cancelled-alerts list is a list of people who withdrew, which PART 14
forbids surfacing.

**Shadow mode dispatches nothing.** Phase 1 of the rollout runs the gates over a
battalion's retrospective records and issues no alerts at all, so the thresholds
can be calibrated against real outcomes before a single officer is asked to act
on one. That is a property of the dispatcher, not a discipline the operators
have to remember.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, time
from typing import Literal

from samvedna.disclosure.audit import Ledger
from samvedna.pipeline.record import CaseRecord

__all__ = [
    "Alert",
    "AlertQueue",
    "DispatchMode",
    "OFFICER_CONSOLE_HOUR",
    "AlertPriority",
]

# Alerts are held until the officer's day starts. Nothing is pushed overnight.
OFFICER_CONSOLE_HOUR = time(7, 0)

DispatchMode = Literal["live", "shadow"]
AlertPriority = Literal["same_day", "routine"]


@dataclass(frozen=True, slots=True)
class Alert:
    """One queued approach. Carries a pid, never a name.

    Re-identification happens at the moment the officer opens the case, in L5,
    with their credentials and a ledger entry. An alert that carried a name
    would be a name sitting in a queue overnight.
    """

    pid: str
    unit_id: str
    priority: AlertPriority
    reason: str
    composite: float
    intervention: str
    queued_at: datetime
    route_to: Literal["welfare_officer", "mental_health_authority"]
    delivered_at: datetime | None = None

    @property
    def delivered(self) -> bool:
        return self.delivered_at is not None

    @property
    def cancellable(self) -> bool:
        """Only what has not yet reached a human can be withdrawn."""
        return not self.delivered


@dataclass
class AlertQueue:
    """Holds alerts between the nightly run and the officer opening the console."""

    mode: DispatchMode = "live"
    _queued: list[Alert] = field(default_factory=list)
    _suppressed_in_shadow: int = 0

    @property
    def shadow(self) -> bool:
        return self.mode == "shadow"

    def enqueue(
        self,
        case: CaseRecord,
        ledger: Ledger,
        *,
        at: datetime | None = None,
    ) -> Alert | None:
        """Queue an alert for one escalated case, or decline and say why.

        Returns None when there is nothing to dispatch — a MONITOR or NO_FLAG
        verdict, or shadow mode. Declining is not an error condition; on most
        nights, for most people, it is the whole output.
        """
        verdict = case.verdict
        if verdict is None or not verdict.names_a_person:
            return None

        when = at or datetime.now(UTC)
        acute = verdict.decision == "IMMEDIATE_ESCALATE"

        if self.shadow:
            # Phase 1: the gates run and the verdict is recorded, so thresholds
            # can be calibrated against real outcomes. Nothing reaches a human.
            self._suppressed_in_shadow += 1
            ledger.append(
                actor="system:alerts",
                action="verdict.recorded",
                subject_pid=case.pid,
                unit_id=case.unit_id,
                purpose="welfare:screening",
                detail={
                    "shadow_mode": True,
                    "would_have_alerted": verdict.decision,
                    "note": "shadow run — gates executed, no alert issued",
                },
                at=when,
            )
            return None

        alert = Alert(
            pid=case.pid,
            unit_id=case.unit_id,
            priority="same_day" if acute else "routine",
            reason=verdict.reason,
            composite=round(verdict.composite, 4),
            intervention=verdict.recommended[0].code if verdict.recommended else "",
            queued_at=when,
            route_to="mental_health_authority" if acute else "welfare_officer",
        )
        self._queued.append(alert)
        ledger.append(
            actor="system:alerts",
            action="disclosure.requested",
            subject_pid=case.pid,
            unit_id=case.unit_id,
            purpose="welfare:acute" if acute else "welfare:contact",
            detail={
                "priority": alert.priority,
                "route_to": alert.route_to,
                "intervention": alert.intervention,
            },
            at=when,
        )
        return alert

    # ------------------------------------------------------------- reading --
    def pending(self, unit_id: str = "") -> tuple[Alert, ...]:
        return tuple(
            a for a in self._queued
            if not a.delivered and (not unit_id or a.unit_id == unit_id)
        )

    def for_pid(self, pid: str) -> tuple[Alert, ...]:
        return tuple(a for a in self._queued if a.pid == pid)

    @property
    def suppressed_in_shadow(self) -> int:
        """How many alerts a shadow run withheld. The point of a shadow run."""
        return self._suppressed_in_shadow

    def __len__(self) -> int:
        return len(self._queued)

    def __bool__(self) -> bool:
        # An empty queue is still a queue. See `Ledger.__bool__` for why this is
        # worth spelling out.
        return True

    # ------------------------------------------------------------ dispatch --
    def deliver(
        self, pid: str, ledger: Ledger, *, at: datetime | None = None
    ) -> Alert | None:
        """Mark an alert as reaching the officer's console. After this it cannot
        be withdrawn, because a person has seen it."""
        when = at or datetime.now(UTC)
        for index, alert in enumerate(self._queued):
            if alert.pid == pid and not alert.delivered:
                delivered = replace(alert, delivered_at=when)
                self._queued[index] = delivered
                ledger.append(
                    actor="system:alerts",
                    action="disclosure.requested",
                    subject_pid=pid,
                    unit_id=alert.unit_id,
                    purpose="welfare:contact",
                    detail={"delivered": True, "priority": alert.priority},
                    at=when,
                )
                return delivered
        return None

    def cancel_for(self, pid: str, ledger: Ledger, *, at: datetime | None = None) -> int:
        """Remove every undelivered alert for a pid. Called on revocation.

        Removed rather than marked cancelled. A list of cancelled alerts is a
        list of people who withdrew consent, and PART 14 forbids that existing
        anywhere a report could read it.

        The ledger entry records that a cancellation happened and how many —
        never who withdrew or why, which is the consent registry's business and
        the auditor's alone.
        """
        before = len(self._queued)
        self._queued = [
            a for a in self._queued if not (a.pid == pid and a.cancellable)
        ]
        cancelled = before - len(self._queued)
        if cancelled:
            ledger.append(
                actor="system:alerts",
                action="disclosure.denied",
                subject_pid=pid,
                purpose="welfare:self",
                detail={"reason": "undelivered alerts withdrawn", "count": cancelled},
                at=at or datetime.now(UTC),
            )
        return cancelled
