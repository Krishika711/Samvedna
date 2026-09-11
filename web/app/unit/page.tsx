"use client";

import { useCallback, useEffect, useState } from "react";
import { Guard } from "@/components/Shell";
import { api } from "@/lib/api";
import { useService } from "@/lib/useService";
import { useSession } from "@/lib/session";
import type { UnitView } from "@/lib/types";

/**
 * The commanding officer's morning read.
 *
 * A commander is not given a list of people. That is the entire design: a
 * commander who can see which of their soldiers was flagged has been handed a
 * personnel file, and word gets round that reporting strain is career-limiting,
 * and then the honest answers stop arriving and the system is worth nothing.
 *
 * So this surface answers a different question — is my unit under strain, and
 * is it something I control? A commander can act on watch-and-rest rotation, on
 * leave backlog, on how long a sub-unit has been running unbroken. None of
 * those need a name.
 *
 * The suppressed cells are the feature. A cell with fewer than k people behind
 * it reads SUPPRESSED and stays suppressed however the view is refreshed,
 * because a number that can be narrowed to one person by asking twice is an
 * identity with extra steps.
 */

type HeatMap = Awaited<ReturnType<typeof api.heatmap>>;

const BAND_ORDER = ["critical", "high", "moderate", "low", "nominal"];

export default function UnitConsolePage() {
  return (
    <Guard need="commander">
      <UnitConsole />
    </Guard>
  );
}

