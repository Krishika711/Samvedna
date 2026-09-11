"""The nightly pipeline. Ten stages, in order, each one auditable and retryable.

This is PART 7 as code. It runs in-process here rather than under Airflow, and
the stages are written so that the Airflow DAG is a thin wrapper: each is a pure
function of (context in, context out) with its own timing, row counts and status,
which is exactly what an Airflow task needs to report.

    [0] TRIGGER   [1] INGEST    [2] PROTECT   [3] FEATURES  [4] DEVIATE
    [5] SCORE     [6] REVIEW    [7] GATE      [8] MATCH     [9] DISCLOSE
    [10] LEARN

**The invariant that governs every stage: each degradation moves the system
toward saying less.** A failed connector removes a domain from the evidence. An
unavailable Confounder Check freezes escalation for the whole run. Model drift
freezes it system-wide. None of them ever lower a bar.

Stage 9 (DISCLOSE) is deliberately *not* in this module. Re-identification lives
in L5 and is called from the orchestrator with an authenticated officer's
credentials — a batch job has no purpose binding and therefore no right to a
name.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from samvedna.analytics.features.deviation import deviations_for, unit_deviating_fractions
from samvedna.analytics.features.store import FeatureStore
from samvedna.analytics.models.sequence import rhythm_for
from samvedna.analytics.models.survival import DiscreteHazard, load_survival
from samvedna.analytics.models.tabular import (
    TabularModel,
    features_for,
    load_model,
    unavailable,
)
from samvedna.analytics.reviewers.panel import Panel
from samvedna.config.thresholds import CONFIG_VERSION
from samvedna.config.windows import BASELINE_LAG_DAYS, BASELINE_WINDOW_DAYS
from samvedna.core.machine import assert_transition
from samvedna.core.types import CaseContext, DomainDeviation, UnitContext
from samvedna.core.verdict import decide
from samvedna.disclosure.audit import Ledger
from samvedna.disclosure.consent import ConsentRegistry
from samvedna.ingest.normalise import normalise
from samvedna.ingest.pseudonymise import Pseudonymiser
from samvedna.pipeline.record import CaseRecord, RunRecord, StageRecord

__all__ = ["NightlyRun", "run_nightly", "PULL_DAYS"]

# How far back the connectors are asked to reach: enough for the lagged baseline
# plus the longest scored window.
PULL_DAYS = BASELINE_WINDOW_DAYS + BASELINE_LAG_DAYS


@dataclass
class NightlyRun:
    """One night's work. Every stage appends to `record` before returning."""

    connectors: tuple
    pseudonymiser: Pseudonymiser
    consent: ConsentRegistry
    ledger: Ledger
    as_of: date
    mode: str = "replay"
    store: FeatureStore = field(default_factory=FeatureStore)
    panel: Panel = field(default_factory=Panel)
    model: TabularModel | None = None
    survival: DiscreteHazard | None = None
    model_dir: str = "artefacts/models"
    drift_exceeded: bool = False
    record: RunRecord = field(init=False)
    horizons: dict = field(default_factory=dict, init=False)
    rhythms: dict = field(default_factory=dict, init=False)
    _states: dict[str, str] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.record = RunRecord(
            run_id=f"run-{self.as_of:%Y%m%d}-{uuid.uuid4().hex[:8]}",
            as_of=self.as_of,
            started_at=datetime.now(UTC),
            mode=self.mode,  # type: ignore[arg-type]
            config_version=CONFIG_VERSION,
        )

    # ------------------------------------------------------------ plumbing --
    def _stage(self, name: str, rows_in: int):
        started = datetime.now(UTC)

        def close(rows_out: int, status: str = "ok", detail: str = "") -> None:
            self.record.stages.append(
                StageRecord(
                    name=name,
                    started_at=started,
                    finished_at=datetime.now(UTC),
                    rows_in=rows_in,
                    rows_out=rows_out,
                    status=status,  # type: ignore[arg-type]
                    detail=detail,
                )
            )

        return close

    def _advance(self, pid: str, to: str) -> None:
        """Every state change is checked. An illegal transition raises."""
        current = self._states.get(pid, "OBSERVED")
        if current != to:
            assert_transition(current, to)  # type: ignore[arg-type]
        self._states[pid] = to

    # -------------------------------------------------------------- stages --
    def stage_1_ingest(self):
        close = self._stage("1-ingest", 0)
        results = tuple(c.pull(self.as_of, PULL_DAYS) for c in self.connectors)
        degraded = tuple(r.domain for r in results if r.degraded)
        rows = sum(len(r.rows) for r in results)
        close(rows, "partial" if degraded else "ok",
              "; ".join(r.detail for r in results if r.degraded))
        self.record.degraded_connectors = degraded
        return results

    def stage_2_protect(self, results):
        """Pseudonymise, then consent-filter. The identifier stops here."""
        close = self._stage("2-protect", sum(len(r.rows) for r in results))
        report = normalise(results, self.pseudonymiser, self.consent.state_for)
        close(
            report.rows_out,
            "ok",
            f"dropped {report.dropped_no_consent} rows without consent, "
            f"{report.dropped_not_enrolled} not enrolled",
        )
        return report

    def stage_3_features(self, report):
        close = self._stage("3-features", len(report.records))
        self.store.upsert(report.records)
        for pid in self.store.pids():
            self._states.setdefault(pid, "OBSERVED")
        close(len(self.store.pids()), "ok", f"{len(self.store.pids())} pids in the store")
        return self.store

    def stage_4_deviate(self, report):
        close = self._stage("4-deviate", len(self.store.pids()))
        by_pid: dict[str, tuple[DomainDeviation, ...]] = {}
        for pid in self.store.pids():
            devs = deviations_for(
                self.store, pid, self.as_of, connector_missing=report.missing_fraction
            )
            by_pid[pid] = devs
            if devs:
                self._advance(pid, "DEVIATING")
        units = {self.store.unit_of(pid) or "" for pid in self.store.pids()}
        fractions = {
            unit_id: unit_deviating_fractions(self.store, unit_id, self.as_of, by_pid)
            for unit_id in units
        }
        deviating = sum(1 for d in by_pid.values() if d)
        close(deviating, "ok", f"{deviating} candidate pids")
        return by_pid, fractions

    def stage_5_score(self, by_pid):
        """The model is an input. If it is missing, the run continues.

        Three estimates come out of this stage and none of them decides
        anything: a calibrated risk score, a time-to-event horizon, and the
        rhythm of the person's roster. The horizon is what makes a case
        schedulable — "an even chance within 30 days" is a diary entry, where a
        score of 0.71 is not — and the rhythm is what a window mean cannot say,
        because two jawans working identical hours are in different situations
        if one is on a settled rotation and one is not.
        """
        candidates = [pid for pid, devs in by_pid.items() if devs]
        close = self._stage("5-score", len(candidates))
        if self.model is None:
            self.model = load_model(self.model_dir)
        if self.survival is None:
            self.survival = load_survival(self.model_dir)

        # Roster rhythm needs no model at all — it is arithmetic over the duty
        # series — so it is computed whether or not anything else loaded.
        self.rhythms = {
            pid: rhythm_for(self.store, pid, self.as_of) for pid in candidates
        }

        scores = {}
        if self.model is None:
            for pid in candidates:
                scores[pid] = unavailable(pid)
                self._advance(pid, "SCORED")
            close(0, "partial", "no risk model available; gates do not require one")
            return scores

        self.record.model_version = self.model.version
        for pid in candidates:
            row = features_for(self.store, pid, self.as_of)
            scores[pid] = self.model.score(pid, row)
            if self.survival is not None:
                self.horizons[pid] = self.survival.estimate(pid, row)
            self._advance(pid, "SCORED")
        close(
            len(scores),
            "ok",
            f"model {self.model.version}"
            + (f", survival {self.survival.version}" if self.survival else
               ", no survival model"),
        )
        return scores

    def stage_6_review(self, contexts):
        close = self._stage("6-review", len(contexts))
        findings = {}
        unavailable_reviewers: set[str] = set()
        for pid, ctx in contexts.items():
            result = self.panel.review(ctx)
            findings[pid] = result
            unavailable_reviewers.update(result.unavailable)
            self._advance(pid, "REVIEWED")
        self.record.unavailable_reviewers = tuple(sorted(unavailable_reviewers))
        if "confounder_check" in unavailable_reviewers:
            self.record.escalation_frozen = True
            self.record.freeze_reason = (
                "Confounder Check unavailable: the system has heard only the case "
                "for concern, so escalation is frozen to MONITOR-only for this run"
            )
        if self.drift_exceeded:
            self.record.escalation_frozen = True
            self.record.freeze_reason = (
                (self.record.freeze_reason + "; ") if self.record.freeze_reason else ""
            ) + "model drift beyond threshold: escalation frozen system-wide"
            self.ledger.append(
                actor="system:drift_monitor", action="model.frozen",
                purpose="governance", detail={"reason": "drift beyond threshold"},
            )
        close(
            len(findings),
            "partial" if unavailable_reviewers else "ok",
            ", ".join(sorted(unavailable_reviewers)),
        )
        return findings

    def stage_7_gate(self, contexts, findings, scores):
        close = self._stage("7-gate", len(contexts))
        for pid, ctx in contexts.items():
            verdict = decide(ctx, escalation_frozen=self.record.escalation_frozen)
            self._advance(pid, "GATED")
            self._advance(
                pid,
                "ESCALATED" if verdict.names_a_person
                else "MONITORED" if verdict.decision == "MONITOR"
                else "CLEARED",
            )
            self.ledger.append(
                actor="system:gate_engine",
                action="verdict.recorded",
                subject_pid=pid,
                unit_id=ctx.unit_id,
                purpose="welfare:screening",
                detail={
                    "decision": verdict.decision,
                    "config_version": verdict.config_version,
                    "failed_gates": ",".join(verdict.failed_gates),
                    "composite": round(verdict.composite, 4),
                    "frozen": self.record.escalation_frozen,
                },
            )
            self.record.cases.append(
                CaseRecord(
                    pid=pid,
                    unit_id=ctx.unit_id,
                    state=self._states[pid],
                    verdict=verdict,
                    # Kept so a self-assessment submitted during the day can be
                    # decided against the same evidence the night used, rather
                    # than waiting for the next run.
                    ctx=ctx,
                    reviewers=findings[pid].findings,
                    risk_score=scores[pid].score if scores.get(pid) else None,
                    model_version=scores[pid].model_version if scores.get(pid) else "",
                    drivers=scores[pid].drivers if scores.get(pid) else (),
                    horizon=dict(self.horizons[pid].by_horizon)
                    if pid in self.horizons else {},
                    horizon_phrase=self.horizons[pid].phrase()
                    if pid in self.horizons else "",
                    rhythm_phrase=self.rhythms[pid].phrase()
                    if pid in self.rhythms else "",
                    rhythm=self.rhythms[pid].as_features()
                    if pid in self.rhythms else {},
                )
            )
        # Everybody with no deviating domain is cleared, and recorded as such —
        # a person the system looked at and had nothing to say about is a result.
        for pid in self.store.pids():
            if pid not in contexts:
                self.record.cases.append(
                    CaseRecord(pid=pid, unit_id=self.store.unit_of(pid) or "",
                               state="CLEARED", verdict=None)
                )
        close(self.record.escalated, "ok",
              f"{self.record.escalated} escalated, {self.record.count('MONITOR')} monitored")


