import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { api } from '../api/client';
import { useMe } from '../api/hooks';
import { useI18n } from '../i18n';

export type Theme = 'light' | 'dark' | 'system';

function read(): Theme {
  try {
    const v = window.localStorage.getItem('acr.theme');
    if (v === 'light' || v === 'dark' || v === 'system') return v;
  } catch {
    /* storage unavailable */
  }
  return 'system';
}

function apply(theme: Theme) {
  const el = document.documentElement;
  if (theme === 'system') el.removeAttribute('data-theme');
  else el.setAttribute('data-theme', theme);
}

interface ThemeValue {
  theme: Theme;
  setTheme: (t: Theme) => void;
}
const Ctx = createContext<ThemeValue | null>(null);

/** Theme persists locally at once and to the server preferences when signed in. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(read);
  const { me } = useMe();
  const { locale, arabicDigits } = useI18n();
  useEffect(() => apply(theme), [theme]);

  const setTheme = useCallback(
    (t: Theme) => {
      setThemeState(t);
      try {
        window.localStorage.setItem('acr.theme', t);
      } catch {
        /* not remembered */
      }
      if (me) api.put('/me/preferences', { theme: t, locale, digits: arabicDigits ? 'arab' : 'latn' }).catch(() => undefined);
    },
    [me, locale, arabicDigits],
  );
  const value = useMemo(() => ({ theme, setTheme }), [theme, setTheme]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTheme(): ThemeValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('ThemeProvider missing');
  return v;
}
