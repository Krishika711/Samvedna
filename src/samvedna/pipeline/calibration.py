"""Workflow I — proposals a governance board approves, and nothing that applies
itself.

The whole module is built around one sentence from PART 8.9: *nothing retrains or
re-thresholds itself.* A system that can quietly lower its own bar for naming
people is exactly the system the problem statement warns about, so `propose`
generates a change and `apply` requires a board decision that a human recorded.
There is deliberately no function that does both.

The inputs are officer outcomes (Stage 10), accepted and rejected confounder
annotations, contested flags, and per-subgroup performance. Those labels are the
only honest source of precision in production: a training AUROC describes data
the model was fitted to, and an officer typing `not_supported` describes what
happened to a real jawan.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from samvedna.config.thresholds import CONFIG_VERSION, DRIFT_PSI_FREEZE, GATE_THRESHOLDS
from samvedna.disclosure.audit import Ledger
from samvedna.pipeline.missed import (
    MISSED_RATE_CEILING,
    SurfacedReport,
)
from samvedna.pipeline.outcomes import CaseBook

__all__ = [
    "Proposal",
    "BoardDecision",
    "WeeklyReport",
    "aggregate_week",
    "propose",
    "apply_decision",
    "population_stability_index",
    "DriftStatus",
    "check_drift",
]

# A proposal is not generated from fewer closed cases than this. A threshold
# change argued from four outcomes is a change argued from noise.
MIN_OUTCOMES_FOR_A_PROPOSAL = 20
# How far a single proposal may move a threshold. Small, deliberately: a system
# that can move its own bar a long way in one step can move it a long way in one
# step in the wrong direction.
MAX_THRESHOLD_STEP = 0.05
# Realised precision below this is the trigger to propose tightening.
PRECISION_FLOOR = 0.70
# Smallest share a PSI bin is treated as having, so an empty bin does not
# divide by zero and does not silently disappear from the sum.
EMPTY_BIN_FLOOR = 1e-4


@dataclass(frozen=True, slots=True)
class WeeklyReport:
    """What the board is shown. Counts and rates, never a case."""

    outcomes: dict[str, int]
    realised_precision: float
    judged_cases: int
    annotations_accepted: int
    annotations_rejected: int
    corrections_requested: int
    subgroup: dict[str, dict[str, float]] = field(default_factory=dict)

    @property
    def enough_evidence(self) -> bool:
        return self.judged_cases >= MIN_OUTCOMES_FOR_A_PROPOSAL


@dataclass(frozen=True, slots=True)
class Proposal:
    """A generated change. **Never applied by the thing that generated it.**"""

    gate: str
    current: float
    proposed: float
    rationale: str
    evidence: dict[str, float]
    generated_at: datetime
    config_version: str = CONFIG_VERSION

    @property
    def direction(self) -> Literal["tighten", "loosen", "none"]:
        if self.proposed > self.current:
            return "tighten"
        if self.proposed < self.current:
            return "loosen"
        return "none"


@dataclass(frozen=True, slots=True)
class BoardDecision:
    """A human decision, minuted. Rejections carry a reason too."""

    proposal: Proposal
    approved: bool
    board_reference: str
    reason: str
    decided_by: str
    decided_at: datetime


def aggregate_week(book: CaseBook, subgroup: dict | None = None) -> WeeklyReport:
    precision, judged = book.realised_precision()
    return WeeklyReport(
        outcomes=book.outcome_counts(),
        realised_precision=round(precision, 4),
        judged_cases=judged,
        annotations_accepted=len(book.annotations),
        annotations_rejected=0,
        corrections_requested=len(book.corrections),
        subgroup=subgroup or {},
    )


def propose(
    report: WeeklyReport,
    *,
    at: datetime | None = None,
    surfaced: SurfacedReport | None = None,
) -> tuple[Proposal, ...]:
    """Generate threshold changes. Generating is all this function does.

    Tightening is proposed when realised precision falls below the floor.
    Loosening is proposed only on evidence of the opposite error — welfare
    concerns that surfaced through another channel after this system had
    declined to name them.

    **A quiet week is still not evidence for loosening.** That was the original
    asymmetry here and it was right as far as it went: the cost of a false
    positive is a soldier wrongly named, and a loop that relaxes its own bar
    every time nothing happens will relax it into the ground. But an asymmetry
    with no counterweight has its own failure mode — this function could only
    ever raise a threshold, so given enough quiet weeks it converges on a system
    that names nobody, which is indistinguishable from no system at all.

    `surfaced` is that counterweight, and it is a much higher bar than silence:
    somebody has to have come to harm, or close to it, through a route that
    found them when this system did not. See `pipeline.missed` for what the
    figure does and does not measure — it is surfaced-case recall, not recall.
    """
    when = at or datetime.now(UTC)
    if not report.enough_evidence:
        return ()

    proposals: list[Proposal] = []
    if report.realised_precision < PRECISION_FLOOR:
        shortfall = PRECISION_FLOOR - report.realised_precision
        step = min(MAX_THRESHOLD_STEP, round(shortfall, 3))
        for gate in ("evidence", "consistency"):
            current = GATE_THRESHOLDS[gate]
            proposals.append(
                Proposal(
                    gate=gate,
                    current=current,
                    proposed=round(min(0.95, current + step), 3),
                    rationale=(
                        f"Realised precision on closed ESCALATE cases is "
                        f"{report.realised_precision:.2f} against a floor of "
                        f"{PRECISION_FLOOR:.2f}, over {report.judged_cases} judged "
                        f"cases. Raising the {gate} threshold by {step:.3f} is the "
                        f"smallest change that addresses it."
                    ),
                    evidence={
                        "realised_precision": report.realised_precision,
                        "judged_cases": float(report.judged_cases),
                        "not_supported": float(report.outcomes.get("not_supported", 0)),
                    },
                    generated_at=when,
                )
            )

    # The other direction. Three conditions, all required, because loosening a
    # gate is the change that puts a name on a screen that would not otherwise
    # have been there.
    if (
        surfaced is not None
        and surfaced.enough_evidence
        and surfaced.missed_rate > MISSED_RATE_CEILING
        # Only a gate that actually did the blocking, and only when one gate
        # accounts for a majority of the recoverable misses. Lowering whichever
        # gate came first alphabetically is noise in the shape of evidence.
        and surfaced.dominant_gate in GATE_THRESHOLDS
        # And never while precision is also failing. Both errors high at once
        # means the model is wrong, and moving a threshold in either direction
        # trades one harm for the other instead of fixing anything.
        and report.realised_precision >= PRECISION_FLOOR
    ):
        gate = surfaced.dominant_gate
        current = GATE_THRESHOLDS[gate]
        excess = surfaced.missed_rate - MISSED_RATE_CEILING
        step = min(MAX_THRESHOLD_STEP, round(excess, 3))
        proposals.append(
            Proposal(
                gate=gate,
                current=current,
                # Floored at 0.40. Below that the gate stops being a gate, and
                # no amount of missed-case evidence justifies removing one.
                proposed=round(max(0.40, current - step), 3),
                rationale=(
                    f"{surfaced.missed} of "
                    f"{surfaced.missed + surfaced.already_escalated} welfare "
                    f"concerns that surfaced through another channel had been "
                    f"declined by this system — a missed rate of "
                    f"{surfaced.missed_rate:.2f} against a ceiling of "
                    f"{MISSED_RATE_CEILING:.2f}. The {gate} gate blocked "
                    f"{surfaced.by_blocking_gate.get(gate, 0)} of "
                    f"{surfaced.recoverable} recoverable misses. Realised "
                    f"precision is {report.realised_precision:.2f}, so there is "
                    f"headroom to lower it by {step:.3f}. This is "
                    f"surfaced-case recall and not recall: concerns that never "
                    f"surfaced are invisible to this figure."
                ),
                evidence={
                    "missed_rate": surfaced.missed_rate,
                    "surfaced_recall": surfaced.surfaced_recall,
                    "missed": float(surfaced.missed),
                    "recoverable": float(surfaced.recoverable),
                    "realised_precision": report.realised_precision,
                },
                generated_at=when,
            )
        )

    # A subgroup materially behind the rest is reported as a proposal too, but
    # the proposed change is zero: the fix for a subgroup gap is more data or a
    # different model, never a threshold that applies to everybody.
    for name, metrics in sorted(report.subgroup.items()):
        if metrics.get("positives", 0) < 3:
            continue
        if metrics.get("precision", 1.0) < PRECISION_FLOOR:
            proposals.append(
                Proposal(
                    gate=f"subgroup:{name}",
                    current=0.0,
                    proposed=0.0,
                    rationale=(
                        f"Subgroup {name} shows precision "
                        f"{metrics['precision']:.2f} against {PRECISION_FLOOR:.2f} "
                        f"overall. No threshold change is proposed — a threshold "
                        f"applies to everybody, and this is a model problem. "
                        f"Escalation for this subgroup should be reviewed directly."
                    ),
                    evidence={k: float(v) for k, v in metrics.items()},
                    generated_at=when,
                )
            )
    return tuple(proposals)


def apply_decision(
    decision: BoardDecision, ledger: Ledger, *, at: datetime | None = None
) -> dict[str, float] | None:
    """Apply an approved change, or record the rejection. Both are logged.

    Returns the new threshold mapping, or None if rejected. It does **not** mutate
    `config/thresholds.py` — a config change is a versioned release, and prior
    verdicts must stay reproducible against the version they were made under.
    """
    when = at or datetime.now(UTC)
    proposal = decision.proposal
    ledger.append(
        actor=f"governance_board:{decision.decided_by}",
        action="config.changed" if decision.approved else "verdict.recorded",
        purpose="governance:audit",
        detail={
            "gate": proposal.gate,
            "from": proposal.current,
            "to": proposal.proposed,
            "approved": decision.approved,
            "board_reference": decision.board_reference,
            "reason": decision.reason,
            "config_version": proposal.config_version,
        },
        at=when,
    )
    if not decision.approved:
        return None
    if proposal.gate.startswith("subgroup:"):
        return None
    updated = dict(GATE_THRESHOLDS)
    updated[proposal.gate] = proposal.proposed
    return updated


# ------------------------------------------------------------------- drift --
DriftStatus = Literal["ok", "frozen"]


def population_stability_index(
    baseline: list[float], current: list[float], bins: int = 10
) -> float:
    """PSI between two score distributions. Above threshold, escalation freezes.

    Standard formulation, with one addition that matters: an empty bin is floored
    rather than skipped. Skipping empty bins makes PSI *fall* when a distribution
    collapses into fewer bins, which is exactly the drift it is supposed to catch.
    """
    if not baseline or not current:
        return 0.0

    def share(values: list[float], lo: float, hi: float, last: bool) -> float:
        count = sum(1 for v in values if (lo <= v < hi) or (last and v >= hi))
        # Floor rather than skip. Skipping empty bins makes PSI *fall* when a
        # distribution collapses into fewer bins, which is exactly the drift it
        # exists to catch.
        return max(EMPTY_BIN_FLOOR, count / len(values))

    psi = 0.0
    for index in range(bins):
        lo, hi = index / bins, (index + 1) / bins
        last = index == bins - 1
        expected = share(baseline, lo, hi, last)
        observed = share(current, lo, hi, last)
        psi += (observed - expected) * math.log(observed / expected)
    return round(psi, 4)


def check_drift(
    baseline: list[float], current: list[float], ledger: Ledger | None = None
) -> tuple[DriftStatus, float, str]:
    """Freeze escalation system-wide if the model has drifted past threshold."""
    psi = population_stability_index(baseline, current)
    if psi < DRIFT_PSI_FREEZE:
        return "ok", psi, f"PSI {psi} below the {DRIFT_PSI_FREEZE} freeze threshold"
    reason = (
        f"PSI {psi} exceeds the {DRIFT_PSI_FREEZE} freeze threshold. Escalation is "
        f"frozen system-wide; MONITOR records continue. A stale model must not keep "
        f"naming people."
    )
    if ledger is not None:
        ledger.append(
            actor="system:drift_monitor",
            action="model.frozen",
            purpose="governance:audit",
            detail={"psi": psi, "threshold": DRIFT_PSI_FREEZE},
        )
    return "frozen", psi, reason
