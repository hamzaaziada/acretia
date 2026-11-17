import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  Avatar,
  Badge,
  Button,
  CommandPalette,
  Dialog,
  Drawer,
  IconBell,
  IconBuilding,
  IconCollapse,
  IconDeal,
  IconAgent,
  IconHome,
  IconKeyboard,
  IconLibrary,
  IconSearch,
  IconSettings,
  IconChevronDown,
  Kbd,
  MenuButton,
  MenuItem,
  MenuLabel,
  MenuSep,
  Segmented,
  Sidebar,
  SidebarLink,
  SidebarNav,
  SkeletonRows,
  Wordmark,
  cx,
  isTypingTarget,
  useToast,
} from '../ds';
import type { PaletteGroup } from '../ds';
import { useMe, OrgEventsProvider, useOrgEvents, items, useDeals, useResource } from '../api/hooks';
import { api } from '../api/client';
import type { Notification, Page, Deal } from '../api/types';
import { useI18n } from '../i18n';
import { useTheme } from './theme';
import { createJob, errorToast, recentPrompts, rememberPrompt, useAgents, useAllDeliverables, viewerPath } from './lib';
import type { Agent } from '../api/types';

interface ShellApi {
  openPalette: (prefill?: string) => void;
  openShortcuts: () => void;
  openNotifications: () => void;
}
const ShellCtx = createContext<ShellApi | null>(null);
export function useShell(): ShellApi {
  const v = useContext(ShellCtx);
  if (!v) throw new Error('Shell missing');
  return v;
}

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);
export const modKey = isMac ? '⌘' : 'Ctrl';

export const SHORTCUTS: Array<{ keys: string[]; labelKey: string }> = [
  { keys: [modKey, 'K'], labelKey: 'shortcut.palette' },
  { keys: ['g', 'h'], labelKey: 'shortcut.home' },
  { keys: ['g', 'd'], labelKey: 'shortcut.deals' },
  { keys: ['g', 'l'], labelKey: 'shortcut.library' },
  { keys: ['g', 'a'], labelKey: 'shortcut.agents' },
  { keys: ['g', 'n'], labelKey: 'shortcut.notifications' },
  { keys: ['g', 's'], labelKey: 'shortcut.settings' },
  { keys: ['j', 'k'], labelKey: 'shortcut.listNav' },
  { keys: ['?'], labelKey: 'shortcut.help' },
  { keys: ['Esc'], labelKey: 'shortcut.close' },
];

const GO: Record<string, string> = { h: '/', d: '/deals', l: '/library', a: '/agents', n: '/notifications', s: '/settings/preferences' };

export function Shell() {
  return (
    <OrgEventsProvider>
      <ShellInner />
    </OrgEventsProvider>
  );
}

function ShellInner() {
  const { t } = useI18n();
  const nav = useNavigate();
  const loc = useLocation();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [palettePrefill, setPalettePrefill] = useState('');
  const [sheetOpen, setSheetOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const goPending = useRef<number | null>(null);

  useEffect(() => setNavOpen(false), [loc.pathname]);

  const api_ = useMemo<ShellApi>(
    () => ({
      openPalette: (p) => {
        setPalettePrefill(p ?? '');
        setPaletteOpen(true);
      },
      openShortcuts: () => setSheetOpen(true),
      openNotifications: () => setDrawerOpen(true),
    }),
    [],
  );

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen((o) => !o);
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey || isTypingTarget(e.target)) return;
      if (document.querySelector('[aria-modal="true"]')) return;
      if (e.key === '?') {
        e.preventDefault();
        setSheetOpen(true);
        return;
      }
      if (goPending.current !== null) {
        window.clearTimeout(goPending.current);
        goPending.current = null;
        const dest = GO[e.key.toLowerCase()];
        if (dest) {
          e.preventDefault();
          nav(dest);
        }
        return;
      }
      if (e.key === 'g') goPending.current = window.setTimeout(() => (goPending.current = null), 1200);
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [nav]);

  return (
    <ShellCtx.Provider value={api_}>
      <div className={cx('acr-app', navOpen && 'is-nav-open')} data-testid="app-shell">
        <a href="#main" className="acr-skip">
          {t('shell.skip')}
        </a>
        <AppSidebar />
        {navOpen && <div className="acr-app__veil" onClick={() => setNavOpen(false)} aria-hidden="true" />}
        <div className="acr-app__col">
          <Topbar onNav={() => setNavOpen((o) => !o)} />
          <main id="main" className="acr-main" tabIndex={-1}>
            <Outlet />
          </main>
        </div>
      </div>
      {paletteOpen && <Palette key={palettePrefill} prefill={palettePrefill} onClose={() => setPaletteOpen(false)} />}
      <ShortcutSheet open={sheetOpen} onClose={() => setSheetOpen(false)} />
      <NotificationsDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </ShellCtx.Provider>
  );
}

