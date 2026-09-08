/** Shapes the API returns. Deliberately mirrors `core/types.py` field for field. */

export type Decision = "ESCALATE" | "IMMEDIATE_ESCALATE" | "MONITOR" | "NO_FLAG";
export type GateName = "evidence" | "consistency" | "persistence" | "actionability";

export interface Gate {
  name: GateName;
  value: number;
  threshold: number;
  passed: boolean;
  /** The formula with the actual numbers substituted. The point of the panel. */
  formula: string;
  inputs: Record<string, string>;
}

export interface MindChangeItem {
  gate: GateName;
  current: number;
  required: number;
  failed_because: string[];
  would_change_if: string[];
  recoverable: boolean;
}

export interface Intervention {
  code: string;
  title: string;
  rationale: string;
  authority: "unit_welfare" | "mental_health" | "command";
}

export interface ReviewerFinding {
  reviewer: "risk_advocate" | "confounder_check" | "welfare_context";
  status: "ok" | "unavailable";
  narrative: string;
  confounders_found: string[];
}

export interface Case {
  /** A pseudonym. There is no name field, because the API never returns one here. */
  pid: string;
  unit_id: string;
  decision: Decision;
  reason: string;
  composite: number;
  override: boolean;
  config_version: string;
  gates: Gate[];
  recommended: Intervention[];
  mind_change: MindChangeItem[];
  contacted: string | null;
  reviewers?: ReviewerFinding[];
  risk?: {
    score: number | null;
    model_version: string;
    drivers?: { feature: string; contribution: number; plain: string }[];
  };
  annotations?: unknown[];
  /** "Risk by when" — cumulative probability by horizon, in days. */
  horizon?: { by_days: Record<string, number>; phrase: string };
  /** What the order of duty days says that their average does not. */
  rhythm?: { features: Record<string, number>; phrase: string };
}

export interface Caseload {
  headline: string;
  run_id: string;
  as_of: string;
  escalation_frozen: boolean;
  freeze_reason: string;
  degraded_connectors: string[];
  unavailable_reviewers: string[];
  cases: Case[];
  /** Contacted but not closed. The console blocks on these. */
  blocking?: string[];
  closed?: Record<string, string>;
  contacted?: Record<string, string>;
  realised_precision?: number;
  judged_cases?: number;
}

export interface UnitCell {
  label: string;
  suppressed: boolean;
  reason?: string;
  n?: number;
  value?: number;
}

export interface UnitView {
  unit_id: string;
  as_of: string;
  k: number;
  cells: UnitCell[];
  suppressed: number;
  next_step: string;
  budget_remaining: number;
  note: string;
}

export interface LedgerEntry {
  seq: number;
  at: string;
  actor: string;
  action: string;
  subject_pid: string;
  unit_id: string;
  purpose: string;
  detail: Record<string, string | number | boolean>;
  prev_hash: string;
  entry_hash: string;
}

export interface Health {
  status: string;
  mode: string;
  config_version: string;
  thresholds: Record<GateName, number>;
  ledger_entries: number;
  ledger_verified: boolean;
  ledger_reason: string;
  run: string | null;
}

/** The overnight run, as the control room sees it. Public — no principal, and
 *  nothing in it resolves to a person: counts and stage timings only. */
export interface RunStage {
  name: string;
  status: string;
  rows_in: number;
  rows_out: number;
  seconds: number;
  detail: string;
}

export interface RunSummary {
  run_id: string;
  as_of: string;
  mode: string;
  status: string;
  config_version: string;
  model_version: string;
  escalation_frozen: boolean;
  freeze_reason: string;
  degraded_connectors: string[];
  unavailable_reviewers: string[];
  screened: number;
  deviating: number;
  reviewed: number;
  escalated: number;
  monitored: number;
  no_flag: number;
  cleared: number;
  ledger_head: string;
  stages: RunStage[];
}
