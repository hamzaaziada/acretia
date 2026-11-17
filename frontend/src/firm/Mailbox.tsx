import { useEffect, useState } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import { Badge, Button, EmptyState, IconMail, Input, Panel, Pill, Segmented, SkeletonRows, Table, useToast } from '../ds';
import type { Column, Tone } from '../ds';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { items, useResource } from '../api/hooks';
import type { Page } from '../api/types';
import { errorToast } from '../app/lib';
import { useI18n } from '../i18n';
import { Switch } from './lib/Switch';
import { LoadError, ReadOnlyNote, useIsOwner } from './lib/shared';
import type { MailLogRow, MailTest, Mailbox as MailboxT } from './lib/types';
import './lib/firm.css';

const EMAIL = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$/;
const REASON: Record<string, string> = {
  sender_not_allowed: 'firm.mail.reason.sender_not_allowed',
  insufficient_role: 'firm.mail.reason.insufficient_role',
  authentication_failed: 'firm.mail.reason.authentication_failed',
  no_valid_sender: 'firm.mail.reason.no_valid_sender',
  empty_request: 'firm.mail.reason.empty_request',
  deal_limit: 'firm.mail.reason.deal_limit',
  org_limit: 'firm.mail.reason.org_limit',
  too_large: 'firm.mail.reason.too_large',
  unparseable: 'firm.mail.reason.unparseable',
};
const OUTCOME: Record<string, { label: string; tone: Tone }> = {
  accepted: { label: 'firm.mail.outcome.accepted', tone: 'positive' },
  rejected: { label: 'firm.mail.outcome.rejected', tone: 'warning' },
  error: { label: 'firm.mail.outcome.error', tone: 'negative' },
};

