"use client";

import { useLocale } from "@/i18n/LocaleProvider";

/**
 * Every language is written in its own script, never as an English exonym.
 *
 * Somebody looking for their language scans for the shape of their own writing.
 * A list reading "Hindi / Bengali / Tamil" in Latin script asks them to read
 * English first in order to escape it, which is precisely backwards on the one
 * screen where reading comfortably is the whole point.
 */
export function LanguagePicker() {
  const { locale, setLocale, all, t } = useLocale();

  return (
    <div className="card" style={{ marginTop: 22 }}>
      <h3>{t("picker.label")}</h3>
      <div className="row" style={{ marginBottom: 8 }}>
        {all.map((meta) => (
          <button
            key={meta.locale}
            onClick={() => setLocale(meta.locale)}
            className={locale === meta.locale ? "primary" : ""}
            lang={meta.locale}
            dir={meta.direction}
            aria-current={locale === meta.locale}
            title={meta.englishName}
          >
            {meta.name}
          </button>
        ))}
      </div>
      <p className="faint" style={{ margin: 0 }}>
        {t("picker.help")}
      </p>
    </div>
  );
}

/**
 * Shown whenever the chosen translation has not been checked by a native
 * speaker. It is deliberately not hidden: a person is entitled to know that the
 * words they are being asked to agree to have not been verified, and the system
 * refuses to record consent against them anyway.
 */
export function DraftBanner() {
  const { meta, t } = useLocale();
  if (meta.reviewStatus !== "draft") return null;
  return (
    <div className="banner warn">
      <strong>{meta.name}</strong>
      <span>{t("picker.draftWarning")}</span>
    </div>
  );
}
