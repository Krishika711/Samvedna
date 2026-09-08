/**
 * The one place the console talks to the API.
 *
 * Role and operator travel as headers because in REPLAY there is no identity
 * provider. In a deployment these are replaced by an OIDC bearer token and the
 * API refuses the headers outright — `_principal` in `api/app.py` returns 501
 * unless the process is in REPLAY mode, so this shim cannot survive being
 * pointed at live records.
 */
import type {
  Case,
  Caseload,
  Gate,
  Health,
  LedgerEntry,
  RunSummary,
  UnitView,
} from "./types";

export type Role = "welfare_officer" | "commander" | "auditor" | "personnel";

export interface Session {
  role: Role;
  operator: string;
  units: string;
}

export const DEFAULT_SESSION: Record<Role, Session> = {
  welfare_officer: { role: "welfare_officer", operator: "WO-12", units: "" },
  commander: { role: "commander", operator: "CO-01", units: "UNIT-01" },
  auditor: { role: "auditor", operator: "AU-03", units: "" },
  personnel: { role: "personnel", operator: "SELF", units: "" },
};

/** POST with the session headers, surfacing the server's own refusal text. */
async function post<T>(path: string, session: Session, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "X-Role": session.role,
      "X-Operator": session.operator,
      "X-Units": session.units,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail ?? `${response.status}`);
  return payload as T;
}

async function get<T>(path: string, session?: Session): Promise<T> {
  const headers: Record<string, string> = {};
  if (session) {
    headers["X-Role"] = session.role;
    headers["X-Operator"] = session.operator;
    headers["X-Units"] = session.units;
  }
  const response = await fetch(path, { headers, cache: "no-store" });
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* the status alone is the message */
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => get<Health>("/api/health"),
  run: () => get<RunSummary>("/api/run"),
  caseload: (s: Session) => get<Caseload>("/api/caseload", s),
  case: (pid: string, s: Session) => get<Case>(`/api/case/${pid}`, s),
  unit: (unitId: string, s: Session) => get<UnitView>(`/api/unit/${unitId}`, s),
  heatmap: (unitId: string, s: Session) =>
    get<{
      unit_id: string; as_of: string; k: number; domains: string[];
      sub_units: string[];
      cells: { sub_unit: string; domain: string; band: string; suppressed: boolean;
               n?: number; value?: number; reason?: string }[];
      suppressed: number; next_step: string; note: string;
    }>(`/api/unit/${unitId}/heatmap`, s),
  myDrivers: (pid: string, s: Session) =>
    get<{
      pid: string; assessed: boolean; decision?: string;
      named_to_an_officer?: boolean; message: string;
      gates: { name: string; value: number; threshold: number; passed: boolean;
               formula: string }[];
      drivers: { feature: string; contribution: number; plain: string }[];
      mind_change?: { gate: string; current: number; required: number;
                      would_change_if: string[] }[];
      contest?: Record<string, string>;
    }>(`/api/me/${pid}/drivers`, s),
  refused: (s: Session) =>
    get<{
      run_id: string; as_of: string; total_refused: number;
      monitored: number; no_flag: number;
      cases: {
        pid: string; unit_id: string; decision: string; reason: string;
        composite: number; closest_miss: number;
        gates: Gate[];
        mind_change: { gate: string; current: number; required: number;
                       failed_because: string[]; would_change_if: string[];
                       recoverable: boolean }[];
      }[];
    }>("/api/refused", s),
  audit: (s: Session) =>
    get<{ verified: boolean; reason: string; entries: LedgerEntry[]; dp_budget: Record<string, number> }>(
      "/api/audit",
      s,
    ),
  contact: (pid: string, s: Session) => post(`/api/case/${pid}/contact`, s),
  close: (pid: string, outcome: string, s: Session) =>
    post(`/api/case/${pid}/close`, s, { outcome }),
  defer: (pid: string, reason: string, s: Session) =>
    post(`/api/case/${pid}/defer`, s, { reason }),
  contest: (pid: string, kind: string, driver: string, reason: string, s: Session) =>
    post(`/api/case/${pid}/contest`, s, { kind, driver, reason }),
  withdraw: (pid: string, s: Session) => post(`/api/consent/${pid}/withdraw`, s),
  disclose: async (pid: string, s: Session) => {
    const response = await fetch(`/api/case/${pid}/disclose`, {
      method: "POST",
      headers: {
        "X-Role": s.role,
        "X-Operator": s.operator,
        "X-Units": s.units,
      },
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail ?? `${response.status}`);
    return body as {
      pid: string;
      identity: {
        service_number: string;
        name: string;
        rank: string;
        unit_id: string;
        contact: string;
      };
      purpose: string;
      ledger_seq: number;
      disclosed_at: string;
    };
  },
};
