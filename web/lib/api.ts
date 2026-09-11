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

export type Role = "welfare_officer" | "commander" | "auditor" | "personnel"
  | "mental_health_authority";

export interface Session {
  role: Role;
  operator: string;
  units: string;
}

/**
 * Fallback sessions for components that act without a signed-in role.
 *
 * The unit-scoped roles carry **no** unit literal on purpose. An empty scope is
 * now refused by the API rather than treated as universal — it used to read
 * every unit in the force, which is fail-open on the axis that decides who may
 * see a name. Anything needing an officer or commander scope must obtain the
 * real units, which `sessionForRun` below does.
 *
 * `commander` previously carried `units: "UNIT-01"`, and that literal went
 * stale the moment units were renamed to carry a service abbreviation.
 */
export const DEFAULT_SESSION: Record<Role, Session> = {
  welfare_officer: { role: "welfare_officer", operator: "WO-12", units: "" },
  commander: { role: "commander", operator: "CO-01", units: "" },
  auditor: { role: "auditor", operator: "AU-03", units: "" },
  personnel: { role: "personnel", operator: "SELF", units: "" },
  mental_health_authority: {
    role: "mental_health_authority",
    operator: "MHA-1",
    // Force-wide, not unit-scoped: an acute referral routes to a clinician
    // centrally, and scoping it to a battalion would make a jawan's
    // referral depend on which unit happened to have one assigned.
    units: "",
  },
};

/** An officer session scoped to the units the current run covers. */
export async function sessionForRun(role: Role): Promise<Session> {
  const base = DEFAULT_SESSION[role];
  if (role !== "welfare_officer" && role !== "commander") return base;
  try {
    const run = await api.run();
    const units = run.units ?? [];
    if (units.length === 0) return base;
    return {
      ...base,
      units: role === "commander" ? units[0] : units.slice(0, 2).join(","),
    };
  } catch {
    return base;
  }
}

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
  /** Record consent against the exact text the person read. The receipt in
   *  the response is the server's, not the browser's — it is the thing that
   *  answers "what did they actually agree to" when that is challenged. */
  consent: (
    body: { pid: string; locale: string; scope: string[]; welfare_contact: boolean },
    s: Session,
  ) =>
    post<{
      status: string;
      locale: string;
      text_version: string;
      content_hash: string;
      review_status: string;
      recorded_at: string;
      domains: string[];
      welfare_contact: boolean;
    }>("/api/consent", s, body),
  withdraw: (pid: string, s: Session) => post(`/api/consent/${pid}/withdraw`, s),
  /** Submit a completed self-assessment. Scored on the server: the browser's
   *  arithmetic is not trusted for a clinical instrument. */
  assessment: (pid: string, items: number[], s: Session) =>
    post<{
      pid: string;
      total: number;
      cutoff: number;
      acute: boolean;
      acute_route: {
        routed_to: string;
        acknowledge_by: string;
        message: string;
        resources: { who: string; how: string }[];
      } | null;
      note: string;
      decision_before: string;
      decision: string;
      named_to_an_officer: boolean;
      gates: { name: string; value: number; threshold: number; passed: boolean; formula: string }[];
      mind_change: { gate: string; current: number; required: number; would_change_if: string[] }[];
    }>(`/api/me/${pid}/assessment`, s, { items }),
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
