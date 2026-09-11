"use client";

import { useEffect, useMemo, useState } from "react";
import { DraftBanner, LanguagePicker } from "@/components/LanguagePicker";
import { MyDrivers } from "@/components/MyDrivers";
import { SelfAssessment } from "@/components/SelfAssessment";
import { Guard } from "@/components/Shell";
import { DEFAULT_SESSION, api } from "@/lib/api";
import { LocaleProvider, useLocale } from "@/i18n/LocaleProvider";

/**
 * The personnel app. Consent, transparency and self-assessment.
 *
 * PART 11's design rule governs this page: it must be worth opening for the
 * person's own benefit. If it reads as surveillance, adoption collapses and the
 * T1 evidence channel dies with it — and a voluntary self-assessment is worth a
 * fifth of the evidence gate on its own, so that channel dying is not a cosmetic
 * loss.
 *
 * So the transparency screen is not a link. It is the page. And every word of it
 * is translated, because a transparency screen somebody cannot read is not
 * transparency.
 *
 * **On the removed "withdraw my consent" button.** It is gone from this screen
 * by request, and the right it exercised is not. DPDP Act 2023 s.6(4) requires
 * withdrawal to be as easy as giving consent, and that is still satisfied here:
 * the per-domain toggles below turn every collection scope off individually,
 * and the welfare-contact toggle stops an officer being able to make contact.
 * Setting all of them to "not allowed" is withdrawal — the same end state, and
 * a more informative one, because a person who only wants the wearable
 * switched off no longer has to revoke everything to get it.
 *
 * `POST /api/consent/{pid}/withdraw` is deliberately left in place. Removing
 * the route as well would make the obligation unimplementable rather than
 * merely differently presented, and an assisted withdrawal recorded by a
 * welfare cell still has to go somewhere.
 */

const DOMAIN_KEYS = [
  { key: "records", scope: ["leave", "deployment", "duty_roster", "transfer", "training", "workload"] },
  { key: "selfReport", scope: ["self_report"] },
  { key: "biometric", scope: ["biometric"] },
  // The add-on. A separate toggle because agreeing to have your leave record
  // read is not agreeing to be recorded, and defaulting this on would make that
  // distinction meaningless.
  { key: "voice", scope: ["voice"] },
] as const;

