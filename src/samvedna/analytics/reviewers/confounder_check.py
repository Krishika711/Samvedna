"""Confounder Check — the benign explanations, and the argument against the flag.

This reviewer is the one with mechanical power, and it has it for a specific
reason: it does not decide anything either, but the rules it reports are the same
rules `core/confounders.py` runs, so what it tells the officer and what moved the
consistency gate are the same facts. The narrative explains the arithmetic rather
than competing with it.

**If this reviewer is unavailable, escalation freezes to MONITOR-only for the
run** (PART 8.8). That is the correct asymmetry: without the case against, the
system has only heard one side, and a system that names a soldier having heard
one side is exactly what the design exists to prevent.
"""
from __future__ import annotations

from samvedna.config.thresholds import DATA_GAP_MISSING_FRACTION
from samvedna.core import confounders as rules
from samvedna.core.types import CaseContext, ReviewerFinding


class ConfounderCheck:
    name = "confounder_check"

    def review(self, ctx: CaseContext) -> ReviewerFinding:
        hits = rules.detect(ctx)
        devs = [d for d in ctx.deviations if ctx.consent.covers(d.domain)]

        if not hits:
            narrative = (
                "No benign explanation was found for these deviations. The unit "
                "cohort is not moving with this person, no sanctioned leave or "
                "training assignment accounts for the pattern, the prior year's "
                "same window does not show it, and record coverage is adequate."
            )
            if len(devs) < 2:
                narrative += (
                    " Note that a single deviating domain has nothing to be "
                    "consistent with, which is itself a reason for caution."
                )
            return ReviewerFinding(
                reviewer="confounder_check",
                narrative=narrative,
                domain_assessments=tuple(
                    (d.domain, "supports", "no confounder found") for d in devs
                ),
            )

        by_domain: dict[str, list[str]] = {}
        for hit in hits:
            by_domain.setdefault(hit.domain, []).append(
                f"{hit.label} (mass {hit.mass:.2f}) — {hit.detail}"
            )

        parts = [
            f"{domain}: " + "; ".join(reasons) for domain, reasons in sorted(by_domain.items())
        ]
        narrative = "The case against: " + " | ".join(parts) + "."

        if any(h.rule == "unit_op_tempo" for h in hits):
            narrative += (
                " A unit-wide pattern is a command workload matter, not an "
                "individual welfare concern. The correct action is to raise it "
                "with the commanding officer as a rostering question."
            )
        if any(h.rule == "data_gap" for h in hits):
            narrative += (
                f" More than {DATA_GAP_MISSING_FRACTION:.0%} of records are "
                "missing for at least one domain. Missingness is not evidence, "
                "and nothing has been imputed to cover it."
            )

        assessments = []
        for d in devs:
            if d.domain in by_domain:
                assessments.append(
                    (d.domain, "contradicts", "; ".join(by_domain[d.domain]))
                )
            else:
                assessments.append((d.domain, "supports", "no confounder found"))

        return ReviewerFinding(
            reviewer="confounder_check",
            narrative=narrative,
            domain_assessments=tuple(assessments),
            confounders_found=tuple(sorted({h.rule for h in hits})),
        )
