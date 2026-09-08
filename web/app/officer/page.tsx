"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { GatePanel } from "@/components/GatePanel";
import { MindChange } from "@/components/MindChange";
import { Guard } from "@/components/Shell";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Case, Caseload } from "@/lib/types";

/**
 * The welfare officer's working surface. Operated, not read.
 *
 * This replaced an explanatory version of the same page, and the difference is
 * the whole point of the rewrite: an officer at 07:00 has a queue to clear, not
 * a design to admire. So the copy that explained *why* the system works this way
 * has moved out to a separate document, and what is left is the day's work —
 * dense, scannable, sorted, and action-first.
 *
 * Two orderings survive from the explanatory version because they are not
 * decoration:
 *
 * **The case against sits above the action buttons.** An officer who clicks
 * "contact" and then reads that 61% of the unit shows the same pattern has been
 * given an instruction, not decision support.
 *
 * **The close-out blocks the queue.** A contacted case cannot be left open, and
 * the header says how many are waiting rather than relying on memory.
 */

const OUTCOMES = [
  { key: "supported", label: "Supported", hint: "Concern real, help accepted" },
  { key: "not_supported", label: "Not supported", hint: "No welfare concern on contact" },
  { key: "already_known", label: "Already known", hint: "Unit was already helping" },
  { key: "declined_contact", label: "Declined", hint: "Chose not to engage" },
];

type Filter = "open" | "contacted" | "closed" | "all";

export default function OfficerConsolePage() {
  return (
    <Guard need="welfare_officer">
      <OfficerConsole />
    </Guard>
  );
}

