"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  LOCALES,
  LOCALE_CODES,
  SOURCE_LOCALE,
  type Dictionary,
  type LocaleMeta,
  lookup,
} from "./index";

const STORAGE_KEY = "samvedna.locale";

interface LocaleContextValue {
  locale: string;
  meta: LocaleMeta;
  setLocale: (locale: string) => void;
  /** A string. Throws on a missing key rather than falling back to English. */
  t: (path: string) => string;
  /** A list. Throws if the key is not a list, for the same reason. */
  list: (path: string) => string[];
  /** Every locale's metadata, for the picker. */
  all: LocaleMeta[];
}

const LocaleContext = createContext<LocaleContextValue | null>(null);

/**
 * Picks the initial language from the device, then defers to what the person
 * chose. Never guesses from an IP address or anything else the person did not
 * tell us — a language guess that is wrong on a consent screen is worse than
 * asking.
 */
function initialLocale(): string {
  if (typeof window === "undefined") return SOURCE_LOCALE;
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored && LOCALE_CODES.includes(stored)) return stored;
  } catch {
    /* private browsing, or storage disabled. The default is still correct. */
  }
  const preferred = window.navigator?.languages ?? [];
  for (const tag of preferred) {
    const base = tag.split("-")[0];
    if (LOCALE_CODES.includes(base)) return base;
  }
  return SOURCE_LOCALE;
}

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState(SOURCE_LOCALE);

  // Read the stored choice after mount rather than during render, so the server
  // and the first client render agree and the page does not flash a language
  // the person did not pick.
  useEffect(() => setLocaleState(initialLocale()), []);

  const setLocale = useCallback((next: string) => {
    if (!LOCALE_CODES.includes(next)) return;
    setLocaleState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* the choice still applies for this session */
    }
  }, []);

  const dict: Dictionary = LOCALES[locale] ?? LOCALES[SOURCE_LOCALE];
  const meta = dict._meta;

  // The document direction follows the language, so an RTL script is laid out
  // as its readers expect rather than as a mirrored afterthought.
  useEffect(() => {
    document.documentElement.lang = meta.locale;
    document.documentElement.dir = meta.direction;
  }, [meta.locale, meta.direction]);

  const value = useMemo<LocaleContextValue>(
    () => ({
      locale,
      meta,
      setLocale,
      t: (path: string) => String(lookup(dict, path)),
      list: (path: string) => {
        const value = lookup(dict, path);
        if (!Array.isArray(value)) {
          throw new Error(`'${path}' is not a list in locale '${locale}'`);
        }
        return value as string[];
      },
      all: LOCALE_CODES.map((code) => LOCALES[code]._meta),
    }),
    [dict, locale, meta, setLocale],
  );

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleContextValue {
  const context = useContext(LocaleContext);
  if (!context) {
    throw new Error("useLocale must be used inside a LocaleProvider");
  }
  return context;
}