def build_contexts(run: NightlyRun, by_pid, fractions, scores) -> dict[str, CaseContext]:
    """Assemble the pure decision-layer input. Nothing below L3 goes in."""
    contexts: dict[str, CaseContext] = {}
    for pid, devs in by_pid.items():
        if not devs:
            continue
        unit_id = run.store.unit_of(pid) or ""
        state = run.consent.state_for(pid)
        if state is None:
            continue
        contexts[pid] = CaseContext(
            pid=pid,
            unit_id=unit_id,
            as_of=run.as_of,
            deviations=devs,
            consent=state,
            unit=UnitContext(
                unit_id=unit_id,
                cohort_size=len(run.store.pids_in_unit(unit_id)),
                cohort_deviating_fraction=fractions.get(unit_id, {}),
            ),
            risk=scores.get(pid),
        )
    return contexts


def run_nightly(
    *,
    connectors,
    pseudonymiser: Pseudonymiser,
    consent: ConsentRegistry,
    ledger: Ledger,
    as_of: date,
    mode: str = "replay",
    panel: Panel | None = None,
    model_dir: str = "artefacts/models",
    drift_exceeded: bool = False,
) -> RunRecord:
    """Stages 0-8. Disclosure (stage 9) is L5 and is not called from a batch job."""
    run = NightlyRun(
        connectors=tuple(connectors),
        pseudonymiser=pseudonymiser,
        consent=consent,
        ledger=ledger,
        as_of=as_of,
        mode=mode,
        panel=panel or Panel(),
        model_dir=model_dir,
        drift_exceeded=drift_exceeded,
    )
    ledger.append(
        actor="system:scheduler", action="run.started", purpose="welfare:nightly",
        detail={"run_id": run.record.run_id, "mode": mode,
                "config_version": CONFIG_VERSION},
    )

    results = run.stage_1_ingest()
    report = run.stage_2_protect(results)
    run.stage_3_features(report)
    by_pid, fractions = run.stage_4_deviate(report)
    scores = run.stage_5_score(by_pid)
    contexts = build_contexts(run, by_pid, fractions, scores)
    findings = run.stage_6_review(contexts)
    run.stage_7_gate(contexts, findings, scores)

    run.record.finish()
    entry = ledger.append(
        actor="system:scheduler",
        action="run.completed" if run.record.status == "COMPLETE" else "run.partial",
        purpose="welfare:nightly",
        detail={
            "run_id": run.record.run_id,
            "screened": run.record.screened,
            "deviating": run.record.deviating,
            "escalated": run.record.escalated,
            "status": run.record.status,
        },
    )
    run.record.ledger_head = entry.entry_hash
    return run.record
