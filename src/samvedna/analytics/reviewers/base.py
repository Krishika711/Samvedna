"""The reviewer contract, and the rule that keeps reviewers out of the decision.

Three reviewers argue about a case in parallel. None of them can move a number.
What they produce is a `ReviewerFinding`: prose for the officer, plus *structured*
facts — domain assessments and confounders found — and only the structured half
is ever read by anything that computes.

An auditing model's opinion is not a defence for attaching a name to a soldier;
a confounder rule that fired on a fact somebody can go and check is. So the
reviewers here are rule- and retrieval-based, run on-premise, and are wired so
that the worst thing a broken one can do is make the system say *less*.

**No external LLM API.** PART 1 and PART 10 forbid external processing of this
data class, and there is no endpoint field anywhere in this package to configure
one into.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from samvedna.core.types import CaseContext, ReviewerFinding

__all__ = ["Reviewer", "unavailable_finding", "REVIEWER_NAMES"]

REVIEWER_NAMES = ("risk_advocate", "confounder_check", "welfare_context")


@runtime_checkable
class Reviewer(Protocol):
    name: str

    def review(self, ctx: CaseContext) -> ReviewerFinding: ...


def unavailable_finding(name: str, detail: str = "") -> ReviewerFinding:
    """The honest output when a reviewer fails.

    Never a fabricated narrative. A reviewer that invents its finding when it
    cannot run is worse than one that is absent, because absence is visible and
    invention is not.
    """
    return ReviewerFinding(
        reviewer=name,  # type: ignore[arg-type]
        narrative=(
            f"{name.replace('_', ' ')} did not complete for this case"
            + (f": {detail}" if detail else "")
            + ". No finding is available and none has been assumed."
        ),
        status="unavailable",
    )
