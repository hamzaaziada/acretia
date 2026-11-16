import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import en from './en.json';
import ar from './ar.json';

export type Locale = 'en' | 'ar';
export type Vars = Record<string, string | number>;

const catalogues: Record<Locale, Record<string, string>> = { en, ar };

export function dirOf(locale: Locale): 'ltr' | 'rtl' {
  return locale === 'ar' ? 'rtl' : 'ltr';
}

function readStore(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}
function writeStore(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: the choice simply is not remembered */
  }
}

function initialLocale(): Locale {
  const stored = readStore('acr.locale');
  if (stored === 'en' || stored === 'ar') return stored;
  return typeof navigator !== 'undefined' && navigator.language.toLowerCase().startsWith('ar') ? 'ar' : 'en';
}

export function applyLocale(locale: Locale) {
  const el = document.documentElement;
  el.lang = locale;
  el.dir = dirOf(locale);
}

export interface Formatters {
  number: (n: number, opts?: Intl.NumberFormatOptions) => string;
  integer: (n: number) => string;
  currency: (n: number, currency?: string, fractionDigits?: number) => string;
  percent: (n: number, fractionDigits?: number) => string;
  date: (iso: string | number | Date, opts?: Intl.DateTimeFormatOptions) => string;
  dateTime: (iso: string | number | Date) => string;
  duration: (seconds: number) => string;
  relative: (iso: string | number | Date) => string;
}

function makeFormatters(locale: Locale, arabicDigits: boolean): Formatters {
  const tag = locale === 'ar' ? `ar-u-nu-${arabicDigits ? 'arab' : 'latn'}` : arabicDigits ? 'en-u-nu-arab' : 'en-US-u-nu-latn';
  const toDate = (v: string | number | Date) => (v instanceof Date ? v : new Date(v));
  const rtf = new Intl.RelativeTimeFormat(tag, { numeric: 'auto', style: 'short' });
  return {
    number: (n, opts) => new Intl.NumberFormat(tag, opts).format(n),
    integer: (n) => new Intl.NumberFormat(tag, { maximumFractionDigits: 0 }).format(n),
    // USD keeps the "$" prefix in every locale (Arabic locales otherwise print "US$" after the number), isolated as LTR.
    currency: (n, currency = 'USD', d = 2) =>
      currency === 'USD'
        ? '⁦$' + new Intl.NumberFormat(tag, { minimumFractionDigits: d, maximumFractionDigits: d }).format(n) + '⁩'
        : new Intl.NumberFormat(tag, { style: 'currency', currency, minimumFractionDigits: d, maximumFractionDigits: d }).format(n),
    percent: (n, d = 1) => new Intl.NumberFormat(tag, { style: 'percent', minimumFractionDigits: d, maximumFractionDigits: d }).format(n),
    date: (v, opts) => new Intl.DateTimeFormat(tag, opts ?? { year: 'numeric', month: 'short', day: 'numeric' }).format(toDate(v)),
    dateTime: (v) => new Intl.DateTimeFormat(tag, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(toDate(v)),
    duration: (s) => {
      const nf = new Intl.NumberFormat(tag, { minimumIntegerDigits: 2, useGrouping: false });
      const t = Math.max(0, Math.round(s));
      const h = Math.floor(t / 3600);
      const m = Math.floor((t % 3600) / 60);
      const sec = t % 60;
      return h > 0 ? `${new Intl.NumberFormat(tag).format(h)}:${nf.format(m)}:${nf.format(sec)}` : `${nf.format(m)}:${nf.format(sec)}`;
    },
    relative: (v) => {
      const diff = (toDate(v).getTime() - Date.now()) / 1000;
      const abs = Math.abs(diff);
      if (abs < 45) return rtf.format(0, 'second');
      if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute');
      if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour');
      return rtf.format(Math.round(diff / 86400), 'day');
    },
  };
}

interface I18nValue {
  locale: Locale;
  dir: 'ltr' | 'rtl';
  t: (key: string, vars?: Vars) => string;
  setLocale: (l: Locale) => void;
  arabicDigits: boolean;
  setArabicDigits: (v: boolean) => void;
  fmt: Formatters;
}

const Ctx = createContext<I18nValue | null>(null);

export function translate(locale: Locale, key: string, vars?: Vars): string {
  const raw = catalogues[locale][key] ?? catalogues.en[key] ?? key;
  if (!vars) return raw;
  return raw.replace(/\{(\w+)\}/g, (_, k: string) => (k in vars ? String(vars[k]) : `{${k}}`));
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale);
  const [arabicDigits, setArabicDigitsState] = useState<boolean>(() => readStore('acr.digits') === 'arab');

  useEffect(() => applyLocale(locale), [locale]);

  const setLocale = useCallback((l: Locale) => {
    writeStore('acr.locale', l);
    applyLocale(l);
    setLocaleState(l);
  }, []);
  const setArabicDigits = useCallback((v: boolean) => {
    writeStore('acr.digits', v ? 'arab' : 'latn');
    setArabicDigitsState(v);
  }, []);

  const value = useMemo<I18nValue>(
    () => ({
      locale,
      dir: dirOf(locale),
      t: (key, vars) => translate(locale, key, vars),
      setLocale,
      arabicDigits,
      setArabicDigits,
      fmt: makeFormatters(locale, arabicDigits),
    }),
    [locale, arabicDigits, setLocale, setArabicDigits],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18nValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('I18nProvider missing');
  return v;
}

export function useT() {
  return useI18n().t;
}