function OfficerConsole() {
  const { session, actor } = useSession();
  const [run, setRun] = useState<Caseload | null>(null);
  const [error, setError] = useState("");
  const [openPid, setOpenPid] = useState<string | null>(null);
  const [detail, setDetail] = useState<Case | null>(null);
  const [identity, setIdentity] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [flash, setFlash] = useState<{ ok: boolean; text: string } | null>(null);
  const [deferReason, setDeferReason] = useState("");
  const [filter, setFilter] = useState<Filter>("open");

  const load = useCallback(() => {
    if (!session) return;
    api.caseload(session).then(setRun).catch((e) => setError(String(e.message ?? e)));
  }, [session]);

  useEffect(load, [load]);

  const counts = useMemo(() => {
    if (!run) return { open: 0, contacted: 0, closed: 0, all: 0 };
    const closed = run.closed ?? {};
    const contacted = run.contacted ?? {};
    return {
      all: run.cases.length,
      closed: run.cases.filter((c) => closed[c.pid]).length,
      contacted: run.cases.filter((c) => contacted[c.pid] && !closed[c.pid]).length,
      open: run.cases.filter((c) => !contacted[c.pid] && !closed[c.pid]).length,
    };
  }, [run]);

  const visible = useMemo(() => {
    if (!run) return [];
    const closed = run.closed ?? {};
    const contacted = run.contacted ?? {};
    return run.cases.filter((c) => {
      if (filter === "all") return true;
      if (filter === "closed") return Boolean(closed[c.pid]);
      if (filter === "contacted") return Boolean(contacted[c.pid]) && !closed[c.pid];
      return !contacted[c.pid] && !closed[c.pid];
    });
  }, [run, filter]);

  const open = async (pid: string) => {
    if (!session) return;
    setOpenPid(pid);
    setDetail(null);
    setDeferReason("");
    try {
      setDetail(await api.case(pid, session));
    } catch (e) {
      setError(String((e as Error).message));
    }
  };

  const act = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    setFlash(null);
    try {
      await fn();
      setFlash({ ok: true, text: `${label} recorded · written to the audit ledger` });
      load();
    } catch (e) {
      setFlash({ ok: false, text: `Refused — ${(e as Error).message}` });
    } finally {
      setBusy("");
    }
  };

  if (error) return <div className="banner stop" style={{ marginTop: 30 }}>{error}</div>;
  if (!run || !session)
    return <p className="faint" style={{ paddingTop: 34 }}>Loading the overnight run…</p>;

  const blocking = run.blocking ?? [];
  const frozen = run.escalation_frozen;

  return (
    <>
      {/* ---------------- header strip: the shift at a glance ---------------- */}
      <div className="console-head">
        <div>
          <p className="eyebrow">Welfare caseload · {run.as_of}</p>
          <h1 style={{ fontSize: "1.85rem" }}>Today&rsquo;s queue</h1>
        </div>
        <div className="spacer" />
        <div className="kpi-row">
          <div className="kpi">
            <span className="kpi-n num">{counts.open}</span>
            <span className="kpi-k">to review</span>
          </div>
          <div className={`kpi ${counts.contacted ? "kpi-alert" : ""}`}>
            <span className="kpi-n num">{counts.contacted}</span>
            <span className="kpi-k">awaiting close-out</span>
          </div>
          <div className="kpi">
            <span className="kpi-n num">{counts.closed}</span>
            <span className="kpi-k">closed</span>
          </div>
          <div className="kpi">
            <span className="kpi-n num">
              {run.judged_cases ? (run.realised_precision ?? 0).toFixed(2) : "—"}
            </span>
            <span className="kpi-k">measured precision</span>
          </div>
        </div>
      </div>

      {/* ---------------- run health: only when there is something wrong ---- */}
      {frozen && (
        <div className="banner stop">
          <strong>Escalation frozen.</strong>
          <span>{run.freeze_reason}</span>
        </div>
      )}
      {run.degraded_connectors.length > 0 && (
        <div className="banner warn">
          <strong>Run incomplete.</strong>
          <span>
            {run.degraded_connectors.join(", ")} returned partial records. Those
            domains are excluded — nothing was imputed, so today&rsquo;s queue is
            shorter than a complete run would produce.
          </span>
        </div>
      )}
      {blocking.length > 0 && (
        <div className="banner warn">
          <strong>{blocking.length} case(s) cannot be left open.</strong>
          <span>Record an outcome before the next run.</span>
        </div>
      )}
      {flash && (
        <div className={`banner ${flash.ok ? "good" : "warn"}`}>
          <span>{flash.text}</span>
        </div>
      )}

      {/* ---------------- filter bar ---------------- */}
      <div className="toolbar">
        {(["open", "contacted", "closed", "all"] as Filter[]).map((f) => (
          <button
            key={f}
            className={filter === f ? "primary" : ""}
            onClick={() => setFilter(f)}
          >
            {f === "open" ? "To review" : f === "contacted" ? "Awaiting close-out"
              : f === "closed" ? "Closed" : "All"}
            <span className="count-chip">{counts[f]}</span>
          </button>
        ))}
        <span className="spacer" />
        <span className="faint mono">
          {actor?.operator} · {actor?.units || "all units"} · run {run.run_id.slice(-8)}
        </span>
        <button className="ghost" onClick={load}>Refresh</button>
      </div>

      {/* ---------------- the queue ---------------- */}
      {visible.length === 0 ? (
        <div className="card flat" style={{ marginTop: 14 }}>
          <p className="muted">
            {counts.all === 0
              ? "Nothing was escalated overnight. That is a result, not an error — the evidence did not clear the gates."
              : `No cases in this view. ${counts.all} in total today.`}
          </p>
        </div>
      ) : (
        <div className="queue">
          <div className="queue-head">
            <span>Case</span>
            <span>Unit</span>
            <span>Priority</span>
            <span>Driver</span>
            <span>Action</span>
            <span>Status</span>
            <span />
          </div>
          {visible.map((c) => {
            const contacted = run.contacted?.[c.pid];
            const closed = run.closed?.[c.pid];
            const isOpen = openPid === c.pid;
            const revealed = identity[c.pid];
            return (
              <div className={`queue-item ${isOpen ? "expanded" : ""}`} key={c.pid}>
                <div className="queue-row" onClick={() => (isOpen ? setOpenPid(null) : open(c.pid))}>
                  <span className="mono cell-id">
                    {revealed ? revealed.split(" · ")[0] : `${c.pid.slice(0, 10)}…`}
                  </span>
                  <span className="faint">{c.unit_id}</span>
                  <span>
                    <span className={`sev sev-${c.override ? "acute" : c.composite >= 0.85 ? "high" : "std"}`}>
                      {c.override ? "SAME DAY" : c.composite >= 0.85 ? "HIGH" : "ROUTINE"}
                    </span>
                  </span>
                  <span className="faint cell-driver">
                    {c.gates.find((g) => g.name === "evidence")?.inputs?.domains
                      ?.split(",").slice(0, 2).join(", ") ?? "—"}
                  </span>
                  <span className="mono faint">{c.recommended[0]?.code ?? "—"}</span>
                  <span>
                    {closed ? (
                      <span className="pill pass">{closed.replace(/_/g, " ")}</span>
                    ) : contacted ? (
                      <span className="pill hold">close-out due</span>
                    ) : (
                      <span className="pill plain">new</span>
                    )}
                  </span>
                  <span className="faint">{isOpen ? "▲" : "▼"}</span>
                </div>

                {isOpen && (
                  <div className="queue-detail">
                    {/* drivers */}
                    <div className="detail-grid">
                      <section>
                        <h3>Why now</h3>
                        {detail?.risk?.drivers?.length ? (
                          <ul className="muted tight-list">
                            {detail.risk.drivers.slice(0, 3).map((d) => (
                              <li key={d.feature}>{d.plain}</li>
                            ))}
                          </ul>
                        ) : (
                          <p className="faint">
                            No model attribution this run — the case rests on the
                            deviating domains.
                          </p>
                        )}
                        {detail?.rhythm?.phrase && (
                          <p className="faint" style={{ marginTop: 8 }}>
                            <strong>Roster:</strong> {detail.rhythm.phrase}
                          </p>
                        )}
                        {detail?.horizon?.phrase && (
                          <p className="faint" style={{ marginTop: 5 }}>
                            <strong>Horizon:</strong> {detail.horizon.phrase}
                          </p>
                        )}
                      </section>

                      <section>
                        <h3>Gates</h3>
                        <GatePanel gates={c.gates} />
                      </section>
                    </div>

                    {/* the case against — above the controls, deliberately */}
                    {detail?.reviewers && (
                      <section style={{ marginTop: 18 }}>
                        <h3>Counter-argument</h3>
                        <div className="stack" style={{ gap: 8, marginTop: 8 }}>
                          {[...detail.reviewers]
                            .sort((a) => (a.reviewer === "confounder_check" ? -1 : 1))
                            .map((r) => (
                              <div
                                className={`card ${r.reviewer === "confounder_check" ? "rail" : "flat"} tight`}
                                key={r.reviewer}
                              >
                                <div className="row">
                                  <strong style={{ fontSize: "0.9rem" }}>
                                    {r.reviewer.replace(/_/g, " ")}
                                  </strong>
                                  {r.status !== "ok" && (
                                    <span className="pill hold">unavailable</span>
                                  )}
                                </div>
                                <p className="muted" style={{ marginTop: 5, fontSize: "0.9rem" }}>
                                  {r.narrative}
                                </p>
                              </div>
                            ))}
                        </div>
                      </section>
                    )}

                    {/* recommended action */}
                    {c.recommended.length > 0 && (
                      <section style={{ marginTop: 18 }}>
                        <h3>Recommended</h3>
                        {c.recommended.slice(0, 2).map((i) => (
                          <div className="card flat tight" key={i.code} style={{ marginTop: 8 }}>
                            <div className="row">
                              <strong style={{ fontSize: "0.92rem" }}>{i.title}</strong>
                              <span className="pill accent">{i.code}</span>
                              {i.authority === "mental_health" && (
                                <span className="pill stop">mental-health authority</span>
                              )}
                            </div>
                            <p className="muted" style={{ marginTop: 5, fontSize: "0.89rem" }}>
                              {i.rationale}
                            </p>
                          </div>
                        ))}
                      </section>
                    )}

                    {/* actions */}
                    <section className="action-bar">
                      {!revealed ? (
                        <button
                          className="primary" disabled={!!busy}
                          onClick={() => act("Identity disclosure", async () => {
                            const r = await api.disclose(c.pid, session);
                            setIdentity((p) => ({
                              ...p,
                              [c.pid]: `${r.identity.rank} ${r.identity.name} · ${r.identity.service_number} · ${r.identity.contact}`,
                            }));
                          })}
                        >
                          Reveal identity
                        </button>
                      ) : (
                        <span className="revealed mono">{revealed}</span>
                      )}
                      <button
                        disabled={!!busy || !!contacted}
                        onClick={() => act("Contact", () => api.contact(c.pid, session))}
                      >
                        {contacted ? "Contact recorded" : "Record contact"}
                      </button>
                      <input
                        className="input" style={{ minWidth: 200 }}
                        placeholder="Reason to defer (logged)"
                        value={deferReason}
                        onChange={(e) => setDeferReason(e.target.value)}
                      />
                      <button
                        disabled={!!busy || !deferReason.trim()}
                        onClick={() => act("Deferral", () => api.defer(c.pid, deferReason, session))}
                      >
                        Defer
                      </button>
                    </section>

                    {/* close-out */}
                    <section style={{ marginTop: 16 }}>
                      <h3>{closed ? "Closed" : "Close-out — required"}</h3>
                      {closed ? (
                        <p className="faint" style={{ marginTop: 6 }}>
                          Recorded as <strong>{closed.replace(/_/g, " ")}</strong>. Only
                          the category is stored, never what was said.
                        </p>
                      ) : (
                        <div className="outcome-row">
                          {OUTCOMES.map((o) => (
                            <button
                              key={o.key} disabled={!!busy}
                              onClick={() => act("Close-out", () => api.close(c.pid, o.key, session))}
                            >
                              <strong>{o.label}</strong>
                              <span className="faint">{o.hint}</span>
                            </button>
                          ))}
                        </div>
                      )}
                    </section>

                    {c.mind_change.length > 0 && <MindChange items={c.mind_change} />}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <p className="faint" style={{ marginTop: 22 }}>
        Escalated cases only. Cases the gates declined are not listed here and no
        identity exists for them —{" "}
        <a href="/audit">governance review</a> holds those.
      </p>
    </>
  );
}
