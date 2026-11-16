import { useState } from 'react';
import type { FormEvent } from 'react';
import { NavLink, useNavigate, useParams } from 'react-router-dom';
import { Badge, Button, Dialog, EmptyState, IconCheck, IconCopy, IconDownload, IconLock, IconPlus, IconSettings, Input, PageHeader, Panel, Segmented, Select, SkeletonRows, Table, useToast, cx } from '../ds';
import type { Column } from '../ds';
import { api, API_BASE } from '../api/client';
import { items, useMe, useResource } from '../api/hooks';
import type { AuditRow, Member, Page, Role } from '../api/types';
import { useI18n } from '../i18n';
import { errorToast } from '../app/lib';
import { useShell } from '../app/shell';
import { useTheme } from '../app/theme';

const SECTIONS = ['firm', 'definitions', 'templates', 'users', 'connectors', 'mailbox', 'audit', 'preferences'] as const;
type Section = (typeof SECTIONS)[number];
const OWNER_ONLY: Section[] = ['users', 'audit'];

export default function Settings() {
  const { section = 'preferences' } = useParams();
  const { t } = useI18n();
  const { me } = useMe();
  const sec: Section = (SECTIONS as readonly string[]).includes(section) ? (section as Section) : 'preferences';
  return (
    <div className="acr-page acr-settings">
      <PageHeader title={t('nav.settings')} subtitle={me ? `${me.org.name} · ${t(`role.${me.role}`)}` : undefined} />
      <div className="acr-settings__grid">
        <nav className="acr-subnav" aria-label={t('settings.sections')}>
          {SECTIONS.map((s) => (
            <NavLink key={s} to={`/settings/${s}`} className={({ isActive }) => cx('acr-subnav__link', isActive && 'is-active')}>
              {t(`settings.${s}`)}
              {OWNER_ONLY.includes(s) && <IconLock size={11} />}
            </NavLink>
          ))}
        </nav>
        <div className="acr-settings__body">
          {sec === 'users' && <Users />}
          {sec === 'audit' && <Audit />}
          {sec === 'preferences' && <Preferences />}
          {(sec === 'firm' || sec === 'definitions' || sec === 'templates' || sec === 'connectors' || sec === 'mailbox') && <Placeholder section={sec} />}
        </div>
      </div>
    </div>
  );
}

function Placeholder({ section }: { section: Exclude<Section, 'users' | 'audit' | 'preferences'> }) {
  const { t } = useI18n();
  const nav = useNavigate();
  const target = { firm: '/settings/users', definitions: '/deals', templates: '/library', connectors: '/agents', mailbox: '/settings/audit' }[section];
  return (
    <EmptyState
      icon={<IconSettings size={22} />}
      title={t(`settings.${section}.title`)}
      body={t(`settings.${section}.body`)}
      action={{ label: t(`settings.${section}.cta`), onClick: () => nav(target) }}
    />
  );
}

/* ---------------- Users ---------------- */

function Users() {
  const { t, fmt } = useI18n();
  const { me } = useMe();
  const toast = useToast();
  const owner = me?.role === 'owner';
  const members = useResource<Member[]>(async (signal) => items(await api.get<Page<Member> | Member[]>('/org/members', { signal })), []);
  const [invite, setInvite] = useState(false);
  const [removing, setRemoving] = useState<Member | null>(null);

  async function changeRole(m: Member, role: Role) {
    try {
      await api.patch(`/org/members/${m.user_id}`, { role });
      members.reload();
    } catch (e) {
      toast.push(errorToast(e, t('users.roleFailed')));
      members.reload();
    }
  }
  async function remove(m: Member) {
    try {
      await api.del(`/org/members/${m.user_id}`);
      setRemoving(null);
      members.reload();
      toast.push({ kind: 'success', title: t('users.removed', { name: m.name || m.email }) });
    } catch (e) {
      toast.push(errorToast(e, t('users.removeFailed')));
    }
  }
  const roles = (['owner', 'member', 'viewer'] as Role[]).map((r) => ({ value: r, label: t(`role.${r}`) }));
  const cols: Column<Member>[] = [
    { key: 'name', header: t('users.name'), sortValue: (m) => m.name, render: (m) => <span className="acr-strong">{m.name || '—'}</span> },
    { key: 'email', header: t('users.email'), sortValue: (m) => m.email, render: (m) => m.email },
    {
      key: 'role',
      header: t('users.role'),
      sortValue: (m) => m.role,
      render: (m) =>
        owner && m.user_id !== me?.user.id ? (
          <Select hideLabel label={t('users.roleOf', { name: m.name || m.email })} options={roles} value={m.role} onChange={(e) => changeRole(m, e.target.value as Role)} data-testid="role-select" />
        ) : (
          <Badge tone={m.role === 'owner' ? 'accent' : 'neutral'}>{t(`role.${m.role}`)}</Badge>
        ),
    },
    { key: 'since', header: t('users.since'), numeric: true, render: (m) => (m.created_at ? fmt.date(m.created_at) : '—') },
    {
      key: 'actions',
      header: '',
      render: (m) =>
        owner && m.user_id !== me?.user.id ? (
          <Button size="sm" variant="ghost" onClick={() => setRemoving(m)}>
            {t('users.remove')}
          </Button>
        ) : null,
    },
  ];
  return (
    <Panel
      title={t('settings.users')}
      flush
      actions={
        owner ? (
          <Button size="sm" variant="primary" icon={<IconPlus size={13} />} data-testid="invite-button" onClick={() => setInvite(true)}>
            {t('users.invite')}
          </Button>
        ) : undefined
      }
    >
      {!owner && <p className="acr-banner acr-banner--info acr-flushbanner">{t('users.readOnly')}</p>}
      {members.loading && !members.data ? (
        <SkeletonRows rows={4} label={t('common.loading')} />
      ) : (
        <Table
          testId="members-table"
          caption={t('settings.users')}
          columns={cols}
          rows={members.data ?? []}
          rowKey={(m) => m.user_id}
          rowProps={(m) => ({ 'data-id': m.user_id, 'data-testid': 'member-row' })}
          empty={<EmptyState title={t('users.empty.title')} body={t('users.empty.body')} action={{ label: t('users.invite'), onClick: () => setInvite(true) }} />}
        />
      )}
      <InviteDialog open={invite} onClose={() => setInvite(false)} onDone={members.reload} />
      <Dialog
        open={removing !== null}
        onClose={() => setRemoving(null)}
        title={t('users.removeTitle')}
        description={removing ? t('users.removeBody', { name: removing.name || removing.email }) : ''}
        closeLabel={t('common.close')}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setRemoving(null)}>
              {t('common.cancel')}
            </Button>
            <Button variant="danger" onClick={() => removing && remove(removing)}>
              {t('users.remove')}
            </Button>
          </>
        }
      >
        <p className="acr-muted">{t('users.removeNote')}</p>
      </Dialog>
    </Panel>
  );
}

