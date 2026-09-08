"""The other half of the accuracy question: the people it did not name.

Everything else in this system is built to avoid naming the wrong person, and
that bias is deliberate — a soldier wrongly named is a real harm and the
problem statement lists stigmatisation among its hardest risks. But a system
tuned only against false positives has an obvious failure mode, and until this
module existed SAMVEDNA had it: `calibration.propose` could only ever raise a
threshold. Given enough quiet weeks it converges on saying nothing at all, and
a welfare system that names nobody is indistinguishable from no system.

So this module measures the misses. Not by guessing: when a welfare concern
surfaces through some other route — the person self-refers, a commander refers
them manually, a medical presentation, an incident — that event is registered
here along with what SAMVEDNA's verdict for that person was at the time. The
question it answers is precise and answerable:

    Of the welfare concerns that came to light some other way, how many had we
    declined to name — and which gate declined them?

**This is not recall.** True recall needs a gold standard for everybody,
including the people nobody ever worried about, and no such thing exists
outside a research study. What this measures is *surfaced-case recall*, which
is biased toward concerns severe enough to surface. Reporting it as recall
would be an overclaim, so `MissedCaseBook.surfaced_recall` is named for what it
is and `LIMITATION` states the bias in words that survive being pasted into a
slide.

The blocking-gate histogram is the part a governance board can act on. A miss
where consistency was the blocker is a different problem from a miss where
consent was: the first is a threshold that may be too high, the second is a
person the system was never allowed to look at, and no amount of retuning
addresses it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

__all__ = [
    "LIMITATION",
    "MISSED_RATE_CEILING",
    "MIN_SURFACED_FOR_A_PROPOSAL",
    "MissedCase",
    "MissedCaseBook",
    "SurfacedReport",
]

# How a concern came to light other than through this system. Kept as a closed
# set because an open text field here would become a clinical note, and this
# module must never hold one.
Channel = Literal[
    "self_referral",       # the person asked for help themselves
    "commander_referral",  # a commander referred them by observation
    "medical",             # surfaced at a medical presentation
    "incident",            # surfaced after an incident
    "peer_concern",        # a colleague raised it
]

# What the system had decided about that person when the concern surfaced.
PriorVerdict = Literal[
    "escalated",   # we had named them — not a miss
    "monitored",   # we saw the deviation and declined to name it — a miss
    "no_flag",     # we saw nothing — a miss, and the more serious kind
    "not_enrolled",  # never in scope; not a miss, and not fixable by tuning
]

# A missed-case rate above this is the trigger to propose *loosening*. Set
# against the precision floor of 0.70 deliberately: the two together define a
# band rather than a single target, so the loop has somewhere to rest instead of
# oscillating between tightening and loosening every week.
MISSED_RATE_CEILING = 0.30
# Same reasoning as the precision side. A rate computed from four surfaced cases
# is not a rate.
MIN_SURFACED_FOR_A_PROPOSAL = 15

LIMITATION = (
    "Surfaced-case recall, not recall. The denominator counts only welfare "
    "concerns that came to light through some other channel, which is biased "
    "toward concerns severe enough to surface at all. A concern nobody ever "
    "raised is absent from both the numerator and the denominator, and no "
    "figure computed here can see it. True recall requires a gold standard for "
    "the whole cohort and is not obtainable outside a research protocol."
)


@dataclass(frozen=True, slots=True)
class MissedCase:
    """One welfare concern that surfaced other than through this system.

    Deliberately thin. A pid, a date, how it surfaced, what we had decided, and
    — only when we had declined — which gate did the declining. No description
    of the concern, no clinical detail, no free text. What is recorded here is
    enough to compute a rate and to say which gate to look at, and nothing more
    than that.
    """

    pid: str
    surfaced_on: date
    channel: Channel
    prior_verdict: PriorVerdict
    # Which gate fell short for this person on the run before the concern
    # surfaced. Empty when we had named them, or had never seen them.
    blocking_gate: str = ""
    # How far short. Zero when there is no blocking gate.
    shortfall: float = 0.0

    @property
    def was_missed(self) -> bool:
        """Did the system have a chance and decline it?

        `not_enrolled` is not a miss. A person outside scope was never assessed,
        so counting them would make the rate a measure of enrolment coverage
        rather than of the gates — two different problems with two different
        owners.
        """
        return self.prior_verdict in ("monitored", "no_flag")

    @property
    def recoverable_by_threshold(self) -> bool:
        """Could a threshold change plausibly have caught this one?

        Only the ones we actually looked at and declined on a gate. A `no_flag`
        miss means no deviation was detected at all, and lowering a gate
        threshold does not help — that is a features or coverage problem.
        """
        return self.prior_verdict == "monitored" and bool(self.blocking_gate)


@dataclass(frozen=True, slots=True)
class SurfacedReport:
    """Counts and rates. Never a case, same rule as the weekly report."""

    surfaced: int
    missed: int
    already_escalated: int
    not_enrolled: int
    by_channel: dict[str, int] = field(default_factory=dict)
    by_blocking_gate: dict[str, int] = field(default_factory=dict)
    recoverable: int = 0

    @property
    def surfaced_recall(self) -> float:
        """Of concerns we had a chance at, the share we had named.

        Denominator excludes `not_enrolled` for the reason in `was_missed`.
        """
        had_a_chance = self.missed + self.already_escalated
        if had_a_chance == 0:
            return 0.0
        return self.already_escalated / had_a_chance

    @property
    def missed_rate(self) -> float:
        had_a_chance = self.missed + self.already_escalated
        if had_a_chance == 0:
            return 0.0
        return self.missed / had_a_chance

    @property
    def enough_evidence(self) -> bool:
        return (self.missed + self.already_escalated) >= MIN_SURFACED_FOR_A_PROPOSAL

    @property
    def dominant_gate(self) -> str:
        """The gate that blocked the most recoverable misses, if one stands out.

        Returns empty unless a single gate accounts for more than half of them.
        A proposal to lower "whichever gate happened to come first" is noise
        wearing the shape of evidence.
        """
        if not self.by_blocking_gate:
            return ""
        total = sum(self.by_blocking_gate.values())
        gate, count = max(self.by_blocking_gate.items(), key=lambda kv: (kv[1], kv[0]))
        return gate if total and count / total > 0.5 else ""


class MissedCaseBook:
    """Registered misses. Append-only in practice; nothing here is edited."""

    def __init__(self) -> None:
        self._cases: list[MissedCase] = []

    def register(self, case: MissedCase) -> None:
        self._cases.append(case)

    def __len__(self) -> int:
        return len(self._cases)

    # `__len__` without `__bool__` is how an empty ledger once became falsy and
    # silently swallowed nine audit entries. Same shape, same fix.
    def __bool__(self) -> bool:
        return True

    def cases(self) -> tuple[MissedCase, ...]:
        return tuple(self._cases)

    def report(self, *, since: date | None = None) -> SurfacedReport:
        window = [c for c in self._cases if since is None or c.surfaced_on >= since]
        missed = [c for c in window if c.was_missed]
        recoverable = [c for c in window if c.recoverable_by_threshold]
        return SurfacedReport(
            surfaced=len(window),
            missed=len(missed),
            already_escalated=sum(1 for c in window if c.prior_verdict == "escalated"),
            not_enrolled=sum(1 for c in window if c.prior_verdict == "not_enrolled"),
            by_channel=dict(sorted(Counter(c.channel for c in window).items())),
            by_blocking_gate=dict(
                sorted(Counter(c.blocking_gate for c in recoverable).items())
            ),
            recoverable=len(recoverable),
        )
