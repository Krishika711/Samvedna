"""Risk Advocate — the strongest *supported* case for concern.

Deliberately one-sided. Its job is to make the best argument that something is
wrong, so that the Confounder Check has something real to argue against and the
officer sees both. A reviewer that hedges produces a narrative nobody can weigh.

"Supported" is doing work in that sentence: the advocate may only cite deviations
that exist, with the z-scores they actually have. It argues from the record, it
does not embellish it.
"""
from __future__ import annotations

from samvedna.config.thresholds import DEVIATION_Z_SELF
from samvedna.core.types import CaseContext, DomainDeviation, ReviewerFinding

DOMAIN_PROSE: dict[str, str] = {
    "leave": "the rate at which their leave applications are denied",
    "deployment": "time deployed away from station",
    "duty_roster": "consecutive duty days without a clear break",
    "transfer": "postings in the trailing year",
    "training": "course and training days assigned",
    "workload": "duty hours above unit establishment",
    "self_report": "a voluntary wellness self-assessment",
    "biometric": "their opt-in resting heart-rate trend",
}


def _describe(dev: DomainDeviation) -> str:
    direction = "well above" if dev.direction == "elevated" else "well below"
    sustained = (
        f", sustained across {dev.windows_breached} of the three scoring windows"
        if dev.windows_breached else ""
    )
    return (
        f"{DOMAIN_PROSE.get(dev.domain, dev.domain)} is {direction} their own "
        f"180-day baseline (z={dev.z_self:+.1f}{sustained})"
    )


class RiskAdvocate:
    name = "risk_advocate"

    def review(self, ctx: CaseContext) -> ReviewerFinding:
        devs = [d for d in ctx.deviations if ctx.consent.covers(d.domain)]
        if not devs:
            return ReviewerFinding(
                reviewer="risk_advocate",
                narrative="No consented domain deviates. There is no case to make.",
            )

        strongest = sorted(devs, key=lambda d: -abs(d.z_self))
        lines = [_describe(d) for d in strongest[:3]]
        tiers = {d.tier for d in devs}
        emphasis = ""
        if "T1" in tiers:
            emphasis = (
                " This includes a validated self-assessment, which the person "
                "volunteered — the strongest class of signal available here."
            )
        elif len(devs) >= 3:
            emphasis = (
                f" No single domain would carry this; the case rests on "
                f"{len(devs)} of them moving together."
            )

        narrative = (
            "The case for concern: " + "; ".join(lines) + "." + emphasis
        )
        assessments = tuple(
            (
                d.domain,
                "supports" if abs(d.z_self) >= DEVIATION_Z_SELF else "insufficient",
                f"z_self={d.z_self:+.2f}, z_unit={d.z_unit:+.2f}, tier {d.tier}",
            )
            for d in strongest
        )
        return ReviewerFinding(
            reviewer="risk_advocate",
            narrative=narrative,
            domain_assessments=assessments,
        )
