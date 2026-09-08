"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { Caseload } from "@/lib/types";
import { DEFAULT_SESSION, api } from "@/lib/api";

/**
 * The overview page, written for somebody who has not seen the system before.
 *
 * It leads with last night's real funnel rather than a slogan, because the most
 * persuasive fact about this system is the ratio — hundreds screened, a handful
 * named — and that is legible in one line.
 */

const SCALE = [
  {
    figure: "654",
    label: "CAPF suicides",
    note: "2018–2022",
    tone: "stop",
  },
  {
    figure: "~1 in 3 days",
    label: "average interval",
    note: "between CAPF suicides",
    tone: "accent",
  },
  {
    figure: "50,155",
    label: "resigned or took VRS",
    note: "in five years",
    tone: "",
  },
  {
    figure: "~10 lakh+",
    label: "personnel addressable",
    note: "CAPF and Armed Forces",
    tone: "mid",
  },
];

const GATES = [
  {
    name: "Evidence",
    threshold: "0.65",
    asks: "Is there enough corroborated signal to be talking about a person at all?",
    guard: "One domain alone can never clear it. The arithmetic will not allow it.",
  },
  {
    name: "Consistency",
    threshold: "0.70",
    asks: "Do the signals agree, or is one anomaly shouting?",
    guard: "A unit deployment, sanctioned leave or a records gap pushes this down.",
  },
  {
    name: "Persistence",
    threshold: "0.60",
    asks: "Sustained, or a bad week?",
    guard: "Weighted to 30 days: long enough to exclude a rough patch, short enough to act.",
  },
  {
    name: "Actionability",
    threshold: "0.50",
    asks: "Is there a welfare action that fits and is not already being taken?",
    guard: "Three hard vetoes. No consent to contact forces this to exactly zero.",
  },
];

const AUDIENCES = [
  {
    who: "Personnel",
    sees: "their own data only",
    gets: "Early support before a crisis, and dignity preserved — no name leaves the system on weak evidence. They can see the same reasons the officer saw, and disagree with them.",
  },
  {
    who: "Welfare officers",
    sees: "escalated cases in their unit",
    gets: "A ranked, explained caseload instead of manual observation, with a recommended intervention attached and the argument against the flag shown first.",
  },
  {
    who: "Commanders",
    sees: "unit aggregates only",
    gets: "Fatigue and workload heat maps for rebalancing rosters and leave — never individual psychological data, and no drill-down exists to build one.",
  },
  {
    who: "The organisation",
    sees: "governance and audit",
    gets: "Evidence-based welfare planning, resource allocation and posting-cycle design, with every access and verdict reviewable.",
  },
];

const PHASES = [
  [
    "Phase 1",
    "Pilot — one battalion",
    "Retrospective data only. Shadow mode: the gates run and every verdict is recorded, but no alert is issued to anybody. Enforced by the dispatcher, not by operators remembering.",
  ],
  [
    "Phase 2",
    "Sector rollout",
    "Live alerts to welfare officers. Thresholds calibrated against real officer outcomes rather than a training metric.",
  ],
  [
    "Phase 3",
    "Force-wide",
    "Federated training across units. Raw records never leave the unit; only clipped, noised parameters do.",
  ],
];

const DOMAINS = [
  { name: "Self-assessment", tier: "T1", note: "Validated instrument, volunteered by the person" },
  { name: "Leave pattern", tier: "T2", note: "Applications denied, leave cancelled" },
  { name: "Duty roster", tier: "T2", note: "Consecutive days without a clear break" },
  { name: "Deployment", tier: "T2", note: "Time deployed away from station" },
  { name: "Workload", tier: "T2", note: "Duty hours above unit establishment" },
  { name: "Transfer", tier: "T3", note: "Postings in the trailing year" },
  { name: "Training", tier: "T3", note: "Course and training days assigned" },
  { name: "Biometric", tier: "T3", note: "Opt-in resting heart-rate trend" },
];

const PIPELINE = [
  ["01", "Ingest", "Seven service-record connectors pull leave, roster, deployment, workload, transfer, training, self-report."],
  ["02", "Protect", "Service number becomes a pseudonym, then the consent filter runs. No identifier goes past this line."],
  ["03", "Features", "Personal and unit baselines over 7, 30, 90 and 180 days."],
  ["04", "Deviate", "Who has moved from their own baseline — not from a fixed threshold everyone is measured against."],
  ["05", "Score", "The risk model runs. If it is missing the night continues; the gates do not need it."],
  ["06", "Review", "Three reviewers argue in parallel: the case for, the case against, and what was tried before."],
];

