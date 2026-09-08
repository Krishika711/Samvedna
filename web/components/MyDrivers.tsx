"use client";

import { useEffect, useState } from "react";
import { DEFAULT_SESSION, api } from "@/lib/api";
import { useLocale } from "@/i18n/LocaleProvider";

/**
 * "Why did the system look at me?" — answered to the person, in the same terms
 * the officer got.
 *
 * PART 8.7's dignity path and the submitted trust strategy both rest on this.
 * A person who is contacted can ask why, sees the same gate arithmetic and the
 * same drivers, and can disagree with them. Without it every false positive is
 * permanent, which is precisely how a welfare tool becomes feared.
 *
 * Deliberately not a summary written for the person. A summary would be a
 * second, friendlier account of a decision that was actually made on the first
 * one, and they are entitled to the one that was used.
 */
export function MyDrivers() {
  const { t } = useLocale();
  const [data, setData] = useState<Awaited<ReturnType<typeof api.myDrivers>> | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    // In a deployment the pid comes from the person's own token. In REPLAY the
    // console asks the run for one so the screen has something real to show.
    api
      .caseload(DEFAULT_SESSION.welfare_officer)
      .then((run) => {
        const first = run.cases[0]?.pid ?? "";
        if (first) {
          return api
            .myDrivers(first, { ...DEFAULT_SESSION.personnel, operator: first })
            .then(setData);
        }
        return undefined;
      })
      .catch((e) => setError(String(e.message ?? e)));
  }, []);

  if (error) return null;

  return (
    <div className="card">
      <h2>{t("drivers.title")}</h2>
      <p className="muted" style={{ marginTop: 8 }}>{t("drivers.lead")}</p>

      {!data && <p className="faint" style={{ marginTop: 12 }}>Loading…</p>}

      {data && !data.assessed && (
        <div className="banner good" style={{ marginTop: 14 }}>
          <strong>Nothing was raised.</strong>
          <span>{t("drivers.none")}</span>
        </div>
      )}

      {data?.assessed && (
        <>
          <div
            className={`banner ${data.named_to_an_officer ? "warn" : "info"}`}
            style={{ marginTop: 14 }}
          >
            <strong>{data.decision}</strong>
            <span>
              {data.named_to_an_officer ? t("drivers.namedYes") : t("drivers.namedNo")}
            </span>
          </div>

          {data.drivers.length > 0 && (
            <>
              <h3 style={{ marginTop: 20 }}>{t("drivers.driversTitle")}</h3>
              <div className="stack" style={{ gap: 8, marginTop: 10 }}>
                {data.drivers.map((d) => (
                  <div className="card flat tight" key={d.feature}>
                    <div className="row">
                      <span>{d.plain}</span>
                      <span className="spacer" />
                      <span className="mono faint">
                        {d.contribution > 0 ? "+" : ""}
                        {d.contribution.toFixed(3)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}

          <h3 style={{ marginTop: 20 }}>{t("drivers.gatesTitle")}</h3>
          <div className="stack" style={{ gap: 8, marginTop: 10 }}>
            {data.gates.map((g) => (
              <div className="card flat tight" key={g.name}>
                <div className="row">
                  <strong style={{ minWidth: 116 }}>{g.name}</strong>
                  <span className={`pill ${g.passed ? "pass" : "hold"}`}>
                    {g.value.toFixed(3)} / {g.threshold.toFixed(2)}
                  </span>
                </div>
                <div className="formula" style={{ marginTop: 8 }}>{g.formula}</div>
              </div>
            ))}
          </div>

          {data.mind_change && data.mind_change.length > 0 && (
            <div className="card flat" style={{ marginTop: 16 }}>
              <h3>What stopped it</h3>
              {data.mind_change.map((m) => (
                <div key={m.gate} style={{ marginTop: 8 }}>
                  <p className="faint">
                    {m.gate}: {m.current.toFixed(3)} → needed {m.required.toFixed(2)}
                  </p>
                  <ul className="muted" style={{ paddingInlineStart: 18, marginTop: 4 }}>
                    {m.would_change_if.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}

          {data.contest && (
            <div className="card rail" style={{ marginTop: 18 }}>
              <h3>{t("drivers.contestTitle")}</h3>
              <div className="stack" style={{ gap: 10, marginTop: 10 }}>
                {Object.entries(data.contest).map(([key, text]) => (
                  <div className="row" key={key} style={{ alignItems: "flex-start" }}>
                    <span className="pill plain">{key.replace(/_/g, " ")}</span>
                    <span className="muted" style={{ flex: 1, minWidth: 220 }}>
                      {text}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <p className="faint" style={{ marginTop: 14 }}>
            Reading your own record is not logged as an access by anybody else,
            and asking why never counts against you.
          </p>
        </>
      )}
    </div>
  );
}