/* ---------------- Sidebar ---------------- */

function AppSidebar() {
  const { t } = useI18n();
  const { me, switchOrg } = useMe();
  const { unread } = useOrgEvents();
  const toast = useToast();
  if (!me) return null;
  return (
    <Sidebar
      label={t('shell.nav')}
      brand={
        <Link to="/" aria-label={t('shell.home')} className="acr-brandlink">
          <Wordmark label="Acretia" />
        </Link>
      }
      footer={<UserMenu />}
    >
      <div data-testid="sidebar" className="acr-sidebar__inner">
        <div className="acr-orgswitch">
          <IconBuilding size={14} />
          {me.orgs.length > 1 ? (
            <select
              data-testid="org-switcher"
              aria-label={t('shell.org')}
              value={me.org.id}
              onChange={(e) => switchOrg(e.target.value).catch((err) => toast.push(errorToast(err, t('shell.orgFail'))))}
            >
              {me.orgs.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          ) : (
            <span data-testid="org-switcher" className="acr-orgswitch__name acr-truncate">
              {me.org.name}
            </span>
          )}
        </div>
        <SidebarNav label={t('shell.nav')}>
          <span data-testid="nav-home" className="acr-navwrap">
            <SidebarLink to="/" end icon={<IconHome size={16} />}>
              {t('nav.home')}
            </SidebarLink>
          </span>
          <span data-testid="nav-deals" className="acr-navwrap">
            <SidebarLink to="/deals" icon={<IconDeal size={16} />}>
              {t('nav.deals')}
            </SidebarLink>
          </span>
          <span data-testid="nav-library" className="acr-navwrap">
            <SidebarLink to="/library" icon={<IconLibrary size={16} />}>
              {t('nav.library')}
            </SidebarLink>
          </span>
          <span data-testid="nav-agents" className="acr-navwrap">
            <SidebarLink to="/agents" icon={<IconAgent size={16} />}>
              {t('nav.agents')}
            </SidebarLink>
          </span>
          <span data-testid="nav-notifications" className="acr-navwrap">
            <SidebarLink to="/notifications" icon={<IconBell size={16} />} badge={unread}>
              {t('nav.notifications')}
            </SidebarLink>
          </span>
          <span data-testid="nav-settings" className="acr-navwrap">
            <SidebarLink to="/settings/preferences" icon={<IconSettings size={16} />}>
              {t('nav.settings')}
            </SidebarLink>
          </span>
        </SidebarNav>
      </div>
    </Sidebar>
  );
}

function UserMenu() {
  const { t, locale, setLocale, arabicDigits, setArabicDigits } = useI18n();
  const { theme, setTheme } = useTheme();
  const { me, logout } = useMe();
  const { openShortcuts } = useShell();
  const nav = useNavigate();
  if (!me) return null;
  return (
    <MenuButton
      up
      label={t('shell.userMenu')}
      testId="user-menu"
      triggerClassName="acr-usermenu"
      trigger={
        <>
          <Avatar name={me.user.name || me.user.email} size={24} />
          <span className="acr-usermenu__who">
            <span className="acr-usermenu__name acr-truncate">{me.user.name || me.user.email}</span>
            <span className="acr-usermenu__role">{t(`role.${me.role}`)}</span>
          </span>
          <IconChevronDown size={13} />
        </>
      }
    >
      {(close) => (
        <>
          <MenuLabel>{t('pref.language')}</MenuLabel>
          <Segmented
            testId="locale-toggle"
            label={t('pref.language')}
            value={locale}
            options={[
              { value: 'en', label: 'EN' },
              { value: 'ar', label: 'عربي' },
            ]}
            onChange={(l) => {
              setLocale(l);
              api.put('/me/preferences', { locale: l }).catch(() => undefined);
            }}
          />
          <MenuLabel>{t('pref.theme')}</MenuLabel>
          <Segmented
            testId="theme-toggle"
            label={t('pref.theme')}
            value={theme}
            options={[
              { value: 'light', label: t('pref.light') },
              { value: 'dark', label: t('pref.dark') },
              { value: 'system', label: t('pref.system') },
            ]}
            onChange={setTheme}
          />
          <MenuLabel>{t('pref.digits')}</MenuLabel>
          <Segmented
            label={t('pref.digits')}
            value={arabicDigits ? 'arab' : 'latn'}
            options={[
              { value: 'latn', label: '123' },
              { value: 'arab', label: '١٢٣' },
            ]}
            onChange={(v) => setArabicDigits(v === 'arab')}
          />
          <MenuSep />
          <MenuItem
            onSelect={() => {
              close();
              openShortcuts();
            }}
          >
            <IconKeyboard size={14} /> {t('shortcut.title')}
          </MenuItem>
          <MenuItem
            onSelect={() => {
              close();
              nav('/settings/preferences');
            }}
          >
            <IconSettings size={14} /> {t('nav.settings')}
          </MenuItem>
          <MenuItem
            testId="logout"
            onSelect={() => {
              close();
              logout().then(() => nav('/login'));
            }}
          >
            {t('shell.signOut')}
          </MenuItem>
        </>
      )}
    </MenuButton>
  );
}

/* ---------------- Top bar ---------------- */

function Topbar({ onNav }: { onNav: () => void }) {
  const { t } = useI18n();
  const { openPalette, openNotifications } = useShell();
  const { unread } = useOrgEvents();
  return (
    <header className="acr-topbar">
      <button type="button" className="acr-topbar__burger" aria-label={t('shell.menu')} onClick={onNav}>
        <IconCollapse size={18} />
      </button>
      <button type="button" className="acr-cmdtrigger" onClick={() => openPalette()} aria-label={t('palette.open')} aria-keyshortcuts="Control+K Meta+K">
        <IconSearch size={14} />
        <span className="acr-cmdtrigger__text">{t('palette.trigger')}</span>
        <span className="acr-cmdtrigger__keys" dir="ltr">
          <Kbd>{modKey}</Kbd>
          <Kbd>K</Kbd>
        </span>
      </button>
      <span className="acr-spacer-flex" />
      <button type="button" className="acr-bell" data-testid="notif-bell" aria-label={unread > 0 ? t('notif.bellUnread', { n: unread }) : t('notif.bell')} onClick={openNotifications}>
        <IconBell size={17} />
        {unread > 0 && (
          <span className="acr-bell__count acr-num" data-testid="notif-count">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>
    </header>
  );
}

/* ---------------- Notifications drawer ---------------- */

export function useNotifications(unreadOnly = false) {
  return useResource<Notification[]>(async (signal) => items(await api.get<Page<Notification> | Notification[]>('/notifications', { query: { limit: 100, unread: unreadOnly ? 1 : undefined }, signal })), [unreadOnly]);
}

export function NotificationList({ rows, onOpen }: { rows: Notification[]; onOpen: (n: Notification) => void }) {
  const { t, fmt } = useI18n();
  return (
    <ul className="acr-notifs">
      {rows.map((n) => (
        <li key={n.id}>
          <button type="button" className={cx('acr-notif', !n.read_at && 'is-unread')} data-testid="notif-item" data-id={n.id} onClick={() => onOpen(n)}>
            <span className="acr-notif__dot" aria-hidden="true" />
            <span className="acr-notif__main">
              <span className="acr-notif__title">
                {n.title}
                {!n.read_at && <span className="acr-sr-only"> ({t('notif.unread')})</span>}
              </span>
              {n.body && <span className="acr-notif__body">{n.body}</span>}
            </span>
            <span className="acr-notif__time acr-num">{fmt.relative(n.created_at)}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

export function useNotificationActions(reload: () => void) {
  const nav = useNavigate();
  const toast = useToast();
  const { t } = useI18n();
  const { setUnread } = useOrgEvents();
  const open = useCallback(
    (n: Notification) => {
      if (!n.read_at) {
        api
          .post(`/notifications/${n.id}/read`)
          .then(() => {
            setUnread(0);
            reload();
          })
          .catch(() => undefined);
      }
      if (n.link) nav(n.link);
    },
    [nav, reload, setUnread],
  );
  const readAll = useCallback(() => {
    api
      .post('/notifications/read-all')
      .then(() => {
        setUnread(0);
        reload();
      })
      .catch((e) => toast.push(errorToast(e, t('notif.readAllFail'))));
  }, [reload, setUnread, toast, t]);
  return { open, readAll };
}

function NotificationsDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n();
  const nav = useNavigate();
  const res = useNotifications();
  const { unread } = useOrgEvents((e) => {
    if (e.name === 'notification') res.reload();
  });
  const actions = useNotificationActions(res.reload);
  useEffect(() => {
    if (open) res.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const rows = (res.data ?? []).slice(0, 20);
  return (
    <>
      <Drawer
        testId="notif-drawer"
        open={open}
        onClose={onClose}
        title={t('notif.title')}
        closeLabel={t('common.close')}
        footer={
          <>
            <Button
              variant="ghost"
              disabled={unread === 0}
              onClick={() => actions.readAll()}
            >
              {t('notif.readAll')}
            </Button>
            <span className="acr-spacer-flex" />
            <Button
              variant="secondary"
              onClick={() => {
                onClose();
                nav('/notifications');
              }}
            >
              {t('notif.viewAll')}
            </Button>
          </>
        }
      >
        {res.loading && !res.data ? (
          <SkeletonRows rows={5} label={t('common.loading')} />
        ) : rows.length === 0 ? (
          <p className="acr-muted acr-pad">{t('notif.emptyDrawer')}</p>
        ) : (
          <NotificationList
            rows={rows}
            onOpen={(n) => {
              actions.open(n);
              onClose();
            }}
          />
        )}
      </Drawer>
    </>
  );
}

/* ---------------- Shortcut sheet ---------------- */

function ShortcutSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n();
  return (
    <>
      <Dialog open={open} onClose={onClose} title={t('shortcut.title')} closeLabel={t('common.close')} size="sm" testId="shortcut-sheet">
        <dl className="acr-shortcuts">
          {SHORTCUTS.map((s) => (
            <div key={s.labelKey} className="acr-shortcuts__row">
              <dt>{t(s.labelKey)}</dt>
              <dd>
                {s.keys.map((k, i) => (
                  <span key={k + i}>
                    {i > 0 && <span className="acr-faint"> {s.keys.length === 2 && s.keys[0].length > 1 ? '+' : s.labelKey === 'shortcut.listNav' ? '/' : t('shortcut.then')} </span>}
                    <Kbd>{k}</Kbd>
                  </span>
                ))}
              </dd>
            </div>
          ))}
        </dl>
      </Dialog>
    </>
  );
}

/* ---------------- Command palette ---------------- */

function Palette({ prefill, onClose }: { prefill: string; onClose: () => void }) {
  const { t } = useI18n();
  const nav = useNavigate();
  const toast = useToast();
  const { me } = useMe();
  const deals = useDeals();
  const agents = useAgents();
  const lib = useAllDeliverables(deals.data);
  const [value, setValue] = useState(prefill);
  const [dealId, setDealId] = useState('');
  const [agent, setAgent] = useState<Agent | null>(null);
  const recents = useMemo(() => recentPrompts(), []);
  const [busy, setBusy] = useState(false);

  async function run(text: string) {
    if (busy) return;
    setBusy(true);
    try {
      rememberPrompt(text);
      const job = await createJob({ prompt: text, deal_id: dealId || null, agent_id: agent?.id ?? null, inputs: { sources: 'deal_documents,sec_filings' } });
      onClose();
      nav(`/runs/${job.id}`);
    } catch (e) {
      setBusy(false);
      toast.push(errorToast(e, t('ask.failed')));
    }
  }

  const q = value.trim().toLowerCase();
  const match = (s: string) => q === '' || s.toLowerCase().includes(q);
  const groups: PaletteGroup[] = [];
  const go = (path: string) => () => nav(path);
  const pages = [
    { id: 'p-home', label: t('nav.home'), path: '/' },
    { id: 'p-deals', label: t('nav.deals'), path: '/deals' },
    { id: 'p-library', label: t('nav.library'), path: '/library' },
    { id: 'p-agents', label: t('nav.agents'), path: '/agents' },
    { id: 'p-notif', label: t('nav.notifications'), path: '/notifications' },
    { id: 'p-settings', label: t('nav.settings'), path: '/settings/preferences' },
  ].filter((p) => match(p.label));
  if (q === '' && recents.length)
    groups.push({
      id: 'recent',
      label: t('palette.recent'),
      items: recents.map((r, i) => ({ id: `r${i}`, label: r, onSelect: () => setValue(r), keepOpen: true })),
    });
  const dealItems = (deals.data ?? []).filter((d) => q !== '' && match(d.name + ' ' + (d.target ?? ''))).slice(0, 5);
  if (dealItems.length) groups.push({ id: 'deals', label: t('nav.deals'), items: dealItems.map((d: Deal) => ({ id: `d-${d.id}`, label: d.name, hint: d.target ?? undefined, icon: <IconDeal size={14} />, onSelect: go(`/deals/${d.id}`) })) });
  const agentItems = (agents.data ?? []).filter((a) => a.enabled !== false && q !== '' && match(a.name + ' ' + a.description)).slice(0, 5);
  if (agentItems.length)
    groups.push({
      id: 'agents',
      label: t('nav.agents'),
      items: agentItems.map((a) => ({ id: `a-${a.id}`, label: a.name, hint: t('palette.useAgent'), icon: <IconAgent size={14} />, onSelect: () => setAgent(a), keepOpen: true })),
    });
  const libItems = (lib.data ?? []).filter((d) => q !== '' && match(d.name + ' ' + d.deal_name)).slice(0, 5);
  if (libItems.length)
    groups.push({
      id: 'library',
      label: t('nav.library'),
      items: libItems.map((d) => ({ id: `l-${d.deal_id}-${d.name}`, label: d.name, hint: d.deal_name, icon: <IconLibrary size={14} />, onSelect: go(viewerPath(d.deal_id, d) ?? `/deals/${d.deal_id}?tab=library`) })),
    });
  if (pages.length) groups.push({ id: 'pages', label: t('palette.go'), items: pages.map((p) => ({ id: p.id, label: p.label, onSelect: go(p.path) })) });

  const dealOptions = deals.data ?? [];
  return (
    <>
      <CommandPalette
        open
        onClose={onClose}
        label={t('palette.label')}
        placeholder={t('palette.placeholder')}
        value={value}
        onValueChange={setValue}
        onSubmit={run}
        groups={groups}
        emptyLabel={t('palette.empty')}
        hints={{ enter: t('palette.hintRun'), navigate: t('palette.hintNav'), close: t('palette.hintClose') }}
        toolbar={
          <div className="acr-row">
            <label className="acr-chip">
              <span className="acr-sr-only">{t('ask.deal')}</span>
              <select aria-label={t('ask.deal')} value={dealId} onChange={(e) => setDealId(e.target.value)}>
                <option value="">{me ? t('ask.noDeal') : ''}</option>
                {dealOptions.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </label>
            {agent && (
              <span className="acr-chip acr-chip--accent">
                {agent.name}
                <button type="button" className="acr-chip__x" aria-label={t('ask.removeSkill', { name: agent.name })} onClick={() => setAgent(null)}>
                  ×
                </button>
              </span>
            )}
            {busy && <Badge tone="accent">{t('common.starting')}</Badge>}
          </div>
        }
      />
    </>
  );
}

export function ShellFallback(): ReactNode {
  return null;
}
