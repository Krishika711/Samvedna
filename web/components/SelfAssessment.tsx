"use client";

import { useState } from "react";
import { instrumentAvailableIn, validationCitation } from "@/i18n";
import { useLocale } from "@/i18n/LocaleProvider";

/**
 * The PHQ-9 self-assessment. Voluntary, stoppable, and answered by nobody else.
 *
 * Three things about this component matter more than its appearance:
 *
 * **The item wording is the validated wording, verbatim.** A questionnaire's
 * cut-offs mean what they mean in the exact words it was validated in. So the
 * items are only rendered in a language where a licensed translation exists,
 * and elsewhere the app declines and says why rather than showing a translation
 * of our own that would look normal and score wrong.
 *
 * **Item 9 is watched, and it does not wait for the nightly run.** Any
 * endorsement above zero routes the same working day to a mental-health
 * authority, bypassing the four gates. That path is triggered by this item, not
 * by a total and never by a model.
 *
 * **The individual answers are discarded.** Only the band is kept. What the
 * officer eventually sees is a domain deviation, never a row of answers, and
 * this component holds the answers only until it computes the band.
 */

const OPTIONS = [
  { value: 0, label: "Not at all" },
  { value: 1, label: "Several days" },
  { value: 2, label: "More than half the days" },
  { value: 3, label: "Nearly every day" },
];

/** PHQ-9, the published wording. Item 9 is the acute-risk item. */
const PHQ9_ITEMS = [
  "Little interest or pleasure in doing things",
  "Feeling down, depressed, or hopeless",
  "Trouble falling or staying asleep, or sleeping too much",
  "Feeling tired or having little energy",
  "Poor appetite or overeating",
  "Feeling bad about yourself — or that you are a failure, or have let yourself or your family down",
  "Trouble concentrating on things, such as reading or watching television",
  "Moving or speaking so slowly that other people could have noticed — or the opposite, being so fidgety or restless that you have been moving around a lot more than usual",
  "Thoughts that you would be better off dead, or of hurting yourself in some way",
];

const ACUTE_INDEX = 8; // item 9, zero-based

function band(total: number): { label: string; tone: string } {
  if (total >= 20) return { label: "Severe (20–27)", tone: "stop" };
  if (total >= 15) return { label: "Moderately severe (15–19)", tone: "hold" };
  if (total >= 10) return { label: "Moderate (10–14)", tone: "hold" };
  if (total >= 5) return { label: "Mild (5–9)", tone: "" };
  return { label: "Minimal (0–4)", tone: "pass" };
}

