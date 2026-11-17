import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Button, Input, Wordmark } from '../ds';
import { api, ApiError } from '../api/client';
import { useMe } from '../api/hooks';
import { useT } from '../i18n';

export default function AcceptInvite() {
  const t = useT();
  const [sp] = useSearchParams();
  const token = sp.get('token') ?? '';
  const { refresh } = useMe();
  const nav = useNavigate();
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<{ message: string; hint: string } | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api.post('/auth/invites/accept', { token, name, password });
      await refresh();
      nav('/', { replace: true });
    } catch (x) {
      setErr({ message: (x instanceof ApiError && x.message) || t('invite.failed'), hint: (x instanceof ApiError && x.hint) || t('invite.failedHint') });
      setBusy(false);
    }
  }

  return (
    <div className="acr-login acr-login--single">
      <main className="acr-login__panel" id="main">
        <form className="acr-login__form" onSubmit={submit}>
          <Wordmark size={24} />
          <h1 className="acr-login__title">{t('invite.title')}</h1>
          <p className="acr-muted acr-login__sub">{token ? t('invite.subtitle') : t('invite.noToken')}</p>
          {err && (
            <div className="acr-formerror" role="alert">
              <strong>{err.message}</strong>
              <span>{err.hint}</span>
            </div>
          )}
          <Input label={t('invite.name')} value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required />
          <Input label={t('invite.password')} hint={t('invite.passwordHint')} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" minLength={10} required />
          <Button type="submit" variant="primary" size="lg" loading={busy} disabled={!token || !name || password.length < 10}>
            {t('invite.submit')}
          </Button>
          <p className="acr-faint acr-login__foot">
            <Link to="/login">{t('invite.haveAccount')}</Link>
          </p>
        </form>
      </main>
    </div>
  );
}
