"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useService } from "@/lib/useService";
import { useSession } from "@/lib/session";
import type { Health, RunSummary } from "@/lib/types";

/**
 * The main dashboard — the standing picture of the system.
 *
 * This route used to hold the explanation of how SAMVEDNA works, which is a
 * good document and the wrong front door: somebody opening the system wants to
 * know what it did last night and where to go, not to be taught the design. The
 * explanation moved intact to /about.
 *
 * Everything on this page is read live from two public endpoints. Neither
 * carries an identity — `/api/run` returns counts and stage timings, and
 * `/api/health` returns config versions and whether the audit chain verifies.
 * That is deliberate: the front door of a welfare system should be openable by
 * anybody in the unit without exposing a single person on it.
 */

export default function Dashboard() {
  const { actor, actors, signIn } = useSession();
  const { service } = useService();
  const [run, setRun] = useState<RunSummary | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [down, setDown] = useState("");

  useEffect(() => {
    Promise.all([api.run(), api.health()])
      .then(([r, h]) => { setRun(r); setHealth(h); })
      .catch((e) => setDown(String(e.message ?? e)));
  }, []);

  const rate = run && run.screened ? (run.escalated / run.screened) * 100 : 0;
  const spared = run ? run.screened - run.escalated : 0;

  return (
    <>
      {/* ---------------- command banner ---------------- */}
      <section className="command">
        <div className="command-inner">
          <div>
            <p className="flash">
              <b>SAMVEDNA</b>
              <span>·</span>
              <span>{service.abbr || "Personnel"} Welfare Monitoring</span>
              {service.ministry && (
                <>
                  <span>·</span>
                  <span>{service.ministry}</span>
                </>
              )}
            </p>
            <h1>Nobody is named until the evidence earns it.</h1>
            <p className="creed">
              The model raises the concern. The evidence must corroborate it.
              <em> The arithmetic decides.</em> A welfare officer takes the
              action.
            </p>
          </div>

          <div className="standing">
            {run ? (
              <>
                <span className="big num">{run.escalated}</span>
                <span className="of">
                  of <b>{run.screened}</b> {service.personnel_plural} reached a
                  human last night
                </span>
                <span className="note">
                  {spared.toLocaleString()} were screened and not named. That
                  ratio is the product — and it is measured, not configured.
                </span>
              </>
            ) : (
              <span className="of">{down ? "No run to report." : "Reading the run…"}</span>
            )}
          </div>
        </div>
      </section>

      {down && (
        <div className="banner stop" style={{ marginTop: 16 }}>
          <strong>The backend is not answering.</strong>
          <span>{down} — start it with <code>./run.sh</code> and reload.</span>
        </div>
      )}

      {run && (
        <>
          {/* ---------------- last night ---------------- */}
          <section className="section">
            <p className="chev">Last night · run {run.run_id.slice(-8)} · {run.as_of}</p>
            <div className="metrics" style={{ marginTop: 10 }}>
              <div className="metric">
                <span className="v">{run.screened}</span>
                <span className="k">screened</span>
              </div>
              <div className="metric">
                <span className="v">{run.deviating}</span>
                <span className="k">deviating</span>
              </div>
              <div className="metric calm">
                <span className="v">{run.monitored}</span>
                <span className="k">watched, not named</span>
              </div>
              <div className="metric lit">
                <span className="v">{run.escalated}</span>
                <span className="k">escalated</span>
              </div>
              <div className="metric">
                <span className="v">{rate.toFixed(2)}%</span>
                <span className="k">escalation rate</span>
              </div>
            </div>

            {run.escalation_frozen && (
              <div className="banner stop" style={{ marginTop: 12 }}>
                <strong>Escalation frozen.</strong>
                <span>{run.freeze_reason}</span>
              </div>
            )}
            {run.degraded_connectors.length > 0 && (
              <div className="banner warn" style={{ marginTop: 12 }}>
                <strong>Run incomplete.</strong>
                <span>
                  {run.degraded_connectors.join(", ")} returned partial records.
                  Those domains were excluded rather than imputed.
                </span>
              </div>
            )}
          </section>

          {/* ---------------- the pipeline, as a readout ---------------- */}
          <section className="section">
            <p className="chev">The night, stage by stage</p>
            <div className="stages" style={{ marginTop: 10 }}>
              {run.stages.map((s) => {
                const name = s.name.replace(/^\d+-/, "");
                return (
                  <div
                    key={s.name}
                    className={`stage-cell ${name === "gate" ? "decides" : ""} ${s.status !== "ok" ? "bad" : ""}`}
                  >
                    <span className="sn">{s.name.split("-")[0]}</span>
                    <span className="st">{name}</span>
                    <span className="sv">
                      {s.rows_out.toLocaleString()} · {s.seconds.toFixed(2)}s
                    </span>
                  </div>
                );
              })}
            </div>
            <p className="faint" style={{ marginTop: 9 }}>
              Only the last stage decides anything. Everything before it gathers
              evidence — and if the risk model is missing the run still
              completes, because the gates never needed a score.
            </p>
          </section>
        </>
      )}

      {/* ---------------- the four doors ---------------- */}
      <section className="section">
        <p className="chev">Consoles</p>
        <h2 style={{ marginTop: 4 }}>Four chairs, four different views</h2>
        <p className="muted measure">
          {actor
            ? `Signed in as ${actor.title}. Opening another console switches you into that role.`
            : "Opening a console signs you into the role it needs. Try one you are not signed in for — the refusal is explained rather than hidden."}
        </p>

        <div className="doors" style={{ marginTop: 14 }}>
          {actors.map((a) => (
            <Link
              key={a.role}
              href={a.routes[0]}
              className="door"
              style={{ borderTopColor: a.accent }}
              onClick={() => signIn(a.role)}
            >
              <div className="row">
                <span className="rank">{a.role.replace(/_/g, " ")}</span>
                <span className="spacer" />
                {actor?.role === a.role && <span className="pill pass">you</span>}
              </div>
              <h3>{a.title}</h3>
              <p className="can">{a.canSee[0]}</p>
              <p className="cant">
                <b>Cannot see:</b> {a.cannotSee[0]}
              </p>
              <span className="go">Open {a.routes[0]} →</span>
            </Link>
          ))}
        </div>
      </section>

      {/* ---------------- integrity ---------------- */}
      {health && (
        <section className="section">
          <p className="chev">Integrity</p>
          <div className="integrity" style={{ marginTop: 10 }}>
            <div className="seal">
              <span className="sk">Audit chain</span>
              <span className={`sv ${health.ledger_verified ? "ok" : "no"}`}>
                {health.ledger_verified ? "INTACT" : "BROKEN"}
              </span>
              <span className="hash">
                {health.ledger_entries} entries
                {health.ledger_reason ? ` · ${health.ledger_reason}` : ""}
              </span>
            </div>
            <div className="seal">
              <span className="sk">Mode</span>
              <span className="sv">{health.mode.toUpperCase()}</span>
              <span className="hash">
                no live service-record access in replay
              </span>
            </div>
            <div className="seal">
              <span className="sk">Config version</span>
              <span className="sv mono" style={{ fontSize: "0.85rem" }}>
                {health.config_version}
              </span>
              <span className="hash">
                thresholds:{" "}
                {Object.entries(health.thresholds)
                  .map(([g, v]) => `${g.slice(0, 4)} ${v}`)
                  .join(" · ")}
              </span>
            </div>
            {run && (
              <div className="seal">
                <span className="sk">Ledger head</span>
                <span className="sv mono" style={{ fontSize: "0.85rem" }}>
                  {run.ledger_head.slice(0, 12)}…
                </span>
                <span className="hash">
                  each entry seals the one before it
                </span>
              </div>
            )}
          </div>
        </section>
      )}

      {/* ---------------- footer rail ---------------- */}
      <section className="section">
        <div className="card rail">
          <p className="eyebrow">New to this system?</p>
          <p className="muted" style={{ marginTop: 5 }}>
            <Link href="/about">Read the overview</Link> — why it exists, the
            four gates, what runs at 02:00, the eight signals it reads, and what
            it will not do. Or open the{" "}
            <Link href="/demo">control room</Link> to watch a run end to end.
          </p>
          <p className="faint" style={{ marginTop: 8, marginBottom: 0 }}>
            Welfare support, never disciplinary action. Outputs are barred in
            software from ACR, posting, promotion and disciplinary processes.
          </p>
        </div>
      </section>
    </>
  );
}
