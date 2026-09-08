"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Role } from "@/lib/api";
import type { RunSummary } from "@/lib/types";

/**
 * The control room: what the overnight run actually did, and the door into each
 * console.
 *
 * This page used to be a script — six numbered cards telling a presenter what
 * to say and what to point at. That script was useful and it still exists, as a
 * document, which is the right shape for it. What was wrong was putting it in
 * the running system, because a visitor reading a card about what the system
 * would show them is not being shown the system.
 *
 * So this is now instrumentation. Every number on it comes from /api/run, the
 * stage table is the real pipeline with real timings, and the four doors switch
 * role and open a console that does work. If the run did not happen, this page
 * says so instead of describing what would have been there.
 */

interface Door {
  role: Role | null;
  route: string;
  label: string;
  sees: string;
  cannot: string;
}

/* The four chairs. What each one *cannot* see is the more informative half —
 * the boundaries are the design, and they are what a visitor should leave
 * remembering. */
const DOORS: Door[] = [
  {
    role: "welfare_officer",
    route: "/officer",
    label: "Welfare officer",
    sees: "Escalated cases, gate arithmetic, identity on disclosure",
    cannot: "Refused cases · aggregate unit views · the ledger",
  },
  {
    role: "commander",
    route: "/unit",
    label: "Commanding officer",
    sees: "Sub-unit strain bands, levers, suppression counts",
    cannot: "Any individual · self-report, biometric or voice domains",
  },
  {
    role: "auditor",
    route: "/audit",
    label: "Governance auditor",
    sees: "Every verdict including refusals, hash chain, privacy budget",
    cannot: "Identities · welfare actions · anything that changes a case",
  },
  {
    role: "personnel",
    route: "/me",
    label: "Personnel",
    sees: "Own consent, own drivers, own check-in, withdrawal",
    cannot: "Anyone else, at any aggregation",
  },
];

