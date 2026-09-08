"""The data contracts. Each stage's output is the next stage's input.

Written first, deliberately. These frozen dataclasses are what makes the boundary
between "the model argues" and "the arithmetic decides" a type error rather than
a code review comment: a `RiskAssessment` carries a score and drivers and has no
field a verdict could be smuggled in, and a `Gate` carries every input term it
was computed from so an officer can check the sum by hand.

Nothing here imports anything below L3. No I/O, no clock, no network.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from samvedna.config.weights import DomainName, Tier

__all__ = [
    "DomainName",
    "Tier",
    "SignalRecord",
    "DomainDeviation",
    "RiskAssessment",
    "Stance",
    "ReviewerFinding",
    "GateName",
    "Gate",
    "Verdict",
    "MindChangeItem",
    "Intervention",
    "ConfounderHit",
    "InstrumentResponse",
    "ConsentState",
    "CaseContext",
    "UnitContext",
    "Decision",
]

Decision = Literal["ESCALATE", "MONITOR", "NO_FLAG", "IMMEDIATE_ESCALATE"]
GateName = Literal["evidence", "consistency", "persistence", "actionability"]
Stance = Literal["supports", "contradicts", "insufficient"]
Direction = Literal["elevated", "reduced"]


# ---------------------------------------------------------------- L1 ingest --
@dataclass(frozen=True, slots=True)
class SignalRecord:
    """One observation about one pid, already pseudonymised and normalised.

    `pid` is an HMAC of the service number under a rotating salt held in the HSM.
    A service number must never appear in this type — that is the whole reason
    pseudonymisation happens at ingest and not at the feature store.
    """

    pid: str
    domain: DomainName
    observed_at: datetime
    value: float  # normalised 0..1 within the domain
    raw_kind: str  # "leave_denied", "consecutive_duty_days", ...
    unit_id: str
    consent_scope: frozenset[DomainName] = frozenset()

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise ValueError(f"{self.raw_kind}: value {self.value} outside 0..1")


@dataclass(frozen=True, slots=True)
class InstrumentResponse:
    """A validated self-assessment, item by item.

    Item-level scores are kept because the acute-risk path is triggered by a
    specific *item* (PHQ-9 item 9), not by a total and never by a model. The
    officer never sees these; only the derived domain deviation and, for an acute
    item, the mental-health authority.
    """

    pid: str
    instrument: Literal["PHQ9", "GAD7", "MBI_GS9"]
    taken_at: datetime
    items: dict[str, int]
    total: int
    cutoff: int

    @property
    def above_cutoff(self) -> bool:
        return self.total >= self.cutoff


# ------------------------------------------------------------- L2 analytics --
@dataclass(frozen=True, slots=True)
class DomainDeviation:
    """How far this person deviates from their OWN baseline and their unit's.

    Both z-scores are carried. `z_self` is what makes the finding about a change
    in this person; `z_unit` is what lets the confounder rules notice that the
    whole unit moved together, which is a command workload problem and not an
    individual welfare flag.
    """

    domain: DomainName
    z_self: float
    z_unit: float
    direction: Direction
    windows_breached: int
    tier: Tier
    weight: float
    # Fraction of days breaching in each persistence window, keyed by window days.
    daily_breach: dict[int, float] = field(default_factory=dict)
    missing_fraction: float = 0.0


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    """A model's opinion. Not a decision, and structurally incapable of being one.

    There is no `verdict` field and no `confidence` field, on purpose: PART 14
    forbids a model emitting either, and the cheapest way to enforce that is to
    leave nowhere to put it.
    """

    pid: str
    score: float  # 0..1
    horizon_days: int
    drivers: tuple[tuple[str, float], ...]  # SHAP top-k (feature, contribution)
    model_version: str
    status: Literal["ok", "unavailable"] = "ok"


@dataclass(frozen=True, slots=True)
class ReviewerFinding:
    """One reviewer's structured argument.

    `narrative` reaches the welfare officer. It never reaches the gates — the
    gates read `domain_assessments` and `confounders_found`, which are structured
    and checkable. Prose cannot move a number in this system.
    """

    reviewer: Literal["risk_advocate", "confounder_check", "welfare_context"]
    narrative: str
    domain_assessments: tuple[tuple[DomainName, Stance, str], ...] = ()
    confounders_found: tuple[str, ...] = ()
    precedent_interventions: tuple[str, ...] = ()
    status: Literal["ok", "unavailable"] = "ok"


@dataclass(frozen=True, slots=True)
class ConfounderHit:
    """A deterministic benign explanation, with the mass it contributes."""

    rule: str
    domain: DomainName
    mass: float
    label: str
    detail: str


# --------------------------------------------------------------- L3 decision --
@dataclass(frozen=True, slots=True)
class Gate:
    """One gate, with every term it was computed from.

    `formula` is rendered with the actual numbers substituted, because the single
    highest-value thing this system can put in front of an officer is the
    arithmetic that produced the answer — not a bar, and not a percentage.
    """

    name: GateName
    value: float
    threshold: float
    passed: bool
    formula: str
    inputs: dict[str, float | bool | str]


@dataclass(frozen=True, slots=True)
class Intervention:
    """A welfare action matched to the drivers that raised the case."""

    code: str
    title: str
    rationale: str
    addresses: tuple[str, ...]  # driver keys this action speaks to
    authority: Literal["unit_welfare", "mental_health", "command"] = "unit_welfare"


@dataclass(frozen=True, slots=True)
class MindChangeItem:
    """What would change our mind about a gate that failed.

    Computed by inverting the gate, never generated by a language model. Every
    `would_change_if` entry has to be something the officer reading it could go
    and check.
    """

    gate: GateName
    current: float
    required: float
    failed_because: tuple[str, ...]
    would_change_if: tuple[str, ...]
    recoverable: bool


@dataclass(frozen=True, slots=True)
class Verdict:
    decision: Decision
    reason: str
    gates: dict[GateName, Gate]
    failed_gates: tuple[GateName, ...]
    mind_change: tuple[MindChangeItem, ...]
    composite: float  # DISPLAY ONLY — never gates anything
    recommended: tuple[Intervention, ...] = ()
    override: bool = False
    override_reason: str = ""
    config_version: str = ""

    @property
    def names_a_person(self) -> bool:
        """Only these two outcomes may ever reach L5 for re-identification."""
        return self.decision in ("ESCALATE", "IMMEDIATE_ESCALATE")


# ------------------------------------------------------- context for the gates --
@dataclass(frozen=True, slots=True)
class ConsentState:
    """Granular, revocable consent. Evaluated per run, never cached across runs."""

    pid: str
    scope: frozenset[DomainName]
    welfare_contact: bool
    status: Literal["NOT_ENROLLED", "ACTIVE", "PARTIAL", "REVOKED"]
    updated_at: datetime

    def covers(self, domain: DomainName) -> bool:
        return self.status in ("ACTIVE", "PARTIAL") and domain in self.scope


@dataclass(frozen=True, slots=True)
class UnitContext:
    """What the unit around this person looks like, for the confounder rules."""

    unit_id: str
    cohort_size: int
    # Fraction of the unit cohort deviating in the same domain and direction.
    cohort_deviating_fraction: dict[DomainName, float] = field(default_factory=dict)
    # Domains explained by an approved leave calendar entry for this pid.
    sanctioned_leave_domains: frozenset[DomainName] = frozenset()
    # Domains explained by a scheduled training assignment.
    training_domains: frozenset[DomainName] = frozenset()
    # Domains showing the same deviation in the prior year's same window.
    seasonal_domains: frozenset[DomainName] = frozenset()
    welfare_capacity_available: bool = True


@dataclass(frozen=True, slots=True)
class CaseContext:
    """Everything the pure decision layer needs, and nothing it does not.

    Note what is absent: a name, a service number, a rank, a unit name. The gates
    cannot leak an identity because they were never handed one.
    """

    pid: str
    unit_id: str
    as_of: date
    deviations: tuple[DomainDeviation, ...]
    consent: ConsentState
    unit: UnitContext
    risk: RiskAssessment | None = None
    reviewers: tuple[ReviewerFinding, ...] = ()
    active_interventions: tuple[Intervention, ...] = ()
    suppressed_drivers: frozenset[str] = frozenset()
    acute_items: tuple[str, ...] = ()
    clinician_concern: bool = False
