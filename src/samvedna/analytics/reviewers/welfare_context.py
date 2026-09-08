"""Welfare Context — unit norms, and what has been tried before.

Retrieval over an intervention playbook and a corpus of precedent welfare cases.

The retrieval is lexical rather than neural, and that is deliberate for v1.
A sentence-transformer would be better at paraphrase, but it is also a model
whose nearest-neighbour output nobody can check, and this reviewer's output is
read by an officer deciding whether to approach a person. Overlap on driver
tokens is worse at recall and completely transparent about why a precedent was
returned. The seam is a Protocol, so a neural retriever can be dropped in behind
the same interface once somebody is willing to own the calibration.
"""
from __future__ import annotations

from dataclasses import dataclass

from samvedna.core.interventions import PLAYBOOK
from samvedna.core.types import CaseContext, ReviewerFinding

__all__ = ["WelfareContext", "Precedent", "PRECEDENTS"]


@dataclass(frozen=True, slots=True)
class Precedent:
    """A closed welfare case, de-identified. Outcome, not narrative.

    Only the outcome category is retained from a real case — the content of a
    welfare conversation is never written to this system (Workflow D), so a
    precedent can say what was tried and whether it helped, and nothing else.
    """

    code: str
    drivers: tuple[str, ...]
    action: str
    outcome: str
    note: str


PRECEDENTS: tuple[Precedent, ...] = (
    Precedent(
        "P-001", ("leave", "duty_roster"), "WLF-LEAVE", "supported",
        "Leave sanction reviewed with the adjutant; two applications had been "
        "held pending rather than refused. Resolved within the week.",
    ),
    Precedent(
        "P-002", ("duty_roster", "workload"), "WLF-REST", "supported",
        "Rotation adjusted after 40 consecutive duty days. The pattern did not "
        "recur in the following quarter.",
    ),
    Precedent(
        "P-003", ("deployment", "transfer"), "WLF-FAMILY", "supported",
        "Third posting in eighteen months with family at the previous station. "
        "Family liaison arranged; compassionate posting review initiated.",
    ),
    Precedent(
        "P-004", ("self_report", "workload"), "WLF-COUNSEL", "already_known",
        "Unit counselling cell was already engaged. The flag added nothing and "
        "the case was closed as duplicate.",
    ),
    Precedent(
        "P-005", ("duty_roster", "leave", "workload"), "WLF-REST", "not_supported",
        "Unit was mid-deployment; the whole company showed the same pattern. "
        "Raised with the commanding officer as a rostering matter instead.",
    ),
    Precedent(
        "P-006", ("training", "workload"), "WLF-TRAINING-LOAD", "supported",
        "Two overlapping course assignments. One was deferred a cycle.",
    ),
    Precedent(
        "P-007", ("self_report",), "WLF-PEER", "declined_contact",
        "Peer-support offered and declined. Consent to welfare contact was "
        "subsequently narrowed, and that is the person's right.",
    ),
)


def _overlap(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    """Jaccard overlap on driver tokens. Transparent about why it matched."""
    left = {token for item in a for token in item.split("_")}
    right = {token for item in b for token in item.split("_")}
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


class WelfareContext:
    name = "welfare_context"

    def __init__(self, precedents: tuple[Precedent, ...] = PRECEDENTS, top_k: int = 3):
        self._precedents = precedents
        self.top_k = top_k

    def review(self, ctx: CaseContext) -> ReviewerFinding:
        devs = [d for d in ctx.deviations if ctx.consent.covers(d.domain)]
        drivers = tuple(d.domain for d in devs)
        if not drivers:
            return ReviewerFinding(
                reviewer="welfare_context",
                narrative="No consented domain deviates; no precedent applies.",
            )

        ranked = sorted(
            ((p, _overlap(drivers, p.drivers)) for p in self._precedents),
            key=lambda pair: -pair[1],
        )
        matched = [(p, score) for p, score in ranked if score > 0][: self.top_k]

        lines = []
        for precedent, score in matched:
            lines.append(
                f"{precedent.code} ({score:.0%} driver overlap, outcome: "
                f"{precedent.outcome}): {precedent.note}"
            )

        cohort = ctx.unit.cohort_size
        norm_line = (
            f"Unit strength on this roll is {cohort}. "
            f"Welfare capacity for the period is "
            f"{'available' if ctx.unit.welfare_capacity_available else 'exhausted'}."
        )

        if ctx.active_interventions:
            active = ", ".join(i.code for i in ctx.active_interventions)
            norm_line += (
                f" This person already has an active intervention ({active}); "
                "re-approaching them without concluding it is how a welfare "
                "system loses the confidence of the force."
            )

        narrative = (
            (("Comparable closed cases: " + " | ".join(lines) + ". ") if lines else
             "No comparable closed case was found for this driver combination. ")
            + norm_line
        )

        # A precedent that was NOT supported is the most useful thing this
        # reviewer can hand an officer, so it is surfaced explicitly rather than
        # averaged into a similarity score.
        cautions = tuple(
            f"{p.code} with similar drivers was closed as {p.outcome}"
            for p, _ in matched
            if p.outcome in ("not_supported", "already_known")
        )
        if cautions:
            narrative += " Caution: " + "; ".join(cautions) + "."

        return ReviewerFinding(
            reviewer="welfare_context",
            narrative=narrative,
            precedent_interventions=tuple(p.action for p, _ in matched)
            or tuple(i.code for i in PLAYBOOK[:1]),
        )
