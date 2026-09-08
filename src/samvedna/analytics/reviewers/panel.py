"""Run the three reviewers in parallel, and fail safely when one does not return.

Parallel because they are independent and a nightly run over a lakh of personnel
cannot afford them to be serial. Isolated because the whole point of a panel is
that one member falling over must not take the argument with it.

The rule that matters is the freeze: **if Confounder Check is unavailable,
escalation is frozen to MONITOR-only for the entire run.** Not for the case — for
the run. A run that named some people before the reviewer died and none after
would be a run whose output depends on timing, which is not something anybody can
audit.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass

from samvedna.analytics.reviewers.base import REVIEWER_NAMES, Reviewer, unavailable_finding
from samvedna.analytics.reviewers.confounder_check import ConfounderCheck
from samvedna.analytics.reviewers.risk_advocate import RiskAdvocate
from samvedna.analytics.reviewers.welfare_context import WelfareContext
from samvedna.core.types import CaseContext, ReviewerFinding

__all__ = ["Panel", "PanelResult", "default_panel"]


@dataclass(frozen=True, slots=True)
class PanelResult:
    findings: tuple[ReviewerFinding, ...]

    @property
    def unavailable(self) -> tuple[str, ...]:
        return tuple(f.reviewer for f in self.findings if f.status == "unavailable")

    @property
    def freeze_escalation(self) -> bool:
        """Without the case against, the system has heard one side only."""
        return "confounder_check" in self.unavailable

    def by_name(self, name: str) -> ReviewerFinding | None:
        return next((f for f in self.findings if f.reviewer == name), None)


def default_panel() -> tuple[Reviewer, ...]:
    return (RiskAdvocate(), ConfounderCheck(), WelfareContext())


class Panel:
    def __init__(
        self,
        reviewers: tuple[Reviewer, ...] | None = None,
        *,
        timeout_s: float = 20.0,
        max_workers: int = 3,
    ) -> None:
        self._reviewers = reviewers if reviewers is not None else default_panel()
        self._timeout = timeout_s
        self._max_workers = max_workers

    def review(self, ctx: CaseContext) -> PanelResult:
        findings: dict[str, ReviewerFinding] = {}
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {
                pool.submit(reviewer.review, ctx): reviewer.name
                for reviewer in self._reviewers
            }
            for future, name in futures.items():
                try:
                    findings[name] = future.result(timeout=self._timeout)
                except FutureTimeout:
                    findings[name] = unavailable_finding(name, "timed out")
                except Exception as exc:  # a broken reviewer must not break the run
                    findings[name] = unavailable_finding(name, type(exc).__name__)

        # A reviewer that was never configured is unavailable, not absent. The
        # officer must see three panels, one of which says it did not run.
        ordered = tuple(
            findings.get(name, unavailable_finding(name, "not configured"))
            for name in REVIEWER_NAMES
        )
        return PanelResult(ordered)
