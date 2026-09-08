"""Domain tiering and gate weights. Deterministic; never model-assigned.

A tier is a property of the *data source*, not of a person and not of a score.
Validated self-report is T1 because the instrument is validated and the person
volunteered it; transfer frequency is T3 because it is confounded by a dozen
ordinary service reasons. No model may promote a domain's tier — the whole point
of PART 6.1 is that the weight attached to a signal is decided in advance, in
public, by people, and is the same for every jawan in the force.
"""
from __future__ import annotations

from typing import Literal, get_args

from samvedna.config.windows import (
    LONG_WINDOW_DAYS,
    PRIMARY_WINDOW_DAYS,
    SHORT_WINDOW_DAYS,
)

DomainName = Literal[
    "leave",
    "deployment",
    "duty_roster",
    "transfer",
    "training",
    "workload",
    "self_report",
    "biometric",
    "voice",
]

ALL_DOMAINS: tuple[DomainName, ...] = get_args(DomainName)

# Domains a nightly connector can pull from a records system.
#
# Voice is the exception and the distinction is load-bearing: a voice signal
# comes from a session a person chose to start, in front of them, with their
# consent given for that sitting. There is no records system to pull it from and
# there must not be one — a connector that could fetch somebody's voice
# overnight is a surveillance capability, whatever the tier says.
CONNECTOR_DOMAINS: tuple[DomainName, ...] = tuple(
    d for d in ALL_DOMAINS if d != "voice"
)
SESSION_DOMAINS: tuple[DomainName, ...] = ("voice",)

Tier = Literal["T1", "T2", "T3"]

TIER_WEIGHT: dict[Tier, float] = {
    "T1": 1.00,  # direct, consented, instrument-validated
    "T2": 0.70,  # objective organisational record
    "T3": 0.40,  # weak or heavily confounded
}

DOMAIN_TIER: dict[DomainName, Tier] = {
    "self_report": "T1",
    "leave": "T2",
    "duty_roster": "T2",
    "deployment": "T2",
    "workload": "T2",
    "transfer": "T3",
    "training": "T3",
    "biometric": "T3",
    # Voice concordance is an ADD-ON rather than a core input: the submitted
    # system reads service records, voluntary self-report and an opt-in
    # wearable, and voice was explored afterwards as a further way of
    # understanding. It is wired in as a full domain so it can corroborate, and
    # tiered so it can do nothing more than that.
    #
    # T3 is the honest placement rather than a modest one. The acoustic
    # reference bands in `analytics/voice/acoustics.py`
    # are documented, adjustable and **not clinically validated** — they encode
    # direction and rough scale from the speech literature and nothing more.
    # Tiering it T2 would give a measurement organisational-record weight it has
    # not earned. At T3 a voice gap on its own scores 0.183 against a 0.65
    # evidence threshold, so it can corroborate a case and can never make one.
    "voice": "T3",
}


def tier_of(domain: DomainName) -> Tier:
    return DOMAIN_TIER[domain]


def weight_of(domain: DomainName) -> float:
    return TIER_WEIGHT[DOMAIN_TIER[domain]]


# --- evidence gate (PART 6.2) ------------------------------------------------
# Saturation point for weighted volume: 2.4 weighted units. Chosen so that three
# T2 domains (2.10) fall just short of saturation and a T1 plus two T2 (2.40)
# reach it exactly — corroboration has to be real, not nominal.
EVIDENCE_VOLUME_SATURATION = 2.4
# Breadth asks for three independent domains before it is satisfied.
EVIDENCE_BREADTH_TARGET = 3
EVIDENCE_W_VOLUME = 0.50
EVIDENCE_W_BREADTH = 0.30
EVIDENCE_W_HAS_T1 = 0.20

# --- persistence gate (PART 6.4) ---------------------------------------------
# Weighted toward 30 days: long enough to exclude a bad week, short enough to act
# before a crisis. Must sum to 1.
PERSISTENCE_W_7D = 0.20
PERSISTENCE_W_30D = 0.45
PERSISTENCE_W_90D = 0.35

# Keyed by window length, so no module downstream builds this mapping itself.
PERSISTENCE_WEIGHTS: dict[int, float] = {
    SHORT_WINDOW_DAYS: PERSISTENCE_W_7D,
    PRIMARY_WINDOW_DAYS: PERSISTENCE_W_30D,
    LONG_WINDOW_DAYS: PERSISTENCE_W_90D,
}

# --- actionability gate (PART 6.5) -------------------------------------------
# Capacity is the single soft term: an exhausted welfare cell lowers the gate but
# must not block, because a genuine case still deserves to be queued.
ACTIONABILITY_CAPACITY_FLOOR = 0.75
ACTIONABILITY_CAPACITY_SPAN = 0.25

# --- displayed composite (PART 6.6) ------------------------------------------
# DISPLAY ONLY. A weighted geometric mean, so one weak gate visibly drags the
# number down. Never gates anything; `core/verdict.py` must not read it.
COMPOSITE_EXP_EVIDENCE = 0.30
COMPOSITE_EXP_CONSISTENCY = 0.30
COMPOSITE_EXP_PERSISTENCE = 0.25
COMPOSITE_EXP_ACTIONABILITY = 0.15
