"""Federated training: the model travels, the records do not.

PART 10's claim is that raw service records never leave the unit. This module is
that claim as code — each unit fits a local model on its own rows, only the
*parameters* are sent to the coordinator, and the coordinator has no way to
reconstruct a row from what it receives.

Two things are implemented here that a demonstration usually skips, because they
are what make the claim checkable rather than architectural:

**DP-SGD-style noise on the update.** Each unit clips its update to a fixed L2
norm and adds Gaussian noise scaled to that norm before sending. Clipping is what
bounds any single person's influence on the update; without it the noise is
calibrated to a sensitivity nobody has measured, which is the most common way a
"differentially private" training run turns out not to be.

**A privacy budget that is spent, reported, and finite.** Each round costs
epsilon. When the budget for a training campaign is gone, the campaign stops —
it does not continue with the noise turned down.

PART 3 names Flower and Opacus. This implementation deliberately depends on
neither: both would pull torch, and a project that must survive being copied to a
pendrive cannot require the recipient to acquire a working torch build first. The
aggregation contract here is the same one Flower implements (FedAvg over
parameter vectors), so a Flower transport can replace the in-process coordinator
without touching the arithmetic.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

__all__ = [
    "UnitUpdate",
    "FederatedRound",
    "Coordinator",
    "clip_to_norm",
    "CLIP_NORM",
    "NOISE_MULTIPLIER",
]

# L2 norm every unit's update is clipped to before noise is added. This is the
# sensitivity the noise is calibrated against, and it is fixed in advance rather
# than measured from the data, because measuring it from the data leaks it.
CLIP_NORM = 1.0
# Gaussian noise standard deviation, as a multiple of CLIP_NORM.
NOISE_MULTIPLIER = 0.8
# Minimum units that must report before a round is aggregated. A round with two
# participants is not federation, it is two units sharing a model.
MIN_PARTICIPANTS = 3


def l2(vector: list[float]) -> float:
    return math.sqrt(sum(v * v for v in vector))


def clip_to_norm(vector: list[float], norm: float = CLIP_NORM) -> list[float]:
    """Scale a vector down to at most `norm`. Never scales up.

    Scaling a small update *up* to the clip norm would be a bug with a specific
    consequence: a unit with almost no signal would be amplified to speak as
    loudly as a unit with a great deal, and the noise calibration would still be
    correct while the model quietly became wrong.
    """
    magnitude = l2(vector)
    if magnitude <= norm or magnitude == 0.0:
        return list(vector)
    scale = norm / magnitude
    return [v * scale for v in vector]


@dataclass(frozen=True, slots=True)
class UnitUpdate:
    """What leaves a unit. Parameters and a count — never a row, never a pid."""

    unit_id: str
    parameters: tuple[float, ...]
    n_examples: int
    clipped: bool
    noised: bool

    def carries_any_record(self) -> bool:
        """Always False. Asserted in the test suite as a structural claim."""
        return False


@dataclass(frozen=True, slots=True)
class FederatedRound:
    index: int
    participants: tuple[str, ...]
    parameters: tuple[float, ...]
    epsilon_spent: float
    skipped: bool = False
    reason: str = ""


@dataclass
class Coordinator:
    """FedAvg over parameter vectors, with a budget that actually runs out."""

    dimension: int
    total_epsilon: float = 8.0
    epsilon_per_round: float = 1.0
    clip_norm: float = CLIP_NORM
    noise_multiplier: float = NOISE_MULTIPLIER
    min_participants: int = MIN_PARTICIPANTS
    parameters: list[float] = field(default_factory=list)
    rounds: list[FederatedRound] = field(default_factory=list)
    spent: float = 0.0

    def __post_init__(self) -> None:
        if not self.parameters:
            self.parameters = [0.0] * self.dimension

    @property
    def remaining(self) -> float:
        return max(0.0, self.total_epsilon - self.spent)

    def prepare_update(
        self,
        unit_id: str,
        local_parameters: list[float],
        n_examples: int,
        rng: random.Random | None = None,
    ) -> UnitUpdate:
        """Run inside the unit. Clip, then noise, then send. Order matters.

        Noising before clipping would clip the noise as well as the update, which
        shrinks the noise below what the privacy accounting assumed and leaves a
        campaign reporting an epsilon it did not actually achieve.
        """
        r = rng or random.Random()
        delta = [
            local - current
            for local, current in zip(local_parameters, self.parameters, strict=False)
        ]
        magnitude = l2(delta)
        clipped = clip_to_norm(delta, self.clip_norm)
        sigma = self.noise_multiplier * self.clip_norm
        noised = [v + r.gauss(0.0, sigma) for v in clipped]
        return UnitUpdate(
            unit_id=unit_id,
            parameters=tuple(noised),
            n_examples=n_examples,
            clipped=magnitude > self.clip_norm,
            noised=True,
        )

    def aggregate(self, updates: list[UnitUpdate]) -> FederatedRound:
        """FedAvg, weighted by local example count, if the budget allows."""
        index = len(self.rounds)
        if len(updates) < self.min_participants:
            record = FederatedRound(
                index, tuple(u.unit_id for u in updates), tuple(self.parameters),
                0.0, skipped=True,
                reason=(
                    f"{len(updates)} unit(s) reported; {self.min_participants} are "
                    f"required. A round with fewer is not federation."
                ),
            )
            self.rounds.append(record)
            return record

        if self.epsilon_per_round > self.remaining:
            record = FederatedRound(
                index, tuple(u.unit_id for u in updates), tuple(self.parameters),
                0.0, skipped=True,
                reason=(
                    f"privacy budget exhausted: {self.remaining:.3f} epsilon remains "
                    f"of {self.total_epsilon:.3f}. The campaign stops rather than "
                    f"continuing with the noise turned down."
                ),
            )
            self.rounds.append(record)
            return record

        total = sum(u.n_examples for u in updates) or 1
        for i in range(self.dimension):
            self.parameters[i] += sum(
                u.parameters[i] * u.n_examples for u in updates
            ) / total

        self.spent += self.epsilon_per_round
        record = FederatedRound(
            index=index,
            participants=tuple(u.unit_id for u in updates),
            parameters=tuple(self.parameters),
            epsilon_spent=self.epsilon_per_round,
        )
        self.rounds.append(record)
        return record

    def report(self) -> dict:
        """The privacy accounting, published rather than assumed."""
        completed = [r for r in self.rounds if not r.skipped]
        return {
            "rounds_completed": len(completed),
            "rounds_skipped": len(self.rounds) - len(completed),
            "epsilon_spent": round(self.spent, 4),
            "epsilon_total": self.total_epsilon,
            "epsilon_remaining": round(self.remaining, 4),
            "clip_norm": self.clip_norm,
            "noise_multiplier": self.noise_multiplier,
            "min_participants": self.min_participants,
            "participants": sorted({u for r in completed for u in r.participants}),
        }