function UnitConsole() {
  const { session, actor } = useSession();
  const { service } = useService();
  const unitId = (actor?.units || "UNIT-01").split(",")[0].trim();

  const [view, setView] = useState<UnitView | null>(null);
  const [heat, setHeat] = useState<HeatMap | null>(null);
  const [error, setError] = useState("");
  const [refreshes, setRefreshes] = useState(0);

  const load = useCallback(() => {
    if (!session) return;
    Promise.all([api.unit(unitId, session), api.heatmap(unitId, session)])
      .then(([u, h]) => { setView(u); setHeat(h); })
      .catch((e) => setError(String(e.message ?? e)));
  }, [session, unitId]);

  useEffect(load, [load]);

  if (error) return <div className="banner stop" style={{ marginTop: 30 }}>{error}</div>;
  if (!view || !heat) return <p className="faint" style={{ paddingTop: 34 }}>Loading unit view…</p>;

  const worst = [...heat.cells]
    .filter((c) => !c.suppressed)
    .sort((a, b) => BAND_ORDER.indexOf(a.band) - BAND_ORDER.indexOf(b.band))[0];
  const attention = heat.cells.filter(
    (c) => !c.suppressed && (c.band === "critical" || c.band === "high"),
  );

  return (
    <>
      <div className="console-head">
        <div>
          <p className="eyebrow">
            {service.unit} {unitId} · aggregate view · {view.as_of}
          </p>
          <h1 style={{ fontSize: "1.85rem" }}>Unit strain</h1>
        </div>
        <div className="spacer" />
        <div className="kpi-row">
          <div className={`kpi ${attention.length ? "kpi-alert" : ""}`}>
            <span className="kpi-n num">{attention.length}</span>
            <span className="kpi-k">{service.sub_unit.toLowerCase()}s raised</span>
          </div>
          <div className="kpi">
            <span className="kpi-n num">{heat.suppressed}</span>
            <span className="kpi-k">suppressed</span>
          </div>
          <div className="kpi">
            <span className="kpi-n num">k≥{heat.k}</span>
            <span className="kpi-k">min group</span>
          </div>
          <div className="kpi">
            <span className="kpi-n num">{view.budget_remaining.toFixed(1)}</span>
            <span className="kpi-k">privacy budget left</span>
          </div>
        </div>
      </div>

      {/* The headline. One sentence, and it is the sentence a commander repeats
        * at the morning brief, so it says what to do and not what was measured. */}
      <div className={`banner ${attention.length ? "warn" : "good"}`}>
        <strong>
          {attention.length === 0
            ? "Nothing raised above baseline."
            : `${worst?.sub_unit} — ${worst?.domain.replace(/_/g, " ")} is ${worst?.band}.`}
        </strong>
        <span>{view.next_step}</span>
      </div>

      <div className="grid-heat" style={{ marginTop: 16 }}>
        {/* ---- the matrix ---- */}
        <div className="card">
          <div className="row">
            <h2 style={{ fontSize: "1.05rem", margin: 0 }}>
              {service.sub_unit} × domain
            </h2>
            <span className="spacer" />
            <button className="ghost" onClick={() => { setRefreshes((r) => r + 1); load(); }}>
              Refresh
            </button>
          </div>
          <div className="scroller" style={{ marginTop: 12 }}>
            <table className="matrix">
              <thead>
                <tr>
                  <th>{service.sub_unit}</th>
                  {heat.domains.map((d) => (
                    <th key={d}>{d.replace(/_/g, " ")}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {heat.sub_units.map((su) => (
                  <tr key={su}>
                    <th scope="row">{su}</th>
                    {heat.domains.map((d) => {
                      const cell = heat.cells.find(
                        (c) => c.sub_unit === su && c.domain === d,
                      );
                      if (!cell) return <td key={d} className="heat-td" />;
                      return (
                        <td key={d} className="heat-td">
                          <span
                            className={`heat-cell band-${cell.suppressed ? "suppressed" : cell.band}`}
                            title={
                              cell.suppressed
                                ? cell.reason
                                : `${cell.band} · n=${cell.n} · ${cell.value?.toFixed(2)}`
                            }
                          >
                            {cell.suppressed ? "—" : cell.band.slice(0, 4)}
                          </span>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="heat-key" style={{ marginTop: 12 }}>
            {BAND_ORDER.map((b) => (
              <span key={b}>
                <span className={`heat-cell band-${b}`} style={{ width: 22 }} /> {b}
              </span>
            ))}
            <span>
              <span className="heat-cell band-suppressed" style={{ width: 22 }} /> too few to show
            </span>
          </div>
        </div>

        {/* ---- side rail ---- */}
        <div className="stack">
          <div className="card rail tight">
            <p className="eyebrow">Raised, in order</p>
            {attention.length === 0 ? (
              <p className="muted" style={{ marginTop: 6 }}>
                No sub-unit above baseline this run.
              </p>
            ) : (
              <ul className="tight-list muted">
                {attention.slice(0, 6).map((c) => (
                  <li key={`${c.sub_unit}-${c.domain}`}>
                    <strong>{c.sub_unit}</strong> · {c.domain.replace(/_/g, " ")} —{" "}
                    <span className={`pill ${c.band === "critical" ? "stop" : "hold"}`}>
                      {c.band}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="card flat tight">
            <p className="eyebrow">Not shown here</p>
            <ul className="tight-list muted">
              <li>Names. No individual is identifiable from this view.</li>
              <li>Self-report, biometric and voice domains — withheld from
                  command entirely, at any group size.</li>
              <li>Cells under k={heat.k} people, suppressed rather than rounded.</li>
            </ul>
            {refreshes > 0 && (
              <p className="faint" style={{ marginTop: 8 }}>
                Refreshed {refreshes}×. The same figures came back — a repeated
                view is served from cache so it cannot be averaged down to one
                person.
              </p>
            )}
          </div>

          <div className="card flat tight">
            <p className="eyebrow">Levers you hold</p>
            <ul className="tight-list muted">
              <li>Watch-and-rest rotation for the raised sub-unit</li>
              <li>Leave backlog — oldest pending request first</li>
              <li>Consecutive-days run: relief before day 14</li>
            </ul>
          </div>
        </div>
      </div>

      <p className="faint" style={{ marginTop: 20 }}>{heat.note}</p>
    </>
  );
}