interface InviteResp {
  invite_url?: string;
  url?: string;
  link?: string;
  token?: string;
  invite?: { token?: string };
}

function InviteDialog({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<Role>('member');
  const [busy, setBusy] = useState(false);
  const [link, setLink] = useState('');
  const [copied, setCopied] = useState(false);

  function close() {
    onClose();
    setEmail('');
    setLink('');
    setCopied(false);
    setBusy(false);
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api.post<InviteResp>('/org/invites', { email: email.trim(), role });
      const token = r.token ?? r.invite?.token;
      const raw = r.invite_url ?? r.url ?? r.link ?? (token ? `/invite?token=${encodeURIComponent(token)}` : '');
      setLink(raw.startsWith('/') ? `${window.location.origin}${raw}` : raw);
      onDone();
    } catch (x) {
      toast.push(errorToast(x, t('users.inviteFailed')));
    } finally {
      setBusy(false);
    }
  }
  async function copy() {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
    } catch {
      toast.push({ kind: 'info', title: t('users.copyFailed'), hint: t('users.copyHint') });
    }
  }
  return (
    <Dialog
      open={open}
      onClose={close}
      title={t('users.invite')}
      description={link ? t('users.invite.sent') : t('users.invite.desc')}
      closeLabel={t('common.close')}
      footer={
        link ? (
          <Button variant="primary" onClick={close}>
            {t('common.done')}
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={close}>
              {t('common.cancel')}
            </Button>
            <Button variant="primary" type="submit" form="invite-form" loading={busy} disabled={!email.includes('@')} data-testid="invite-submit">
              {t('users.invite.create')}
            </Button>
          </>
        )
      }
    >
      {link ? (
        <div className="acr-stack">
          <div className="acr-invitelink">
            <code data-testid="invite-link" className="acr-mono">
              {link}
            </code>
            <Button size="sm" variant="secondary" icon={copied ? <IconCheck size={13} /> : <IconCopy size={13} />} onClick={copy}>
              {copied ? t('common.copied') : t('common.copy')}
            </Button>
          </div>
          <p className="acr-banner acr-banner--warning">{t('users.invite.once')}</p>
        </div>
      ) : (
        <form id="invite-form" className="acr-stack" onSubmit={submit}>
          <Input label={t('users.email')} type="email" value={email} onChange={(e) => setEmail(e.target.value)} data-autofocus data-testid="invite-email" required />
          <Select label={t('users.role')} value={role} onChange={(e) => setRole(e.target.value as Role)} options={(['member', 'viewer', 'owner'] as Role[]).map((r) => ({ value: r, label: t(`role.${r}`) }))} data-testid="invite-role" />
        </form>
      )}
    </Dialog>
  );
}

/* ---------------- Audit ---------------- */

