"""Roster rhythm: what the *order* of duty days says that their average does not.

Two jawans can work identical total hours over ninety days and be in completely
different situations — one on a settled 6-on-2-off rotation, one on scattered
blocks with no predictable break. A window mean cannot tell them apart, and
that difference is exactly what "roster rhythm" means to somebody living it.

PART 3 names a Temporal Transformer. This implementation deliberately does not
use one, and the reason is the same one that decided the tabular backend: torch
wheels are large, platform-specific, and a transferable project cannot require
the recipient to acquire a working CUDA-or-not build before anything runs. What
is implemented instead is a small set of **explicit rhythm features** —
regularity, longest unbroken run, break adequacy, block variance — computed from
the same daily series a transformer would have consumed.

That is a real trade and it is worth stating plainly: a transformer would learn
interactions these four features cannot express. What these four buy back is that
an officer can be told "your longest unbroken run was 23 days" instead of "the
sequence model scored 0.71", and the seam is a Protocol, so a torch-backed
implementation drops in behind it for anybody willing to own the deployment.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date

from samvedna.analytics.features.store import FeatureStore
from samvedna.config.windows import LONG_WINDOW_DAYS, SUSTAINABLE_RUN_DAYS

__all__ = ["RhythmFeatures", "rhythm_for", "RHYTHM_NAMES"]

RHYTHM_NAMES: tuple[str, ...] = (
    "rhythm_regularity",
    "rhythm_longest_run",
    "rhythm_break_adequacy",
    "rhythm_block_variance",
)

# A duty day, for rhythm purposes: at or above this normalised level.
ON_DUTY_LEVEL = 0.5
# A break shorter than this does not restore anybody.
ADEQUATE_BREAK_DAYS = 2


@dataclass(frozen=True, slots=True)
class RhythmFeatures:
    """What the shape of a roster says, in terms an officer can repeat aloud."""

    regularity: float          # 0..1, higher is more predictable
    longest_run_days: int      # longest unbroken stretch on duty
    break_adequacy: float      # 0..1, fraction of breaks that were long enough
    block_variance: float      # 0..1, normalised variance of duty block lengths
    observed_days: int

    def as_features(self) -> dict[str, float]:
        return {
            "rhythm_regularity": round(self.regularity, 4),
            "rhythm_longest_run": float(self.longest_run_days),
            "rhythm_break_adequacy": round(self.break_adequacy, 4),
            "rhythm_block_variance": round(self.block_variance, 4),
        }

    def phrase(self) -> str:
        if self.longest_run_days == 0:
            return f"no duty days recorded in the last {self.observed_days} days"
        unsustainable = (
            f" — beyond the {SUSTAINABLE_RUN_DAYS}-day sustainable run"
            if self.longest_run_days > SUSTAINABLE_RUN_DAYS else ""
        )
        return (
            f"longest unbroken run {self.longest_run_days} days{unsustainable}; "
            f"{self.break_adequacy:.0%} of breaks were {ADEQUATE_BREAK_DAYS} days "
            f"or longer; roster regularity {self.regularity:.2f}"
        )


def _runs(flags: list[bool]) -> tuple[list[int], list[int]]:
    """Lengths of consecutive on-duty and off-duty stretches."""
    on: list[int] = []
    off: list[int] = []
    if not flags:
        return on, off
    current, length = flags[0], 1
    for flag in flags[1:]:
        if flag == current:
            length += 1
        else:
            (on if current else off).append(length)
            current, length = flag, 1
    (on if current else off).append(length)
    return on, off


def rhythm_for(
    store: FeatureStore, pid: str, as_of: date, domain: str = "duty_roster"
) -> RhythmFeatures:
    series = store.series(pid, domain)  # type: ignore[arg-type]
    values = series.window(as_of, LONG_WINDOW_DAYS) if series else []
    if len(values) < ADEQUATE_BREAK_DAYS * 2:
        return RhythmFeatures(0.0, 0, 0.0, 0.0, len(values))

    flags = [v >= ON_DUTY_LEVEL for v in values]
    on_runs, off_runs = _runs(flags)

    longest = max(on_runs) if on_runs else 0
    adequacy = (
        sum(1 for r in off_runs if r >= ADEQUATE_BREAK_DAYS) / len(off_runs)
        if off_runs else 0.0
    )
    if len(on_runs) > 1:
        spread = statistics.pstdev(on_runs)
        mean = statistics.fmean(on_runs)
        # Coefficient of variation, saturating at 1. A roster whose block lengths
        # vary as much as their mean is not a roster anybody can plan around.
        block_variance = min(1.0, spread / mean) if mean else 0.0
    else:
        # One block, or none. Not "perfectly regular" — there is no rotation to
        # be regular about, so predictability is undefined and reads as 0.
        block_variance = 1.0 if on_runs else 0.0

    # Regularity is three things at once, and the first version conflated the
    # first two. A 61-day unbroken run scored **1.00** — perfectly predictable,
    # and the worst roster in the sample. Predictability is not sustainability,
    # so the sustainability term is separate and multiplicative rather than
    # folded into the variance.
    predictability = 1.0 - block_variance
    sustainability = (
        1.0 if longest <= SUSTAINABLE_RUN_DAYS
        else max(0.0, SUSTAINABLE_RUN_DAYS / longest)
    )
    if not on_runs:
        # Nobody was on duty in the window. There is no rhythm to report, and
        # reporting a perfect one would be worse than reporting none.
        regularity = 0.0
        adequacy = 0.0
    else:
        regularity = round(
            predictability * (0.5 + 0.5 * adequacy) * sustainability, 4
        )

    return RhythmFeatures(
        regularity=regularity,
        longest_run_days=longest,
        break_adequacy=round(adequacy, 4),
        block_variance=round(block_variance, 4),
        observed_days=len(values),
    )
