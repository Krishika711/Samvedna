"use client";

import { useState } from "react";
import { DEFAULT_SESSION, api } from "@/lib/api";
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

export function SelfAssessment({
  pid,
  onAcute,
}: {
  /** Whose assessment this is. Empty until the console has resolved it,
   *  in which case the form still works and simply cannot submit. */
  pid: string;
  onAcute?: () => void;
}) {
  const { t, locale } = useLocale();
  const available = instrumentAvailableIn("PHQ9", locale);

  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<(number | null)[]>(
    Array(PHQ9_ITEMS.length).fill(null),
  );
  const [result, setResult] = useState<{ total: number; acute: boolean } | null>(null);
  // What the server decided. The browser's own total is shown only until this
  // arrives, and is never what a decision rests on.
  const [outcome, setOutcome] = useState<
    Awaited<ReturnType<typeof api.assessment>> | null
  >(null);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState("");

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
        ) : sendError ? (
          // Nothing here claims the assessment was recorded, because it was
          // not. The screenshot that prompted this fix showed "your assessment
          // has been recorded" directly above "your answers could not be
          // recorded" — the first from local state the moment the form was
          // completed, the second from the server refusing it. A person cannot
          // act on a screen that says both.
          <div className="banner warn" style={{ marginTop: 12 }}>
            <strong>Not recorded.</strong>
            <span>
              You completed the questionnaire, but it did not reach the system.
              See below.
            </span>
          </div>
        ) : outcome ? (
          <div className="banner good" style={{ marginTop: 12 }}>
            <strong>{t("instrument.done")}</strong>
          </div>
        ) : (
          <div className="banner info" style={{ marginTop: 12 }}>
            <span>Recording your answers…</span>
          </div>
        )}
        <div className="row" style={{ marginTop: 16 }}>
          <span className="faint">{t("instrument.bandLabel")}</span>
          <span className={`pill ${b.tone}`}>{b.label}</span>
          {outcome && outcome.total !== result.total && (
            // The server scores the instrument itself. If its total disagrees
            // with the browser's, the server's is the one that counted and the
            // person should see that rather than a number that decided nothing.
            <span className="faint">
              (recorded as {outcome.total})
            </span>
          )}
        </div>
        {!sendError && (
          <p className="faint" style={{ marginTop: 10 }}>
            {t("instrument.privacyNote")}
          </p>
        )}

        {/* What the server actually decided.
          *
          * A person who fills in nine questions and is shown a colour has not
          * been told anything. If the answer is "this did not reach anybody",
          * that is the answer they are owed — with the reason — rather than an
          * ambiguous silence they will read as either broken or ignored. */}
        {sending && (
          <p className="faint" style={{ marginTop: 12 }}>Recording your answers…</p>
        )}
        {sendError && (
          <div className="banner warn" style={{ marginTop: 12 }}>
            <strong>Your answers could not be recorded.</strong>
            <span>
              {sendError}. What you can see above still stands, and the
              helplines are still the right number to call.
            </span>
          </div>
        )}
        {outcome && (
          <div className="card flat tight" style={{ marginTop: 14 }}>
            <p className="eyebrow">What happened next</p>
            {outcome.named_to_an_officer ? (
              <p className="muted" style={{ marginTop: 6 }}>
                A welfare officer has been given your case
                {outcome.acute
                  ? ", and the designated mental-health authority has it as an urgent referral."
                  : "."}{" "}
                They can see the reasons, not your answers.
              </p>
            ) : (
              <>
                <p className="muted" style={{ marginTop: 6 }}>
                  <strong>This has not been sent to anybody.</strong> Your
                  answers are recorded and count towards tonight&rsquo;s
                  review, but on their own they are not enough to put your name
                  in front of an officer — one kind of evidence never is, and a
                  single day is not yet a pattern.
                </p>
                {outcome.mind_change.length > 0 && (
                  <p className="faint" style={{ marginTop: 8 }}>
                    What would change that:{" "}
                    {outcome.mind_change[0].would_change_if[0]}
                  </p>
                )}
                <p className="faint" style={{ marginTop: 8 }}>
                  If you would rather speak to somebody now, you do not have to
                  wait for the system to agree with you — the numbers above work
                  at any hour.
                </p>
              </>
            )}
          </div>
        )}
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

  const finish = async () => {
    const items = answers.map((a) => a ?? 0);
    const total = items.reduce((sum, a) => sum + a, 0);
    const acute = items[ACUTE_INDEX] > 0;
    setResult({ total, acute });
    if (acute) onAcute?.();

    // And send it. This is the whole point of the change: the form used to
    // compute a band and stop, so completing a questionnaire produced no
    // record, no re-decision and no case. Self-report is the only T1 domain in
    // the system and it was inert.
    if (!pid) {
      setSendError("no identity resolved yet — reload and try again");
      return;
    }
    setSending(true);
    setSendError("");
    try {
      setOutcome(await api.assessment(pid, items, {
        ...DEFAULT_SESSION.personnel,
        operator: pid,
      }));
    } catch (e) {
      // The band is still shown, and so are the helplines if item 9 fired.
      // Withholding support because a request failed would be the worst
      // possible reading of "fail closed".
      setSendError((e as Error).message);
    } finally {
      setSending(false);
    }
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
