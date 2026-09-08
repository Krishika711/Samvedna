"""Workflow C close-out and Workflow G contest — the two loops that keep the
system honest.

**Close-out (Stage 10).** Every escalation is closed by the officer with an
outcome category, and the case list blocks until it is. Those labels are the only
honest source of precision measurement in production: a training AUROC says what
the model did on data it was fitted to, and an officer saying `not_supported`
says what happened to a real jawan.

**Contest (Workflow G).** A person who is contacted can see their own drivers and
disagree with them. An accepted confounder annotation suppresses that driver for
a configured window, so the system stops being wrong about them in the same way
next cycle. Without this every false positive is permanent, which is precisely
how a welfare tool becomes feared.

Only the *fact* of contact and its outcome category are stored. The content of a
welfare conversation is never written here (Workflow D).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from samvedna.config.windows import CONFOUNDER_ANNOTATION_DAYS
from samvedna.disclosure.audit import Ledger
from samvedna.disclosure.rbac import Principal

__all__ = [
    "Outcome",
    "OUTCOMES",
    "CloseOut",
    "Annotation",
    "ContestKind",
    "CaseBook",
    "OutcomeRequired",
]

Outcome = Literal["supported", "not_supported", "already_known", "declined_contact"]
OUTCOMES: tuple[Outcome, ...] = (
    "supported", "not_supported", "already_known", "declined_contact",
)
ContestKind = Literal["factual_error", "benign_explanation", "objects_to_analysis"]


class OutcomeRequired(RuntimeError):
    """A case cannot be closed without an outcome category."""


@dataclass(frozen=True, slots=True)
class CloseOut:
    pid: str
    outcome: Outcome
    officer: str
    at: datetime
    note: str = ""  # a category qualifier, never the conversation


@dataclass(frozen=True, slots=True)
class Annotation:
    """An accepted benign explanation, scoped to a driver and a window."""

    pid: str
    driver: str
    reason: str
    accepted_by: str
    at: datetime
    expires_on: date

    def active_on(self, day: date) -> bool:
        return day <= self.expires_on


@dataclass
class CaseBook:
    """Officer actions across runs. The persistent version is the same shape."""

    contacted: dict[str, datetime] = field(default_factory=dict)
    closed: dict[str, CloseOut] = field(default_factory=dict)
    deferred: dict[str, str] = field(default_factory=dict)
    annotations: list[Annotation] = field(default_factory=list)
    corrections: list[tuple[str, str, datetime]] = field(default_factory=list)

    # ------------------------------------------------------- Workflow C --
    def record_contact(
        self, pid: str, principal: Principal, ledger: Ledger, *, at: datetime | None = None
    ) -> datetime:
        when = at or datetime.now(UTC)
        self.contacted[pid] = when
        ledger.append(
            actor=principal.actor, action="case.contacted", subject_pid=pid,
            purpose="welfare:contact", detail={}, at=when,
        )
        return when

    def close(
        self,
        pid: str,
        outcome: str,
        principal: Principal,
        ledger: Ledger,
        *,
        note: str = "",
        at: datetime | None = None,
    ) -> CloseOut:
        """Mandatory close-out. An unrecognised outcome is refused, not coerced."""
        if outcome not in OUTCOMES:
            raise OutcomeRequired(
                f"'{outcome}' is not an outcome category. One of {list(OUTCOMES)} "
                f"is required, and the case list blocks until one is given."
            )
        when = at or datetime.now(UTC)
        record = CloseOut(pid=pid, outcome=outcome, officer=principal.actor,
                          at=when, note=note)
        self.closed[pid] = record
        ledger.append(
            actor=principal.actor, action="case.closed", subject_pid=pid,
            purpose="welfare:contact",
            detail={"outcome": outcome, "note": note}, at=when,
        )
        return record

    def defer(
        self, pid: str, reason: str, principal: Principal, ledger: Ledger,
        *, at: datetime | None = None,
    ) -> None:
        if not reason.strip():
            raise OutcomeRequired("a deferral requires a reason, and it is logged")
        self.deferred[pid] = reason
        ledger.append(
            actor=principal.actor, action="case.deferred", subject_pid=pid,
            purpose="welfare:contact", detail={"reason": reason}, at=at or datetime.now(UTC),
        )

    def blocking(self, escalated_pids: tuple[str, ...]) -> tuple[str, ...]:
        """Cases contacted but not closed. The console blocks on these."""
        return tuple(
            pid for pid in escalated_pids
            if pid in self.contacted and pid not in self.closed
        )

    # ------------------------------------------------------- Workflow G --
    def contest(
        self,
        pid: str,
        kind: ContestKind,
        driver: str,
        reason: str,
        principal: Principal,
        ledger: Ledger,
        *,
        accepted: bool = True,
        as_of: date | None = None,
        at: datetime | None = None,
    ) -> Annotation | None:
        """A person disagrees. Three outcomes, all logged, all fed to calibration."""
        when = at or datetime.now(UTC)
        today = as_of or when.date()

        if kind == "factual_error":
            self.corrections.append((pid, driver, when))
            ledger.append(
                actor=principal.actor, action="correction.requested", subject_pid=pid,
                purpose="welfare:contact",
                detail={"driver": driver, "reason": reason}, at=when,
            )
            return None

        if kind == "objects_to_analysis":
            # Handled by the consent registry (Workflow B). Recorded here only so
            # the contest path has one exit per branch and calibration sees it.
            ledger.append(
                actor=principal.actor, action="consent.narrowed", subject_pid=pid,
                purpose="welfare:self", detail={"via": "contest"}, at=when,
            )
            return None

        ledger.append(
            actor=principal.actor,
            action="annotation.accepted" if accepted else "annotation.rejected",
            subject_pid=pid,
            purpose="welfare:contact",
            detail={"driver": driver, "reason": reason,
                    "window_days": CONFOUNDER_ANNOTATION_DAYS},
            at=when,
        )
        if not accepted:
            return None
        annotation = Annotation(
            pid=pid, driver=driver, reason=reason, accepted_by=principal.actor,
            at=when, expires_on=today + timedelta(days=CONFOUNDER_ANNOTATION_DAYS),
        )
        self.annotations.append(annotation)
        return annotation

    def suppressed_drivers(self, pid: str, as_of: date) -> frozenset[str]:
        """What the next run must ignore for this person. Feeds `CaseContext`."""
        return frozenset(
            a.driver for a in self.annotations
            if a.pid == pid and a.active_on(as_of)
        )

    # ------------------------------------------------------- Workflow I --
    def realised_precision(self) -> tuple[float, int]:
        """Measured precision from officer outcomes, not from a training metric.

        `already_known` counts as neither: the concern was real but the system
        added nothing. Counting it as a success flatters the model; counting it
        as a failure punishes it for being right about somebody already being
        helped.
        """
        judged = [
            c for c in self.closed.values()
            if c.outcome in ("supported", "not_supported")
        ]
        if not judged:
            return 0.0, 0
        supported = sum(1 for c in judged if c.outcome == "supported")
        return supported / len(judged), len(judged)

    def outcome_counts(self) -> dict[str, int]:
        return {
            outcome: sum(1 for c in self.closed.values() if c.outcome == outcome)
            for outcome in OUTCOMES
        }
