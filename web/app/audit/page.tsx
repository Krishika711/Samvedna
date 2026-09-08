"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { GatePanel } from "@/components/GatePanel";
import { Guard } from "@/components/Shell";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { LedgerEntry } from "@/lib/types";

/**
 * The auditor's console: every verdict, including the ones nobody acted on.
 *
 * This is the only surface in the system that sees the refusals, and that
 * placement is a decision rather than an accident. An officer given the refused
 * list would work it — the whole point of a gate declining to clear is that no
 * officer is told, so handing them a "nearly flagged" queue undoes the refusal
 * and quietly lowers the threshold to zero.
 *
 * An auditor has the opposite job. They are checking whether the machine
 * refuses for defensible reasons, which means they need the near-misses most of
 * all, sorted nearest-miss first, with the arithmetic on show.
 */

type Refused = Awaited<ReturnType<typeof api.refused>>;
type Audit = Awaited<ReturnType<typeof api.audit>>;

type Tab = "refused" | "ledger" | "budget";

export default function AuditConsolePage() {
  return (
    <Guard need="auditor">
      <AuditConsole />
    </Guard>
  );
}

function AuditConsole() {
  const { session } = useSession();
  const [refused, setRefused] = useState<Refused | null>(null);
  const [audit, setAudit] = useState<Audit | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("refused");
  const [openPid, setOpenPid] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const load = useCallback(() => {
    if (!session) return;
    Promise.all([api.refused(session), api.audit(session)])
      .then(([r, a]) => { setRefused(r); setAudit(a); })
      .catch((e) => setError(String(e.message ?? e)));
  }, [session]);

  useEffect(load, [load]);

  const entries = useMemo(() => {
    if (!audit) return [];
    const q = query.trim().toLowerCase();
    const rows = [...audit.entries].sort((a, b) => b.seq - a.seq);
    if (!q) return rows;
    return rows.filter((e) =>
      [e.actor, e.action, e.subject_pid, e.unit_id, e.purpose]
        .join(" ").toLowerCase().includes(q),
    );
  }, [audit, query]);

  if (error) return <div className="banner stop" style={{ marginTop: 30 }}>{error}</div>;
  if (!refused || !audit) return <p className="faint" style={{ paddingTop: 34 }}>Loading governance view…</p>;

  const budget = audit.dp_budget ?? {};
  const spent = Number(budget.spent ?? 0);
  const total = Number(budget.total ?? 0);

  return (
    <>
      <div className="console-head">
        <div>
          <p className="eyebrow">Governance · run {refused.run_id.slice(-8)} · {refused.as_of}</p>
          <h1 style={{ fontSize: "1.85rem" }}>Assurance</h1>
        </div>
        <div className="spacer" />
        <div className="kpi-row">
          <div className="kpi">
            <span className="kpi-n num">{refused.total_refused}</span>
            <span className="kpi-k">refused</span>
          </div>
          <div className="kpi">
            <span className="kpi-n num">{refused.monitored}</span>
            <span className="kpi-k">monitor only</span>
          </div>
          <div className="kpi">
            <span className="kpi-n num">{audit.entries.length}</span>
            <span className="kpi-k">ledger entries</span>
          </div>
          <div className={`kpi ${audit.verified ? "" : "kpi-alert"}`}>
            <span className="kpi-n num" style={{ fontSize: "1.1rem", paddingTop: 5 }}>
              {audit.verified ? "INTACT" : "BROKEN"}
            </span>
            <span className="kpi-k">hash chain</span>
          </div>
        </div>
      </div>

      {!audit.verified && (
        <div className="banner stop">
          <strong>Chain verification failed.</strong>
          <span>{audit.reason} — treat every disclosure after the break as unproven.</span>
        </div>
      )}

      <div className="toolbar">
        <button className={tab === "refused" ? "primary" : ""} onClick={() => setTab("refused")}>
          Refusals <span className="count-chip">{refused.cases.length}</span>
        </button>
        <button className={tab === "ledger" ? "primary" : ""} onClick={() => setTab("ledger")}>
          Ledger <span className="count-chip">{audit.entries.length}</span>
        </button>
        <button className={tab === "budget" ? "primary" : ""} onClick={() => setTab("budget")}>
          Privacy budget
        </button>
        <span className="spacer" />
        <button className="ghost" onClick={load}>Refresh</button>
      </div>

      {/* ---------------- refusals ---------------- */}
      {tab === "refused" && (
        refused.cases.length === 0 ? (
          <div className="card flat"><p className="muted">No refusals in this run.</p></div>
        ) : (
          <div className="queue">
            <div className="queue-head" style={{ gridTemplateColumns: "1.1fr 0.7fr 1fr 1.4fr 0.8fr 0.9fr 24px" }}>
              <span>Subject</span><span>Unit</span><span>Verdict</span>
              <span>Blocked by</span><span>Nearest miss</span><span>Recoverable</span><span />
            </div>
            {refused.cases.map((c) => {
              const isOpen = openPid === c.pid;
              const recoverable = c.mind_change.some((m) => m.recoverable);
              return (
                <div className={`queue-item ${isOpen ? "expanded" : ""}`} key={c.pid}>
                  <div
                    className="queue-row"
                    style={{ gridTemplateColumns: "1.1fr 0.7fr 1fr 1.4fr 0.8fr 0.9fr 24px" }}
                    onClick={() => setOpenPid(isOpen ? null : c.pid)}
                  >
                    <span className="mono cell-id">{c.pid.slice(0, 10)}…</span>
                    <span className="faint">{c.unit_id}</span>
                    <span>
                      <span className={`pill ${c.decision === "MONITOR" ? "hold" : "plain"}`}>
                        {c.decision}
                      </span>
                    </span>
                    <span className="faint cell-driver">{c.reason}</span>
                    <span className="num">{c.closest_miss.toFixed(3)}</span>
                    <span>
                      <span className={`pill ${recoverable ? "hold" : "plain"}`}>
                        {recoverable ? "yes" : "structural"}
                      </span>
                    </span>
                    <span className="faint">{isOpen ? "▲" : "▼"}</span>
                  </div>
                  {isOpen && (
                    <div className="queue-detail">
                      <div className="detail-grid">
                        <section>
                          <h3>Gate arithmetic</h3>
                          <GatePanel gates={c.gates} />
                        </section>
                        <section>
                          <h3>What would change the verdict</h3>
                          {c.mind_change.length === 0 ? (
                            <p className="faint">Nothing within the current window.</p>
                          ) : (
                            c.mind_change.map((m) => (
                              <div className="card flat tight" key={m.gate} style={{ marginTop: 8 }}>
                                <div className="row">
                                  <strong style={{ fontSize: "0.9rem" }}>{m.gate}</strong>
                                  <span className="mono faint">
                                    {m.current.toFixed(3)} → needs {m.required.toFixed(2)}
                                  </span>
                                </div>
                                <ul className="tight-list muted" style={{ marginTop: 5 }}>
                                  {m.would_change_if.map((w) => <li key={w}>{w}</li>)}
                                </ul>
                              </div>
                            ))
                          )}
                          <p className="faint" style={{ marginTop: 9 }}>
                            Computed by inverting the failed gate, not written by a
                            language model. It is the threshold arithmetic run
                            backwards, so it cannot describe a route that would not
                            in fact clear the gate.
                          </p>
                        </section>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )
      )}

      {/* ---------------- ledger ---------------- */}
      {tab === "ledger" && (
        <>
          <div className="toolbar" style={{ paddingTop: 0 }}>
            <input
              className="input" style={{ minWidth: 280 }}
              placeholder="Filter by actor, action, unit or subject"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <span className="faint">{entries.length} shown</span>
          </div>
          <div className="ledger">
            <div className="ledger-row" style={{ background: "var(--paper-2)", fontWeight: 650 }}>
              <span>#</span><span>Actor · action</span><span>Subject · purpose</span><span>Entry hash</span>
            </div>
            {entries.slice(0, 120).map((e: LedgerEntry) => (
              <div className="ledger-row" key={e.seq}>
                <span className="chain-n">{e.seq}</span>
                <span>
                  <strong>{e.actor}</strong>
                  <br />
                  <span className="faint">{e.action.replace(/_/g, " ")} · {e.at.slice(0, 19)}</span>
                </span>
                <span>
                  <span className="mono">{e.subject_pid ? `${e.subject_pid.slice(0, 10)}…` : "—"}</span>
                  <br />
                  <span className="faint">{e.unit_id || "—"} · {e.purpose}</span>
                </span>
                <span className="hash mono">{e.entry_hash.slice(0, 24)}…</span>
              </div>
            ))}
          </div>
          <p className="faint" style={{ marginTop: 12 }}>
            Append-only. Each entry carries the hash of the one before it, so a
            deleted or edited row breaks verification for everything after it. A
            failed write aborts the disclosure it was recording — there is no
            path to an unlogged identity release.
          </p>
        </>
      )}

      {/* ---------------- budget ---------------- */}
      {tab === "budget" && (
        <div className="grid grid-2">
          <div className="card">
            <p className="eyebrow">Differential privacy budget</p>
            <div className="meter" style={{ marginTop: 12 }}>
              <div
                className="meter-fill"
                style={{ width: `${total ? Math.min(100, (spent / total) * 100) : 0}%` }}
              />
            </div>
            <p className="muted" style={{ marginTop: 10 }}>
              <strong className="num">{spent.toFixed(1)}ε</strong> spent of{" "}
              <strong className="num">{total.toFixed(1)}ε</strong>.
            </p>
            <ul className="tight-list muted" style={{ marginTop: 8 }}>
              {Object.entries(budget)
                .filter(([k]) => k !== "spent" && k !== "total")
                .map(([k, v]) => (
                  <li key={k}>{k.replace(/_/g, " ")}: <span className="num">{Number(v).toFixed(2)}</span></li>
                ))}
            </ul>
          </div>
          <div className="card flat">
            <p className="eyebrow">Why a budget at all</p>
            <p className="muted">
              Aggregate views carry calibrated noise. Noise alone is not enough:
              fresh noise on every refresh averages back to the truth, so
              repeated views of the same cell are served from a release cache
              and charged once. The budget is what stops a determined reader
              from reconstructing an individual out of group statistics.
            </p>
            <p className="faint" style={{ marginTop: 8 }}>
              One unit heat map costs roughly 24ε of the {total.toFixed(0)}ε
              budget. When it is exhausted, aggregate views stop being served —
              individual welfare decisions are unaffected.
            </p>
          </div>
        </div>
      )}
    </>
  );
}