export default function Overview() {
  const [run, setRun] = useState<Caseload | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .caseload(DEFAULT_SESSION.welfare_officer)
      .then(setRun)
      .catch((e) => setError(String(e.message ?? e)));
  }, []);

  const figures = run?.headline.match(/[\d,]+/g) ?? [];
  const [screened, deviating] = figures;
  const named = run?.cases.length ?? 0;
  const watched = Math.max(0, Number((deviating ?? "0").replace(/,/g, "")) - named);

  return (
    <>
      <div className="hero">
        <div className="hero-inner">
          <p className="eyebrow">
            Smart India Hackathon 2026 · PS 26186 · Team CodeZila
          </p>
          <h1>
            Evidence-Gated Stress &amp;
            <br />
            Welfare Intelligence
          </h1>
          <p className="hero-quote">
            &ldquo;It flags a soldier only when the evidence earns it.&rdquo;
          </p>
          <p className="lede">
            SAMVEDNA finds early indicators of stress and burnout among CAPF and
            Armed Forces personnel, from records the force already holds plus
            voluntary self-assessment. Then it does the unusual part: it refuses
            to hand over a name unless four separate arithmetic tests all clear.
          </p>
          <div className="row" style={{ marginTop: 10 }}>
            <Link href="/demo" className="hero-cta">
              Take the guided walkthrough →
            </Link>
            <Link href="/signin" className="hero-cta ghost">
              Sign in as a role
            </Link>
          </div>
        </div>
      </div>

      {error && (
        <div className="banner warn">
          <strong>Backend not reachable.</strong>
          <span>
            Start it with <code>uv run samvedna serve</code>. Every figure on
            this page comes from a live run.
          </span>
        </div>
      )}

      {run && (
        <div className="stack">
          <div className="headline">{run.headline}</div>
          <div className="grid grid-4">
            <div className="stat mid">
              <span className="n num">{screened ?? "—"}</span>
              <span className="k">screened overnight</span>
              <span className="sub">every consenting person in the force</span>
            </div>
            <div className="stat">
              <span className="n num">{deviating ?? "—"}</span>
              <span className="k">deviating</span>
              <span className="sub">moved from their own baseline</span>
            </div>
            <div className="stat pass">
              <span className="n num">{watched}</span>
              <span className="k">watched, not named</span>
              <span className="sub">the evidence did not hold up</span>
            </div>
            <div className="stat accent">
              <span className="n num">{named}</span>
              <span className="k">named to an officer</span>
              <span className="sub">after all four gates cleared</span>
            </div>
          </div>
          <p className="faint">
            Live figures from run <code>{run.run_id}</code>, as of {run.as_of}.
          </p>
        </div>
      )}

      <section className="section">
        <p className="eyebrow">Why this exists</p>
        <h2>The scale of the problem</h2>
        <div className="grid grid-4">
          {SCALE.map((s) => (
            <div className={`stat ${s.tone}`} key={s.label}>
              <span className="n num">{s.figure}</span>
              <span className="k">{s.label}</span>
              <span className="sub">{s.note}</span>
            </div>
          ))}
        </div>
        <p className="faint measure">
          Today stress is identified by manual observation and self-reporting, so
          intervention arrives late. Sources: PRS India Standing Committee on
          Home Affairs; Ministry of Home Affairs Demand for Grants analysis.
        </p>
      </section>

      <section className="section">
        <p className="eyebrow">The idea</p>
        <h2>A risk score is not a decision</h2>
        <div className="grid grid-2">
          <div className="stack">
            <p className="muted">
              Published machine-learning models for burnout reach roughly AUROC
              0.72 on personnel-record data. Deploy a raw score like that across
              ten lakh personnel and you name thousands of people wrongly — each
              one a soldier told, in effect, that a computer thinks something is
              wrong with them.
            </p>
            <p className="muted">
              So the score is not allowed to be the answer. It is one input to an
              arithmetic layer that a reviewing officer, an auditor or a judge
              can check by hand.
            </p>
          </div>
          <div className="card rail">
            <p style={{ fontFamily: "var(--serif)", fontSize: "1.24rem", lineHeight: 1.45 }}>
              The model raises the concern. The evidence must corroborate it.{" "}
              <span style={{ color: "var(--accent)" }}>
                The arithmetic makes the decision.
              </span>{" "}
              A welfare officer takes the action.
            </p>
          </div>
        </div>
      </section>

      <section className="section">
        <p className="eyebrow">The mechanism</p>
        <h2>Four gates, and all four must clear</h2>
        <div className="grid grid-2">
          {GATES.map((gate) => (
            <div className="card lifted" key={gate.name}>
              <div className="row" style={{ marginBottom: 8 }}>
                <h3>{gate.name}</h3>
                <span className="spacer" />
                <span className="pill accent mono">≥ {gate.threshold}</span>
              </div>
              <p className="muted" style={{ marginBottom: 10 }}>{gate.asks}</p>
              <p className="faint">{gate.guard}</p>
            </div>
          ))}
        </div>
        <p className="faint measure">
          Every value comes with the formula that produced it, with the actual
          numbers substituted. That is what turns &ldquo;the computer says
          0.694&rdquo; into something an officer can defend to the person sitting
          opposite them.
        </p>
      </section>

      <section className="section">
        <p className="eyebrow">One night, end to end</p>
        <h2>What runs at 02:00</h2>
        <div className="card">
          <div className="seq">
            {PIPELINE.map(([n, what, does]) => (
              <div className="seq-item" key={n}>
                <span className="n">{n}</span>
                <span className="what">{what}</span>
                <span className="does">{does}</span>
              </div>
            ))}
            <div className="seq-item key">
              <span className="n">07</span>
              <span className="what">Gate</span>
              <span className="does">
                Four gates, then the verdict. This is the only stage that decides
                anything.
              </span>
              <span className="count">{named} escalated</span>
            </div>
          </div>
        </div>
        {run && (
          <div className="card">
            <div className="funnel">
              {[
                ["screened", Number((screened ?? "0").replace(/,/g, "")), false],
                ["deviating", Number((deviating ?? "0").replace(/,/g, "")), false],
                ["watched, not named", watched, false],
                ["named to an officer", named, true],
              ].map(([label, value, final]) => {
                const total = Number((screened ?? "1").replace(/,/g, "")) || 1;
                return (
                  <div className="rung" key={String(label)}>
                    <span className="lab">{label as string}</span>
                    <span
                      className={`bar ${final ? "final" : ""}`}
                      style={{ width: `${Math.max(0.4, (Number(value) / total) * 100)}%` }}
                    />
                    <span className="n">{String(value)}</span>
                  </div>
                );
              })}
            </div>
            <p className="faint" style={{ marginTop: 14 }}>
              {watched} people were watched and not named. That is not the system
              failing to find them — it is the system declining to accuse them on
              evidence that did not hold up.
            </p>
          </div>
        )}
      </section>

      <section className="section">
        <p className="eyebrow">What it reads</p>
        <h2>Eight signals, weighted before anyone looks at them</h2>
        <p className="measure muted">
          A signal&rsquo;s weight is fixed by what kind of source it is, in
          configuration, in advance. No model can promote a domain into mattering
          more than it was approved to matter.
        </p>
        <div className="card">
          <div className="scroller">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 200 }}>Signal</th>
                  <th style={{ width: 80 }}>Tier</th>
                  <th>What it actually is</th>
                </tr>
              </thead>
              <tbody>
                {DOMAINS.map((d) => (
                  <tr key={d.name}>
                    <td style={{ fontWeight: 600 }}>{d.name}</td>
                    <td>
                      <span
                        className={`pill ${d.tier === "T1" ? "pass" : d.tier === "T2" ? "mid" : ""}`}
                      >
                        {d.tier}
                      </span>
                    </td>
                    <td className="muted">{d.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="section">
        <p className="eyebrow">Add-on · beyond the submitted scope</p>
        <h2>Voice concordance — a further way of understanding</h2>
        <div className="card rail">
          <p className="muted measure">
            An extension explored after submission, not part of the core system.
            It measures the voice underneath a claim — where somebody says they
            are managing and the voice underneath says otherwise — and it is
            offered as an additional way of understanding, never as a
            replacement for the record-based signals above.
          </p>
          <div className="grid grid-3" style={{ marginTop: 16 }}>
            <div>
              <h3 style={{ fontSize: "0.98rem" }}>Consented session only</h3>
              <p className="faint" style={{ marginTop: 5 }}>
                No connector can fetch a voice overnight. It comes from a sitting
                the person chose to start.
              </p>
            </div>
            <div>
              <h3 style={{ fontSize: "0.98rem" }}>Tier 3, like a wearable</h3>
              <p className="faint" style={{ marginTop: 5 }}>
                The acoustic bands are not clinically validated. A voice signal
                alone scores 0.183 against a 0.65 threshold.
              </p>
            </div>
            <div>
              <h3 style={{ fontSize: "0.98rem" }}>No audio, ever</h3>
              <p className="faint" style={{ marginTop: 5 }}>
                Each window is measured and discarded. Six numbers survive a
                sitting; the transcript does not.
              </p>
            </div>
          </div>
          <div className="row" style={{ marginTop: 18 }}>
            <Link href="/voice" className="pill accent" style={{ padding: "6px 14px" }}>
              See the add-on →
            </Link>
          </div>
        </div>
      </section>

      <section className="section">
        <p className="eyebrow">Where to look</p>
        <h2>See it work</h2>
        <div className="grid grid-2">
          <Link href="/officer" className="card lifted">
            <h3>Welfare officer console</h3>
            <p className="muted" style={{ margin: "8px 0 0" }}>
              The overnight caseload. Open a case and click a gate bar — the
              formula opens with the real numbers in it, and the argument{" "}
              <em>against</em> the flag sits above the action buttons.
            </p>
          </Link>
          <Link href="/unit" className="card lifted">
            <h3>Commander unit view</h3>
            <p className="muted" style={{ margin: "8px 0 0" }}>
              Aggregates only, k-anonymous and noised. Try opening another
              unit&rsquo;s view — it refuses, in the software rather than the
              interface.
            </p>
          </Link>
          <Link href="/me" className="card lifted">
            <h3>Personnel app</h3>
            <p className="muted" style={{ margin: "8px 0 0" }}>
              Eight languages. Per-domain consent, one-tap withdrawal, and a
              consent record tied to the exact words the person read.
            </p>
          </Link>
        </div>
      </section>

      <section className="section">
        <p className="eyebrow">Who it changes things for</p>
        <h2>Four audiences, four different views</h2>
        <div className="grid grid-2">
          {AUDIENCES.map((a) => (
            <div className="card" key={a.who}>
              <div className="row" style={{ marginBottom: 8 }}>
                <h3>{a.who}</h3>
                <span className="spacer" />
                <span className="pill plain">{a.sees}</span>
              </div>
              <p className="muted">{a.gets}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="section">
        <p className="eyebrow">Deployment</p>
        <h2>Three phases, and the first one issues no alerts</h2>
        <div className="card">
          <div className="seq">
            {PHASES.map(([n, name, detail], i) => (
              <div className={`seq-item ${i === 0 ? "key" : ""}`} key={n}>
                <span className="n">{n}</span>
                <span className="what">{name}</span>
                <span className="does">{detail}</span>
              </div>
            ))}
          </div>
        </div>
        <p className="faint measure">
          Escalation is precision-first: a missed early signal is recoverable at
          the next review cycle; a wrongly named soldier is not.
        </p>
      </section>

      <section className="section">
        <p className="eyebrow">What it will not do</p>
        <h2>The bars, and where they live</h2>
        <div className="grid grid-2">
          <div className="card rail-deep">
            <h3>Barred in the software</h3>
            <ul className="muted" style={{ paddingInlineStart: 18, marginTop: 10 }}>
              <li>ACR, promotion, posting and disciplinary processes — refused for every role.</li>
              <li>Individual data on a commanding officer&rsquo;s screen. No drill-down exists.</li>
              <li>Naming anybody who has not consented to welfare contact.</li>
              <li>Reporting or surfacing that a person withdrew consent.</li>
            </ul>
          </div>
          <div className="card rail-deep">
            <h3>Structural, not policy</h3>
            <ul className="muted" style={{ paddingInlineStart: 18, marginTop: 10 }}>
              <li>No identifier reaches the model layer — pseudonymised at ingest.</li>
              <li>A failed audit write aborts the disclosure. No name is released.</li>
              <li>No model may emit a gate value, a verdict or a confidence.</li>
              <li>Nothing retrains or re-thresholds itself without a recorded board decision.</li>
            </ul>
          </div>
        </div>
      </section>
    </>
  );
}