function MyDataInner() {
  const { t, list, locale, meta } = useLocale();
  const [scopes, setScopes] = useState<Record<string, boolean>>({
    records: true,
    selfReport: true,
    biometric: false,
    voice: false,
  });
  const [contact, setContact] = useState(true);
  const [receipt, setReceipt] = useState<{
    locale: string;
    version: string;
    at: string;
  } | null>(null);
  const [saveError, setSaveError] = useState("");
  const [saving, setSaving] = useState(false);
  // Who this console is acting as. In a deployment it comes from the
  // person's own token; in REPLAY the server hands one over, and says so.
  const [pid, setPid] = useState("");

  useEffect(() => {
    fetch("/api/me/whoami", {
      headers: { "X-Role": "personnel", "X-Operator": "SELF", "X-Units": "" },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d?.pid && setPid(d.pid))
      .catch(() => { /* the rest of the screen works without it */ });
  }, []);

  const canConsent = meta.reviewStatus !== "draft";

  const selectedScope = useMemo(
    () =>
      DOMAIN_KEYS.filter((d) => scopes[d.key]).flatMap((d) => [...d.scope]),
    [scopes],
  );

  const toggle = (key: string) =>
    setScopes((prev) => ({ ...prev, [key]: !prev[key] }));

  const save = async () => {
    if (!canConsent) {
      setSaveError(t("save.blockedDraft"));
      return;
    }
    if (!pid) {
      setSaveError("no identity resolved yet — reload and try again");
      return;
    }
    setSaveError("");
    setSaving(true);
    try {
      // This used to set a local receipt and stop. The toggles looked saved,
      // the button said SAVED, and the server had never heard of any of it —
      // so the next screen to ask "do they consent to self-report?" was told
      // no, and refused a submitted assessment. Two surfaces disagreeing about
      // consent is the worst possible thing for them to disagree about.
      const recorded = await api.consent(
        {
          pid,
          locale,
          scope: selectedScope,
          welfare_contact: contact,
        },
        { ...DEFAULT_SESSION.personnel, operator: pid },
      );
      // The receipt is the server's answer, not a hopeful echo of the request.
      setReceipt({
        locale: recorded.locale,
        version: recorded.text_version,
        at: recorded.recorded_at.replace("T", " ").slice(0, 16),
      });
    } catch (e) {
      setSaveError((e as Error).message);
      setReceipt(null);
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <LanguagePicker />
      <DraftBanner />

      {/* An operational header rather than a title and a paragraph. The three
        * tiles are the only things a person needs to know on opening this: what
        * they have allowed, whether they have checked in, and which language
        * their consent was recorded in. */}
      <div className="console-head" style={{ paddingTop: 18 }}>
        <div>
          <p className="eyebrow">{meta.englishName} · text {meta.textVersion}</p>
          <h1 style={{ fontSize: "1.7rem", maxWidth: "22ch" }}>{t("transparency.title")}</h1>
        </div>
        <div className="spacer" />
        <div className="kpi-row">
          <div className="kpi">
            <span className="kpi-n num">{selectedScope.length}</span>
            <span className="kpi-k" style={{ maxWidth: "13ch" }}>{t("allow.title")}</span>
          </div>
          <div className={`kpi ${contact ? "" : "kpi-alert"}`}>
            <span className="kpi-n num" style={{ fontSize: "1.05rem", paddingTop: 6 }}>
              {contact ? t("allow.allowed") : t("allow.notAllowed")}
            </span>
            <span className="kpi-k" style={{ maxWidth: "13ch" }}>{t("welfareContact.question")}</span>
          </div>
          <div className={`kpi ${receipt ? "" : "kpi-alert"}`}>
            <span className="kpi-n num" style={{ fontSize: "1.05rem", paddingTop: 6 }}>
              {receipt ? t("save.saved") : "—"}
            </span>
            <span className="kpi-k" style={{ maxWidth: "13ch" }}>{t("receipt.title")}</span>
          </div>
        </div>
      </div>

      <p className="muted" style={{ maxWidth: 640 }}>{t("transparency.lead")}</p>

      <div className="grid two">
        <div className="card">
          <h3 style={{ color: "var(--pass)" }}>{t("transparency.canSeeTitle")}</h3>
          <ul className="muted" style={{ paddingInlineStart: 18, margin: 0 }}>
            {list("transparency.canSee").map((line) => <li key={line}>{line}</li>)}
          </ul>
        </div>
        <div className="card">
          <h3 style={{ color: "var(--stop)" }}>{t("transparency.cannotSeeTitle")}</h3>
          <ul className="muted" style={{ paddingInlineStart: 18, margin: 0 }}>
            {list("transparency.cannotSee").map((line) => <li key={line}>{line}</li>)}
          </ul>
        </div>
      </div>

      {/* Folded, not deleted. Somebody reads this once on enrolment and never
        * again, and while it is open it pushes the actions below the fold. */}
      <details className="card fold">
        <summary>{t("transparency.neverTitle")}</summary>
        <ul className="muted" style={{ paddingInlineStart: 18, margin: "10px 0 0" }}>
          {list("transparency.never").map((line) => <li key={line}>{line}</li>)}
        </ul>
      </details>

      <div className="card">
        <h2>{t("allow.title")}</h2>
        <p className="faint" style={{ marginTop: 0 }}>{t("allow.lead")}</p>

        {DOMAIN_KEYS.map(({ key }) => (
          <div className="card flat tight" key={key}>
            <div className="row">
              <button
                onClick={() => toggle(key)}
                className={scopes[key] ? "primary" : ""}
                style={{ minWidth: 110 }}
                aria-pressed={scopes[key]}
              >
                {scopes[key] ? t("allow.allowed") : t("allow.notAllowed")}
              </button>
              <strong>{t(`domains.${key}.label`)}</strong>
              <span className="pill">{t(`domains.${key}.tier`)}</span>
            </div>
            <p className="muted" style={{ margin: "7px 0 0" }}>
              {t(`domains.${key}.what`)}
            </p>
          </div>
        ))}

        <div className="card flat tight" style={{ borderColor: "var(--accent)" }}>
          <div className="row">
            <button
              onClick={() => setContact(!contact)}
              className={contact ? "primary" : ""}
              style={{ minWidth: 110 }}
              aria-pressed={contact}
            >
              {contact ? t("allow.allowed") : t("allow.notAllowed")}
            </button>
            <strong>{t("welfareContact.question")}</strong>
          </div>
          <p className="muted" style={{ margin: "7px 0 0" }}>
            {t("welfareContact.explain")}
          </p>
          {!contact && (
            <div className="banner warn" style={{ marginBottom: 0 }}>
              <span>{t("welfareContact.warningOff")}</span>
            </div>
          )}
        </div>

        <div className="row" style={{ marginTop: 12 }}>
          <button
            className="primary"
            onClick={save}
            disabled={!canConsent || saving || !pid}
          >
            {saving ? "Saving…" : t("save.button")}
          </button>
          {receipt && <span className="pill pass">{t("save.saved")}</span>}
          {saveError && <span className="pill stop">{saveError}</span>}
        </div>
      </div>

      <SelfAssessment pid={pid} />

      <MyDrivers />

      <div className="card">
        <h2>{t("receipt.title")}</h2>
        <p className="muted" style={{ marginTop: 0 }}>{t("receipt.lead")}</p>
        <table>
          <tbody>
            <tr>
              <td className="faint" style={{ width: 180 }}>{t("receipt.language")}</td>
              <td>{receipt ? receipt.locale : <span className="faint">{t("receipt.notRecorded")}</span>}</td>
            </tr>
            <tr>
              <td className="faint">{t("receipt.version")}</td>
              <td className="mono">{receipt ? receipt.version : "—"}</td>
            </tr>
            <tr>
              <td className="faint">{t("receipt.recordedAt")}</td>
              <td className="mono">{receipt ? receipt.at : "—"}</td>
            </tr>
          </tbody>
        </table>
        {receipt && (
          <p className="faint" style={{ marginBottom: 0 }}>
            {selectedScope.length} domain(s) allowed ·{" "}
            {contact ? t("allow.allowed") : t("allow.notAllowed")}:{" "}
            {t("welfareContact.question")}
          </p>
        )}
      </div>

      {/* This one stays open. It is the single card on the page that somebody
        * might need at the moment they open it, and a person in difficulty
        * should not have to find and click a disclosure triangle to reach a
        * helpline number. */}
      <div className="card rail">
        <h2>{t("help.title")}</h2>
        <p className="muted" style={{ marginBottom: 8 }}>{t("help.lead")}</p>
        <ul className="muted" style={{ paddingInlineStart: 18, margin: 0 }}>
          {list("help.items").map((line) => <li key={line}>{line}</li>)}
        </ul>
      </div>

      <p className="faint">
        <span lang={locale}>{meta.name}</span> · {meta.englishName} ·{" "}
        text {meta.textVersion} · {meta.reviewStatus}
      </p>
    </>
  );
}

export default function MyData() {
  return (
    <Guard need="personnel">
      <LocaleProvider>
        <MyDataInner />
      </LocaleProvider>
    </Guard>
  );
}
