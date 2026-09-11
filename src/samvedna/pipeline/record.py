"""Run records — what the pipeline did, in a form an auditor can replay.

A run record is the unit of reproducibility. It names the config version, the
model version, which connectors degraded, the funnel counts at every stage, and
every case verdict with its gate values. Given a run record and the fixtures, a
reviewing officer can rebuild exactly what an officer saw that morning.

Note what a run record does **not** contain: a name, a service number, or a
self-report answer. It is safe to hand to an auditor whole.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal

from samvedna.core.types import CaseContext, Decision, ReviewerFinding, Verdict

__all__ = ["CaseRecord", "RunRecord", "StageRecord", "RunStatus"]

RunStatus = Literal["RUNNING", "COMPLETE", "PARTIAL", "FAILED"]


@dataclass(frozen=True, slots=True)
class StageRecord:
    name: str
    started_at: datetime
    finished_at: datetime
    rows_in: int
    rows_out: int
    status: Literal["ok", "partial", "failed"] = "ok"
    detail: str = ""

    @property
    def seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


@dataclass(frozen=True, slots=True)
class CaseRecord:
    """One pid's journey through one run. No identity, ever."""

    pid: str
    unit_id: str
    state: str
    verdict: Verdict | None
    reviewers: tuple[ReviewerFinding, ...] = ()
    risk_score: float | None = None
    model_version: str = ""
    # SHAP attributions, kept so they can be shown to the **person** and not
    # only to the officer. A system that explains itself to the people acting on
    # it and not to the people it acts on has not explained itself.
    drivers: tuple[tuple[str, float], ...] = ()
    # "Risk by when", not just "risk". A welfare officer schedules things, and
    # a horizon is a diary entry where a score is not.
    horizon: dict[int, float] = field(default_factory=dict)
    horizon_phrase: str = ""
    # What the *order* of duty days says that their average does not.
    rhythm_phrase: str = ""
    rhythm: dict[str, float] = field(default_factory=dict)
    # The exact facts that produced `verdict`, kept so the case can be decided
    # again when new evidence arrives during the day.
    #
    # A nightly batch was the only thing that ever created a verdict, so the
    # inputs could be thrown away once it had. Then a jawan submitted a
    # self-assessment at 11:00 and there was no way to reconsider their case
    # until 02:00 the next morning — which is a strange thing for a system whose
    # whole purpose is noticing sooner. Holding the context makes an intra-day
    # re-decision possible without re-running the pipeline for 240 people.
    #
    # It carries no identity. See `CaseContext` — that is the point of it.
    ctx: CaseContext | None = None

    @property
    def decision(self) -> Decision | Literal["CLEARED"]:
        return self.verdict.decision if self.verdict else "CLEARED"

    @property
    def composite(self) -> float:
        return self.verdict.composite if self.verdict else 0.0


@dataclass
class RunRecord:
    run_id: str
    as_of: date
    started_at: datetime
    mode: Literal["live", "replay"]
    config_version: str
    status: RunStatus = "RUNNING"
    finished_at: datetime | None = None
    model_version: str = "unavailable"
    escalation_frozen: bool = False
    freeze_reason: str = ""
    degraded_connectors: tuple[str, ...] = ()
    unavailable_reviewers: tuple[str, ...] = ()
    stages: list[StageRecord] = field(default_factory=list)
    cases: list[CaseRecord] = field(default_factory=list)
    ledger_head: str = ""

    # -------------------------------------------------------- the funnel --
    @property
    def screened(self) -> int:
        return len(self.cases)

    @property
    def deviating(self) -> int:
        return sum(1 for c in self.cases if c.decision != "CLEARED")

    @property
    def reviewed(self) -> int:
        return sum(1 for c in self.cases if any(r.status == "ok" for r in c.reviewers))

    def count(self, decision: str) -> int:
        return sum(1 for c in self.cases if c.decision == decision)

    @property
    def escalated(self) -> int:
        return self.count("ESCALATE") + self.count("IMMEDIATE_ESCALATE")

    @property
    def headline(self) -> str:
        """The line at the top of the officer's console, every morning."""
        return (
            f"Overnight: {self.screened:,} screened · {self.deviating} deviating · "
            f"{self.reviewed} reviewed · {self.escalated} escalated"
        )

    def caseload(self) -> tuple[CaseRecord, ...]:
        """ESCALATE cases only, ranked by composite.

        The ranking uses the display composite, which is the one place it is
        allowed to matter — ordering a queue is not deciding anything. Acute
        overrides sort first regardless of composite.
        """
        cases = [c for c in self.cases if c.verdict and c.verdict.names_a_person]
        cases.sort(
            key=lambda c: (c.decision != "IMMEDIATE_ESCALATE", -c.composite)
        )
        return tuple(cases)

    def monitored(self) -> tuple[CaseRecord, ...]:
        return tuple(c for c in self.cases if c.decision == "MONITOR")

    def finish(self, at: datetime | None = None) -> None:
        self.finished_at = at or datetime.now(UTC)
        if self.status == "RUNNING":
            self.status = "PARTIAL" if (
                self.degraded_connectors or self.unavailable_reviewers
            ) else "COMPLETE"

    def to_summary(self) -> dict:
        """Safe to hand to an auditor whole — no identity in it anywhere."""
        return {
            "run_id": self.run_id,
            "as_of": self.as_of.isoformat(),
            "mode": self.mode,
            "status": self.status,
            # The units this run covers. Organisational structure, not personal
            # data — the same identifiers already appear in the audit ledger and
            # on the commander's heat map.
            #
            # It is here because the console needs it and had been guessing.
            # The role scopes were hardcoded to "UNIT-01,UNIT-02"; units were
            # later renamed to carry their service abbreviation (CRPF-01), and
            # the welfare officer console silently showed an empty caseload
            # because it was asking about units that no longer existed. Deriving
            # the scope from the run means the two cannot drift apart again.
            "units": sorted({c.unit_id for c in self.cases if c.unit_id}),
            "config_version": self.config_version,
            "model_version": self.model_version,
            "escalation_frozen": self.escalation_frozen,
            "freeze_reason": self.freeze_reason,
            "degraded_connectors": list(self.degraded_connectors),
            "unavailable_reviewers": list(self.unavailable_reviewers),
            "screened": self.screened,
            "deviating": self.deviating,
            "reviewed": self.reviewed,
            "escalated": self.escalated,
            "monitored": self.count("MONITOR"),
            "no_flag": self.count("NO_FLAG"),
            "cleared": self.count("CLEARED"),
            "ledger_head": self.ledger_head,
            "stages": [
                {"name": s.name, "status": s.status, "rows_in": s.rows_in,
                 "rows_out": s.rows_out, "seconds": round(s.seconds, 3),
                 "detail": s.detail}
                for s in self.stages
            ],
        }