export default function ControlRoom() {
  const router = useRouter();
  const { actor, actors, signIn } = useSession();
  const [run, setRun] = useState<RunSummary | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.run().then(setRun).catch((e) => setError(String(e.message ?? e)));
  }, []);

  const go = (door: Door) => {
    if (door.role) signIn(door.role);
    router.push(door.route);
  };

  if (error)
    return (
      <div className="banner stop" style={{ marginTop: 30 }}>
        <strong>No run to show.</strong>
        <span>{error} — start the API with ./run.sh and reload.</span>
      </div>
    );
  if (!run) return <p className="faint" style={{ paddingTop: 34 }}>Reading the run…</p>;

  const funnel = [
    { k: "screened", n: run.screened, note: "consented personnel in scope" },
    { k: "deviating", n: run.deviating, note: "at least one domain off baseline" },
    { k: "reviewed", n: run.reviewed, note: "three reviewers, in parallel" },
    { k: "escalated", n: run.escalated, note: "reached a human" },
  ];
  const rate = run.screened ? (run.escalated / run.screened) * 100 : 0;

  return (
    <>
      <div className="console-head">
        <div>
          <p className="eyebrow">
            Run {run.run_id.slice(-8)} · {run.mode} · config {run.config_version}
          </p>
          <h1 style={{ fontSize: "1.85rem" }}>Overnight run</h1>
        </div>
        <div className="spacer" />
        <div className="kpi-row">
          <div className="kpi">
            <span className="kpi-n num">{run.screened}</span>
            <span className="kpi-k">screened</span>
          </div>
          <div className="kpi">
            <span className="kpi-n num">{run.monitored}</span>
            <span className="kpi-k">watched, not named</span>
          </div>
          <div className="kpi kpi-alert">
            <span className="kpi-n num">{run.escalated}</span>
            <span className="kpi-k">escalated</span>
          </div>
          <div className="kpi">
            <span className="kpi-n num">{rate.toFixed(2)}%</span>
            <span className="kpi-k">escalation rate</span>
          </div>
        </div>
      </div>

      <div className={`banner ${run.status === "COMPLETE" ? "good" : "warn"}`}>
        <strong>{run.status}</strong>
        <span>
          {run.escalated} of {run.screened} reached a human. The other{" "}
          {run.screened - run.escalated} were screened and not named — that ratio
          is the product, and it is measured, not configured.
        </span>
      </div>
      {run.escalation_frozen && (
        <div className="banner stop">
          <strong>Escalation frozen.</strong>
          <span>{run.freeze_reason}</span>
        </div>
      )}
      {run.degraded_connectors.length > 0 && (
        <div className="banner warn">
          <strong>Degraded inputs.</strong>
          <span>
            {run.degraded_connectors.join(", ")} — those domains were excluded
            rather than imputed.
          </span>
        </div>
      )}

      <div className="grid-heat" style={{ marginTop: 16 }}>
        {/* ---- pipeline, live ---- */}
        <div className="card">
          <h2 style={{ fontSize: "1.05rem", margin: 0 }}>Pipeline</h2>
          <div className="scroller" style={{ marginTop: 12 }}>
            <table className="matrix">
              <thead>
                <tr>
                  <th>Stage</th><th>In</th><th>Out</th><th>Seconds</th><th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {run.stages.map((s) => (
                  <tr key={s.name}>
                    <th scope="row">
                      {s.name.replace(/^\d+-/, "")}{" "}
                      {s.status !== "ok" && <span className="pill hold">{s.status}</span>}
                    </th>
                    <td style={{ padding: "6px 9px" }} className="num faint">
                      {s.rows_in ? s.rows_in.toLocaleString() : "—"}
                    </td>
                    <td style={{ padding: "6px 9px" }} className="num">
                      {s.rows_out.toLocaleString()}
                    </td>
                    <td style={{ padding: "6px 9px" }} className="num faint">
                      {s.seconds.toFixed(3)}
                    </td>
                    <td style={{ padding: "6px 9px" }} className="faint">{s.detail || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="faint" style={{ marginTop: 10 }}>
            Model {run.model_version} · ledger head{" "}
            <span className="mono">{run.ledger_head.slice(0, 16)}…</span>
          </p>
        </div>

        {/* ---- funnel ---- */}
        <div className="card flat">
          <h2 style={{ fontSize: "1.05rem", margin: 0 }}>Funnel</h2>
          <div className="stack" style={{ gap: 9, marginTop: 12 }}>
            {funnel.map((f) => (
              <div key={f.k}>
                <div className="row" style={{ marginBottom: 3 }}>
                  <strong style={{ fontSize: "0.88rem" }}>{f.k}</strong>
                  <span className="spacer" />
                  <span className="num">{f.n}</span>
                </div>
                <div className="track">
                  <div
                    className="fill"
                    style={{ width: `${run.screened ? (f.n / run.screened) * 100 : 0}%` }}
                  />
                </div>
                <p className="faint" style={{ margin: "3px 0 0", fontSize: "0.79rem" }}>
                  {f.note}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ---- the four doors ---- */}
      <h2 style={{ marginTop: 28, fontSize: "1.15rem" }}>Consoles</h2>
      <p className="faint" style={{ marginTop: 2 }}>
        {actor ? `Signed in as ${actor.title}. ` : ""}
        Opening a console switches you into the role it needs. Try a door you are
        not signed in for — the refusal is explained rather than hidden.
      </p>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(258px, 1fr))", marginTop: 12 }}>
        {DOORS.map((d) => {
          const who = actors.find((a) => a.role === d.role);
          const current = actor?.role === d.role;
          return (
            <div
              className="card lifted"
              key={d.route}
              style={who ? { borderTop: `4px solid ${who.accent}` } : undefined}
            >
              <div className="row">
                <strong>{d.label}</strong>
                <span className="spacer" />
                {current && <span className="pill pass">you</span>}
              </div>
              <p className="muted" style={{ margin: "9px 0 0", fontSize: "0.88rem" }}>
                {d.sees}
              </p>
              <p className="faint" style={{ margin: "7px 0 0", fontSize: "0.82rem" }}>
                <strong>Cannot see:</strong> {d.cannot}
              </p>
              <button className="primary" style={{ marginTop: 13 }} onClick={() => go(d)}>
                Open →
              </button>
            </div>
          );
        })}
      </div>

      <div className="card rail" style={{ marginTop: 22 }}>
        <p className="eyebrow">Where the refusals live</p>
        <p className="muted" style={{ marginTop: 4 }}>
          {run.monitored} people were watched and not named tonight. They are on
          the <a href="/audit">governance console</a>, nearest-miss first, with
          the sum that fell short and what would change it. They are deliberately
          absent from the officer&rsquo;s queue: an officer handed a
          nearly-flagged list would work it, which lowers the threshold to zero.
        </p>
      </div>
    </>
  );
}