function Audit() {
  const { t, fmt } = useI18n();
  const { me } = useMe();
  const toast = useToast();
  const nav = useNavigate();
  const rows = useResource<AuditRow[]>(async (signal) => items(await api.get<Page<AuditRow> | AuditRow[]>('/audit', { query: { limit: 200 }, signal })), []);
  const [verify, setVerify] = useState<{ ok: boolean; seq?: number | null } | null>(null);
  const [busy, setBusy] = useState(false);
  if (me && me.role !== 'owner')
    return <EmptyState icon={<IconLock size={22} />} title={t('audit.ownerOnly.title')} body={t('audit.ownerOnly.body')} action={{ label: t('settings.preferences'), onClick: () => nav('/settings/preferences') }} />;

  async function runVerify() {
    setBusy(true);
    try {
      const r = await api.get<{ ok: boolean; seq?: number | null; broken_at?: number | null }>('/audit/verify');
      setVerify({ ok: r.ok, seq: r.broken_at ?? r.seq });
    } catch (e) {
      toast.push(errorToast(e, t('audit.verifyFailed')));
    } finally {
      setBusy(false);
    }
  }
  const cols: Column<AuditRow>[] = [
    { key: 'seq', header: '#', numeric: true, sortValue: (r) => r.seq, render: (r) => fmt.integer(r.seq) },
    { key: 'at', header: t('audit.at'), numeric: true, sortValue: (r) => r.at, render: (r) => fmt.dateTime(r.at) },
    { key: 'user', header: t('audit.user'), sortValue: (r) => r.user_email ?? r.user_id, render: (r) => r.user_email ?? r.user_id ?? '—' },
    { key: 'action', header: t('audit.action'), sortValue: (r) => r.action, mono: true, render: (r) => r.action },
    { key: 'target', header: t('audit.target'), mono: true, render: (r) => r.target || '—' },
    { key: 'ip', header: 'IP', mono: true, render: (r) => r.ip ?? '—' },
  ];
  return (
    <Panel
      title={t('settings.audit')}
      flush
      actions={
        <>
          <Button size="sm" variant="secondary" icon={<IconCheck size={13} />} loading={busy} data-testid="audit-verify" onClick={runVerify}>
            {t('audit.verify')}
          </Button>
          <a className="acr-btn acr-btn--secondary acr-btn--sm" data-testid="audit-export" href={`${API_BASE}/audit/export.csv`} download>
            <IconDownload size={13} />
            <span className="acr-btn__label">{t('audit.export')}</span>
          </a>
        </>
      }
    >
      {verify && (
        <p className={cx('acr-banner acr-flushbanner', verify.ok ? 'acr-banner--positive' : 'acr-banner--negative')} role="status" data-testid="audit-verify-result">
          {verify.ok ? t('audit.verify.ok') : t('audit.verify.broken', { seq: verify.seq ?? '?' })}
        </p>
      )}
      {rows.loading && !rows.data ? (
        <SkeletonRows rows={6} label={t('common.loading')} />
      ) : (
        <Table testId="audit-table" caption={t('settings.audit')} columns={cols} rows={rows.data ?? []} rowKey={(r) => String(r.seq)} initialSort={{ key: 'seq', dir: 'desc' }} maxHeight={560} empty={<EmptyState title={t('audit.empty.title')} body={t('audit.empty.body')} action={{ label: t('common.retry'), onClick: rows.reload }} />} />
      )}
    </Panel>
  );
}

/* ---------------- Preferences ---------------- */

function Preferences() {
  const { t, locale, setLocale, arabicDigits, setArabicDigits, fmt } = useI18n();
  const { theme, setTheme } = useTheme();
  const { openShortcuts } = useShell();
  return (
    <Panel title={t('settings.preferences')}>
      <div className="acr-prefs">
        <div className="acr-prefs__row">
          <div>
            <div className="acr-strong">{t('pref.theme')}</div>
            <div className="acr-muted">{t('pref.theme.hint')}</div>
          </div>
          <Segmented label={t('pref.theme')} value={theme} onChange={setTheme} options={[{ value: 'light', label: t('pref.light') }, { value: 'dark', label: t('pref.dark') }, { value: 'system', label: t('pref.system') }]} />
        </div>
        <div className="acr-prefs__row">
          <div>
            <div className="acr-strong">{t('pref.language')}</div>
            <div className="acr-muted">{t('pref.language.hint')}</div>
          </div>
          <Segmented label={t('pref.language')} value={locale} onChange={(l) => { setLocale(l); api.put('/me/preferences', { locale: l }).catch(() => undefined); }} options={[{ value: 'en', label: 'English' }, { value: 'ar', label: 'العربية' }]} />
        </div>
        <div className="acr-prefs__row">
          <div>
            <div className="acr-strong">{t('pref.digits')}</div>
            <div className="acr-muted">{t('pref.digits.hint', { sample: fmt.number(1234567.89) })}</div>
          </div>
          <Segmented label={t('pref.digits')} value={arabicDigits ? 'arab' : 'latn'} onChange={(v) => setArabicDigits(v === 'arab')} options={[{ value: 'latn', label: '0123' }, { value: 'arab', label: '٠١٢٣' }]} />
        </div>
        <div className="acr-prefs__row">
          <div>
            <div className="acr-strong">{t('shortcut.title')}</div>
            <div className="acr-muted">{t('pref.shortcuts.hint')}</div>
          </div>
          <Button variant="secondary" onClick={openShortcuts}>
            {t('pref.shortcuts.open')}
          </Button>
        </div>
      </div>
    </Panel>
  );
}