export default function Mailbox() {
  const { t, fmt } = useI18n();
  const toast = useToast();
  const owner = useIsOwner();
  const res = useResource<MailboxT>((signal) => api.get<MailboxT>('/firm/mailbox', { signal }), []);
  const log = useResource<MailLogRow[]>(async (signal) => (owner ? items(await api.get<Page<MailLogRow>>('/firm/mailbox/log', { query: { limit: 25 }, signal })) : []), [owner]);
  const [f, setF] = useState<MailboxT | null>(null);
  const [secret, setSecret] = useState('');
  const [sender, setSender] = useState('');
  const [senderErr, setSenderErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [test, setTest] = useState<MailTest | null>(null);
  const [error, setError] = useState<{ message: string; hint: string | null } | null>(null);

  useEffect(() => {
    if (res.data) {
      setF(res.data);
      setSecret('');
    }
  }, [res.data]);

  if (res.error) return <LoadError error={res.error} retry={res.reload} />;
  if (!res.data || !f) return <SkeletonRows rows={5} label={t('common.loading')} />;
  const form = f;
  const set = (p: Partial<MailboxT>) => setF({ ...form, ...p });
  const dirty = JSON.stringify({ ...form, secret: '' }) !== JSON.stringify({ ...res.data, secret: '' }) || secret !== '';

  function addSender() {
    const v = sender.trim().toLowerCase();
    if (!v) return;
    if (!EMAIL.test(v)) {
      setSenderErr(t('firm.mail.senderInvalid'));
      return;
    }
    setSenderErr('');
    if (!form.allowed_senders.includes(v)) set({ allowed_senders: [...form.allowed_senders, v] });
    setSender('');
  }
  function senderKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addSender();
    }
  }
  async function save(e: FormEvent) {
    e.preventDefault();
    if (!owner) return;
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        kind: form.kind,
        host: form.host,
        port: Number(form.port),
        username: form.username,
        folder: form.folder,
        path: form.path,
        poll_seconds: Number(form.poll_seconds),
        allowed_senders: form.allowed_senders,
        send_enabled: form.send_enabled,
      };
      if (secret) body.secret = secret;
      await api.put<MailboxT>('/firm/mailbox', body);
      toast.push({ kind: 'success', title: t('firm.mail.saved') });
      setTest(null);
      res.reload();
      log.reload();
    } catch (x) {
      const m = errorToast(x, t('firm.mail.saveFailed'));
      setError({ message: m.body ?? m.title, hint: m.hint ?? null });
    } finally {
      setBusy(false);
    }
  }
  async function runTest() {
    setTesting(true);
    try {
      setTest(await api.post<MailTest>('/firm/mailbox/test'));
      res.reload();
    } catch (x) {
      toast.push(errorToast(x, t('firm.mail.testFailed')));
    } finally {
      setTesting(false);
    }
  }
  const logCols: Column<MailLogRow>[] = [
    { key: 'at', header: t('firm.mail.log.at'), numeric: true, sortValue: (r) => r.at, render: (r) => fmt.dateTime(r.at) },
    { key: 'sender', header: t('firm.mail.log.from'), mono: true, sortValue: (r) => r.sender, render: (r) => r.sender || '—' },
    { key: 'subject', header: t('firm.mail.log.subject'), render: (r) => <span className="acr-truncate">{r.subject || '—'}</span> },
    { key: 'outcome', header: t('firm.mail.log.outcome'), sortValue: (r) => r.outcome, render: (r) => <Badge tone={OUTCOME[r.outcome]?.tone ?? 'neutral'}>{t(OUTCOME[r.outcome]?.label ?? 'firm.mail.outcome.error')}</Badge> },
    {
      key: 'detail',
      header: t('firm.mail.log.detail'),
      render: (r) => (r.job_id ? <Link to={`/runs/${r.job_id}`}>{t('firm.mail.log.openRun')}</Link> : r.reason ? (REASON[r.reason] ? t(REASON[r.reason]) : r.reason) : '—'),
    },
  ];
  const ro = !owner;
  return (
    <div className="acr-firm">
      <p className="acr-firm__intro">{t('firm.mail.intro')}</p>
      <Panel title={t('firm.mail.title')} flush>
        {ro && <ReadOnlyNote>{t('firm.ownerOnly')}</ReadOnlyNote>}
        <form data-testid="mailbox-form" onSubmit={save} noValidate>
          <div className="acr-firm__pad acr-stack">
            <div className="acr-row acr-wrap">
              <Segmented
                label={t('firm.mail.kind')}
                value={form.kind}
                onChange={(k) => !ro && set({ kind: k })}
                options={[
                  { value: 'imap', label: t('firm.mail.kind.imap') },
                  { value: 'maildir', label: t('firm.mail.kind.maildir') },
                ]}
                testId="mailbox-kind"
              />
              {res.data.configured && (
                <Badge tone={res.data.status === 'ok' ? 'positive' : res.data.status === 'error' ? 'negative' : 'neutral'} dot>
                  {t(res.data.status === 'ok' ? 'firm.mail.status.ok' : res.data.status === 'error' ? 'firm.mail.status.error' : 'firm.mail.status.new')}
                </Badge>
              )}
              {res.data.last_poll && <span className="acr-firm__meta">{t('firm.mail.lastPoll', { when: fmt.relative(res.data.last_poll) })}</span>}
            </div>
            {form.kind === 'imap' ? (
              <div className="acr-firm__grid">
                <Input label={t('firm.mail.host')} value={form.host} onChange={(e) => set({ host: e.target.value })} disabled={ro} mono dir="ltr" placeholder="imap.example.com" autoComplete="off" data-testid="mailbox-host" />
                <Input label={t('firm.mail.port')} value={String(form.port)} onChange={(e) => set({ port: Number(e.target.value.replace(/\D/g, '')) || 0 })} disabled={ro} mono dir="ltr" inputMode="numeric" data-testid="mailbox-port" />
                <Input label={t('firm.mail.username')} value={form.username} onChange={(e) => set({ username: e.target.value })} disabled={ro} mono dir="ltr" autoComplete="off" data-testid="mailbox-username" />
                <Input
                  label={t('firm.mail.secret')}
                  hint={form.has_secret ? t('firm.mail.secretSaved', { mask: form.secret || '••••' }) : t('firm.mail.secretHint')}
                  type="password"
                  value={secret}
                  onChange={(e) => setSecret(e.target.value)}
                  disabled={ro}
                  placeholder={form.has_secret ? form.secret : ''}
                  dir="ltr"
                  autoComplete="new-password"
                  data-testid="mailbox-secret"
                />
                <Input label={t('firm.mail.folder')} value={form.folder} onChange={(e) => set({ folder: e.target.value })} disabled={ro} mono dir="ltr" data-testid="mailbox-folder" />
              </div>
            ) : (
              <Input label={t('firm.mail.path')} hint={t('firm.mail.pathHint')} value={form.path} onChange={(e) => set({ path: e.target.value })} disabled={ro} mono dir="ltr" data-testid="mailbox-path" />
            )}
            <Input
              label={t('firm.mail.poll')}
              hint={t('firm.mail.pollHint')}
              value={String(form.poll_seconds)}
              onChange={(e) => set({ poll_seconds: Number(e.target.value.replace(/\D/g, '')) || 0 })}
              disabled={ro}
              mono
              dir="ltr"
              inputMode="numeric"
              fieldClassName="acr-firm__narrow"
              data-testid="mailbox-poll"
            />
            <div className="acr-firm-senders">
              <h3 className="acr-firm__sub">{t('firm.mail.senders')}</h3>
              <p className="acr-firm__meta">{t('firm.mail.sendersHint')}</p>
              <div className="acr-firm-chips" data-testid="mailbox-senders">
                {form.allowed_senders.length === 0 && <span className="acr-firm__meta">{t('firm.mail.sendersNone')}</span>}
                {form.allowed_senders.map((s) => (
                  <Pill key={s} onRemove={ro ? undefined : () => set({ allowed_senders: form.allowed_senders.filter((x) => x !== s) })} removeLabel={t('firm.mail.removeSender', { email: s })}>
                    <span dir="ltr">{s}</span>
                  </Pill>
                ))}
              </div>
              {!ro && (
                <div className="acr-firm-senders__add">
                  <Input label={t('firm.mail.addSender')} value={sender} onChange={(e) => setSender(e.target.value)} onKeyDown={senderKey} error={senderErr || undefined} type="email" dir="ltr" placeholder="name@partner.com" data-testid="mailbox-sender-input" />
                  <Button variant="secondary" onClick={addSender} data-testid="mailbox-sender-add">
                    {t('firm.mail.add')}
                  </Button>
                </div>
              )}
            </div>
            <div className="acr-stack">
              <Switch
                checked={form.send_enabled}
                onChange={(v) => set({ send_enabled: v })}
                disabled={ro}
                label={t('firm.mail.send')}
                hint={t('firm.mail.sendHint')}
                testId="mailbox-send-enabled"
              />
              <p className="acr-banner acr-banner--warning" data-testid="mailbox-send-warning">
                {t('firm.mail.sendWarning')}
              </p>
            </div>
            {test && (
              <div className={`acr-firm-result ${test.ok ? 'is-ok' : 'is-bad'}`} role="status" data-testid="mailbox-test-result">
                <strong>{test.message}</strong>
                {test.hint && <span>{test.hint}</span>}
              </div>
            )}
            {error && (
              <div className="acr-formerror" role="alert">
                <strong>{error.message}</strong>
                {error.hint && <span>{error.hint}</span>}
              </div>
            )}
          </div>
          {!ro && (
            <div className="acr-firm__footer">
              {dirty && <Badge tone="warning">{t('firm.unsaved')}</Badge>}
              <span className="acr-spacer-flex" />
              <Button variant="secondary" loading={testing} disabled={dirty || !res.data.configured} onClick={runTest} data-testid="mailbox-test" title={dirty ? t('firm.mail.testSaveFirst') : undefined}>
                {t('firm.mail.test')}
              </Button>
              <Button variant="primary" type="submit" loading={busy} disabled={!dirty} data-testid="mailbox-save">
                {t('common.save')}
              </Button>
            </div>
          )}
        </form>
      </Panel>
      {owner && (
        <Panel title={t('firm.mail.log.title')} flush>
          {log.loading && !log.data ? (
            <SkeletonRows rows={3} label={t('common.loading')} />
          ) : (
            <Table
              testId="mail-log"
              caption={t('firm.mail.log.title')}
              columns={logCols}
              rows={log.data ?? []}
              rowKey={(r) => r.id}
              maxHeight={320}
              initialSort={{ key: 'at', dir: 'desc' }}
              empty={<EmptyState icon={<IconMail size={22} />} title={t('firm.mail.log.empty.title')} body={t('firm.mail.log.empty.body')} action={{ label: t('common.retry'), onClick: log.reload }} />}
            />
          )}
        </Panel>
      )}
    </div>
  );
}
