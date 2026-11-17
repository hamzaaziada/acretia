import { useState } from 'react';
import type { FormEvent } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { Button, IconCheck, Input, Segmented, Wordmark } from '../ds';
import { ApiError } from '../api/client';
import { useMe } from '../api/hooks';
import { useI18n } from '../i18n';

export default function Login() {
  const { t, locale, setLocale } = useI18n();
  const { me, login, loading } = useMe();
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const next = sp.get('next');
  const safeNext = next && next.startsWith('/') && !next.startsWith('//') ? next : '/';
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<{ message: string; hint: string } | null>(null);

  if (!loading && me) return <Navigate to={safeNext} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setErr(null);
    try {
      await login(email.trim(), password);
      nav(safeNext, { replace: true });
    } catch (x) {
      if (x instanceof ApiError && x.status === 429) setErr({ message: x.message || t('login.tooMany'), hint: x.hint ?? t('login.tooManyHint') });
      else if (x instanceof ApiError && x.status === 401) setErr({ message: x.message || t('login.invalid'), hint: x.hint ?? t('login.invalidHint') });
      else if (x instanceof ApiError && x.status === 0) setErr({ message: t('login.network'), hint: t('login.networkHint') });
      else setErr({ message: (x instanceof ApiError && x.message) || t('login.failed'), hint: (x instanceof ApiError && x.hint) || t('login.failedHint') });
      setBusy(false);
    }
  }

  return (
    <div className="acr-login">
      <aside className="acr-login__brand">
        <Wordmark size={26} />
        <div className="acr-login__pitch">
          <h2 className="acr-login__headline">{t('login.headline')}</h2>
          <ul className="acr-login__points">
            {(['p1', 'p2', 'p3'] as const).map((k) => (
              <li key={k}>
                <span className="acr-login__tick">
                  <IconCheck size={13} />
                </span>
                <span>
                  <strong>{t(`login.${k}.title`)}</strong>
                  <span className="acr-login__pointbody">{t(`login.${k}.body`)}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <div className="acr-login__legal">{t('login.legal')}</div>
      </aside>
      <main className="acr-login__panel" id="main">
        <div className="acr-login__lang">
          <Segmented
            label={t('pref.language')}
            value={locale}
            options={[
              { value: 'en', label: 'EN' },
              { value: 'ar', label: 'عربي' },
            ]}
            onChange={setLocale}
          />
        </div>
        <form className="acr-login__form" onSubmit={submit} noValidate>
          <h1 className="acr-login__title">{t('login.title')}</h1>
          <p className="acr-muted acr-login__sub">{t('login.subtitle')}</p>
          {err && (
            <div className="acr-formerror" role="alert" data-testid="login-error">
              <strong>{err.message}</strong>
              <span>{err.hint}</span>
            </div>
          )}
          <Input
            label={t('login.email')}
            type="email"
            name="email"
            autoComplete="username"
            required
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            data-testid="login-email"
          />
          <Input
            label={t('login.password')}
            type="password"
            name="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            data-testid="login-password"
          />
          <Button type="submit" variant="primary" size="lg" loading={busy} disabled={!email || !password} data-testid="login-submit" className="acr-login__submit">
            {t('login.submit')}
          </Button>
          <p className="acr-faint acr-login__foot">{t('login.help')}</p>
        </form>
      </main>
    </div>
  );
}
