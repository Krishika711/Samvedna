/**
 * Vernacular support for the personnel app.
 *
 * Three rules shape this module, and each of them exists because the ordinary
 * approach to i18n would be actively harmful on a consent screen.
 *
 * **1. A missing key is a build failure, not an English fallback.** The usual
 * behaviour — fall back to the source language for anything untranslated — puts
 * an English sentence under a Hindi heading. A person who reads the Hindi and
 * skips the line they cannot read has not given informed consent, and the system
 * would have no way to know. `tools/check_locales.py` fails the build on any
 * missing or extra key, so a locale is either complete or it is not offered.
 *
 * **2. A translation carries a review status, and consent is refused against an
 * unreviewed one** outside pilot mode. Machine-drafted text is fine for showing
 * a reviewer what needs checking; it is not fine as the legal basis for
 * processing somebody's psychological data.
 *
 * **3. Validated instruments are not translated here at all.** PHQ-9 and GAD-7
 * cut-off scores are only valid against the officially validated translation for
 * a language. Substituting our own would leave the instrument looking normal and
 * scoring wrong, so `INSTRUMENT_AVAILABILITY` records where a licensed
 * translation exists and the app declines to offer the assessment where it does
 * not.
 *
 * No translation service is called, at build time or run time. The strings ship
 * in the repository, which is also what makes them reviewable.
 */

import ar from "./locales/ur.json";
import bn from "./locales/bn.json";
import en from "./locales/en.json";
import hi from "./locales/hi.json";
import mr from "./locales/mr.json";
import pa from "./locales/pa.json";
import ta from "./locales/ta.json";
import te from "./locales/te.json";

export type ReviewStatus = "source" | "draft" | "reviewed";
export type Direction = "ltr" | "rtl";

export interface LocaleMeta {
  locale: string;
  /** The language's name in its own script. Never the English exonym. */
  name: string;
  englishName: string;
  direction: Direction;
  /**
   * Bumped whenever any string in this file changes. A consent receipt records
   * the version the person actually read, so "what did they agree to?" has an
   * answer that survives a later edit.
   */
  textVersion: string;
  reviewStatus: ReviewStatus;
  reviewedBy: string;
  reviewedOn: string;
}

export interface Dictionary {
  _meta: LocaleMeta;
  [key: string]: unknown;
}

export const LOCALES: Record<string, Dictionary> = {
  en: en as Dictionary,
  hi: hi as Dictionary,
  bn: bn as Dictionary,
  mr: mr as Dictionary,
  ta: ta as Dictionary,
  te: te as Dictionary,
  pa: pa as Dictionary,
  ur: ar as Dictionary,
};

export const SOURCE_LOCALE = "en";
export const LOCALE_CODES = Object.keys(LOCALES);

/**
 * Where an officially validated translation of each instrument exists.
 *
 * This list is deliberately short and deliberately not optimistic. An instrument
 * offered in a language whose validation we cannot cite is an instrument whose
 * cut-off means nothing, and the failure is silent: the person answers, the
 * score computes, and the number is wrong in a direction nobody can see.
 *
 * Entries must cite the validation before being added. Where there is none, the
 * app tells the person plainly and offers the assessment in a language that has
 * one, rather than translating it ourselves.
 */
export const INSTRUMENT_AVAILABILITY: Record<string, Record<string, string>> = {
  PHQ9: {
    en: "Kroenke, Spitzer & Williams (2001), original validation",
    hi: "Hindi validation in Indian primary-care samples (De Man et al., 2021)",
  },
  GAD7: {
    en: "Spitzer et al. (2006), original validation",
    hi: "Hindi validation reported in Indian community samples",
  },
  MBI_GS9: {
    en: "Schaufeli et al., MBI-GS short form",
  },
};

export function metaFor(locale: string): LocaleMeta {
  return (LOCALES[locale] ?? LOCALES[SOURCE_LOCALE])._meta;
}

/**
 * Look a key up. Throws in development on a miss rather than returning the key
 * or an English string — see rule 1. The build-time check means this should be
 * unreachable in a shipped build, and if it is reached, failing loudly is the
 * only safe behaviour on this particular screen.
 */
export function lookup(dict: Dictionary, path: string): unknown {
  const value = path
    .split(".")
    .reduce<unknown>(
      (node, key) =>
        node && typeof node === "object"
          ? (node as Record<string, unknown>)[key]
          : undefined,
      dict,
    );
  if (value === undefined) {
    throw new Error(
      `missing translation '${path}' in locale '${dict._meta.locale}'. ` +
        `A partially translated consent screen is not informed consent.`,
    );
  }
  return value;
}

export function instrumentAvailableIn(instrument: string, locale: string): boolean {
  return Boolean(INSTRUMENT_AVAILABILITY[instrument]?.[locale]);
}

export function validationCitation(instrument: string, locale: string): string {
  return INSTRUMENT_AVAILABILITY[instrument]?.[locale] ?? "";
}