export function SelfAssessment({ onAcute }: { onAcute?: () => void }) {
  const { t, locale } = useLocale();
  const available = instrumentAvailableIn("PHQ9", locale);

  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<(number | null)[]>(
    Array(PHQ9_ITEMS.length).fill(null),
  );
  const [result, setResult] = useState<{ total: number; acute: boolean } | null>(null);

  if (!available) {
    return (
      <div className="card">
        <h2>{t("instrument.title")}</h2>
        <div className="banner warn" style={{ marginTop: 12 }}>
          <strong>PHQ-9</strong>
          <span>{t("instrument.unavailable")}</span>
        </div>
        <p className="faint" style={{ marginTop: 10 }}>
          {t("instrument.takeIn")}: English, हिन्दी
        </p>
      </div>
    );
  }

  if (result) {
    const b = band(result.total);
    return (
      <div className="card">
        <h2>{t("instrument.title")}</h2>
        {result.acute ? (
          <div className="banner stop" style={{ marginTop: 12 }}>
            <strong>Someone will contact you today.</strong>
            <span>
              What you have described is taken seriously. This goes to the
              designated mental-health authority — <strong>not</strong> to your
              commanding officer, not on your record, and it will not affect your
              posting, promotion or ACR. You do not have to wait for that call:
              the unit medical officer is reachable through the unit exchange at
              any hour.
            </span>
          </div>
        ) : (
          <div className="banner good" style={{ marginTop: 12 }}>
            <strong>{t("instrument.done")}</strong>
          </div>
        )}
        <div className="row" style={{ marginTop: 16 }}>
          <span className="faint">{t("instrument.bandLabel")}</span>
          <span className={`pill ${b.tone}`}>{b.label}</span>
        </div>
        <p className="faint" style={{ marginTop: 10 }}>
          {t("instrument.privacyNote")}
        </p>
        <div className="row" style={{ marginTop: 14 }}>
          <button
            onClick={() => {
              setResult(null);
              setOpen(false);
              setIndex(0);
              setAnswers(Array(PHQ9_ITEMS.length).fill(null));
            }}
          >
            Close
          </button>
        </div>
      </div>
    );
  }

  if (!open) {
    return (
      <div className="card">
        <h2>{t("instrument.title")}</h2>
        <div className="banner info" style={{ marginTop: 12 }}>
          <strong>PHQ-9</strong>
          <span>{t("instrument.available")}</span>
        </div>
        <p className="muted" style={{ marginTop: 12 }}>{t("instrument.intro")}</p>
        <p className="faint" style={{ marginTop: 8 }}>
          {t("instrument.validatedAs")}: {validationCitation("PHQ9", locale)}
        </p>
        <div className="row" style={{ marginTop: 14 }}>
          <button className="primary" onClick={() => setOpen(true)}>
            {t("instrument.start")}
          </button>
        </div>
      </div>
    );
  }

  const answered = answers[index];
  const last = index === PHQ9_ITEMS.length - 1;

  const choose = (value: number) => {
    const next = [...answers];
    next[index] = value;
    setAnswers(next);
  };

  const finish = () => {
    const total = answers.reduce<number>((sum, a) => sum + (a ?? 0), 0);
    const acute = (answers[ACUTE_INDEX] ?? 0) > 0;
    setResult({ total, acute });
    if (acute) onAcute?.();
  };

  return (
    <div className="card">
      <div className="row" style={{ marginBottom: 6 }}>
        <h2 style={{ fontSize: "1.25rem" }}>{t("instrument.title")}</h2>
        <span className="spacer" />
        <span className="faint">
          {t("instrument.progress")} {index + 1} {t("instrument.of")}{" "}
          {PHQ9_ITEMS.length}
        </span>
      </div>

      <div
        className="progress"
        role="progressbar"
        aria-valuenow={index + 1}
        aria-valuemin={1}
        aria-valuemax={PHQ9_ITEMS.length}
      >
        <span style={{ width: `${((index + 1) / PHQ9_ITEMS.length) * 100}%` }} />
      </div>

      <p className="faint" style={{ margin: "14px 0 4px" }}>{t("instrument.lead")}</p>
      <p style={{ fontSize: "1.1rem", fontFamily: "var(--serif)", marginBottom: 14 }}>
        {PHQ9_ITEMS[index]}
      </p>

      <div className="stack" style={{ gap: 8 }}>
        {OPTIONS.map((o) => (
          <button
            key={o.value}
            onClick={() => choose(o.value)}
            className={answered === o.value ? "primary" : ""}
            style={{ textAlign: "left", justifyContent: "flex-start" }}
            aria-pressed={answered === o.value}
          >
            {o.label}
          </button>
        ))}
      </div>

      <div className="row" style={{ marginTop: 18 }}>
        <button onClick={() => setIndex((i) => Math.max(0, i - 1))} disabled={index === 0}>
          {t("instrument.back")}
        </button>
        {last ? (
          <button className="primary" onClick={finish} disabled={answered === null}>
            {t("instrument.submit")}
          </button>
        ) : (
          <button
            className="primary"
            onClick={() => setIndex((i) => i + 1)}
            disabled={answered === null}
          >
            {t("instrument.next")}
          </button>
        )}
        <span className="spacer" />
        <button
          className="ghost"
          onClick={() => {
            setOpen(false);
            setIndex(0);
            setAnswers(Array(PHQ9_ITEMS.length).fill(null));
          }}
        >
          {t("instrument.cancel")}
        </button>
      </div>
    </div>
  );
}
