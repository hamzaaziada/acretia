import { useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Badge, Button, Dialog, EmptyState, IconExternal, IconPlay, Input, PageHeader, Panel, SkeletonRows, Skeleton, Stat, TabPanel, Table, Tabs, useToast } from '../ds';
import type { Column, TabItem } from '../ds';
import { ApiError, api } from '../api/client';
import { items, normalizeDeal, useMe, useOrgEvents, useResource } from '../api/hooks';
import type { DealDetail, Job, Page } from '../api/types';
import { useI18n } from '../i18n';
import { DocumentsTab } from '../features/Documents';
import { DeliverablesTable } from '../features/Deliverables';
import type { DeliverableRowData } from '../features/Deliverables';
import { errorToast, jobDuration, statusTone, viewerPath } from '../app/lib';
import { Switch } from '../firm/lib/Switch';
import { useShell } from '../app/shell';
import { dealTone } from './Deals';

type TabId = 'overview' | 'documents' | 'grid' | 'models' | 'decks' | 'library' | 'activity';
const TABS: TabId[] = ['overview', 'documents', 'grid', 'models', 'decks', 'library', 'activity'];

export default function Deal() {
  const { id = '' } = useParams();
  const [sp, setSp] = useSearchParams();
  const { t } = useI18n();
  const nav = useNavigate();
  const res = useResource<DealDetail | null>(async (signal) => (id ? normalizeDeal(await api.get<DealDetail>(`/deals/${id}`, { signal })) : null), [id]);
  const delivs = useResource<DeliverableRowData[]>(
    async (signal) => (id ? items(await api.get<Page<DeliverableRowData> | DeliverableRowData[]>(`/deals/${id}/deliverables`, { signal })).map((d) => ({ ...d, deal_id: id })) : []),
    [id],
  );
  const tabParam = sp.get('tab') as TabId | null;
  const tab: TabId = tabParam && TABS.includes(tabParam) ? tabParam : 'overview';
  const deal = res.data;

  if (res.error?.status === 404)
    return (
      <div className="acr-page">
        <h1 className="acr-sr-only">{t('deal.notFound.title')}</h1>
        <EmptyState title={t('deal.notFound.title')} body={t('deal.notFound.body')} action={{ label: t('nav.deals'), onClick: () => nav('/deals') }} />
      </div>
    );
  if (res.loading && !deal)
    return (
      <div className="acr-page" aria-busy="true">
        <h1 className="acr-sr-only">{t('common.loading')}</h1>
        <Skeleton width={300} height={22} />
        <div className="acr-page__gap" />
        <SkeletonRows rows={6} label={t('common.loading')} />
      </div>
    );
  if (!deal)
    return (
      <div className="acr-page">
        <h1 className="acr-sr-only">{t('deal.loadFailed')}</h1>
        <EmptyState title={t('deal.loadFailed')} body={res.error?.hint ?? res.error?.message} action={{ label: t('common.retry'), onClick: res.reload }} />
      </div>
    );

  const all = delivs.data ?? [];
  const byKind = (k: string) => all.filter((d) => (d.view ?? (d.kind === 'xlsx' ? 'model' : d.kind === 'pptx' ? 'deck' : d.kind === 'grid' ? 'grid' : '')) === k);
  const tabItems: TabItem[] = TABS.map((k) => ({
    id: k,
    label: t(`deal.tab.${k}`),
    count: k === 'documents' ? deal.counts?.documents : k === 'library' ? all.length : k === 'models' ? byKind('model').length : k === 'decks' ? byKind('deck').length : k === 'grid' ? byKind('grid').length : undefined,
  }));

  return (
    <div className="acr-page acr-deal">
      <PageHeader
        breadcrumb={
          <nav aria-label={t('common.breadcrumbs')} data-testid="breadcrumbs" className="acr-crumbs">
            <Link to="/deals">{t('nav.deals')}</Link>
            <span aria-hidden="true">/</span>
            <span aria-current="page">{deal.name}</span>
          </nav>
        }
        title={deal.name}
        subtitle={[deal.target, deal.sector].filter(Boolean).join(' · ') || undefined}
        meta={
          <Badge tone={dealTone(deal.status)} dot>
            {t(`deal.status.${deal.status}`)}
          </Badge>
        }
        actions={<RollForward dealId={id} />}
      />
      <Tabs
        items={tabItems}
        value={tab}
        label={t('deal.tabs')}
        idPrefix="deal"
        onChange={(k) => setSp(k === 'overview' ? {} : { tab: k }, { replace: true })}
        testIds={(k) => `deal-tab-${k}`}
      />
      <TabPanel idPrefix="deal" id={tab}>
        {tab === 'overview' && <Overview deal={deal} dealId={id} />}
        {tab === 'documents' && <DocumentsTab dealId={id} />}
        {tab === 'grid' && <KindList dealId={id} kind="grid" rows={byKind('grid')} loading={delivs.loading && !delivs.data} />}
        {tab === 'models' && <KindList dealId={id} kind="model" rows={byKind('model')} loading={delivs.loading && !delivs.data} />}
        {tab === 'decks' && <KindList dealId={id} kind="deck" rows={byKind('deck')} loading={delivs.loading && !delivs.data} />}
        {tab === 'library' && (
          <DeliverablesTable rows={all} onChanged={delivs.reload} emptyAction={{ label: t('home.title'), onClick: () => nav('/') }} />
        )}
        {tab === 'activity' && <Activity deal={deal} />}
      </TabPanel>
    </div>
  );
}

function Overview({ deal, dealId }: { deal: DealDetail; dealId: string }) {
  const { t, fmt } = useI18n();
  const nav = useNavigate();
  const { openPalette } = useShell();
  const jobs = useResource<Job[]>(async (signal) => items(await api.get<Page<Job> | Job[]>('/jobs', { query: { deal_id: dealId, limit: 8 }, signal })), [dealId]);
  useOrgEvents((e) => {
    if (e.name === 'job') jobs.reload();
  });
  const defs = Object.entries(deal.definitions ?? {});
  const cols: Column<Job>[] = [
    { key: 'prompt', header: t('runs.prompt'), render: (j) => <Link to={`/runs/${j.id}`}>{j.prompt}</Link> },
    { key: 'status', header: t('runs.status'), render: (j) => <Badge tone={statusTone(j.status)} dot>{t(`status.${j.status}`)}</Badge> },
    { key: 'cost', header: t('runs.cost'), numeric: true, render: (j) => fmt.currency(j.cost_usd, 'USD', 4) },
    { key: 'dur', header: t('runs.duration'), numeric: true, render: (j) => { const d = jobDuration(j); return d == null ? '—' : fmt.duration(d); } },
  ];
  return (
    <div className="acr-overview">
      <div className="acr-stats">
        <Stat label={t('deal.tab.documents')} value={fmt.integer(deal.counts?.documents ?? 0)} />
        <Stat label={t('nav.library')} value={fmt.integer(deal.counts?.deliverables ?? 0)} />
        <Stat label={t('deal.runs')} value={fmt.integer(deal.counts?.jobs ?? 0)} />
        <Stat label={t('lib.updated')} value={deal.updated_at ? fmt.relative(deal.updated_at) : '—'} />
      </div>
      <div className="acr-home__cols">
        <Panel title={t('deal.recentRuns')} flush actions={<Button size="sm" variant="secondary" icon={<IconPlay size={12} />} onClick={() => openPalette()}>{t('deal.askAbout')}</Button>}>
          {jobs.loading && !jobs.data ? (
            <SkeletonRows rows={3} label={t('common.loading')} />
          ) : (
            <Table caption={t('deal.recentRuns')} columns={cols} rows={jobs.data ?? []} rowKey={(j) => j.id} onRowActivate={(j) => nav(`/runs/${j.id}`)} empty={<EmptyState title={t('deal.noRuns.title')} body={t('deal.noRuns.body')} action={{ label: t('deal.askAbout'), onClick: () => openPalette() }} />} />
          )}
        </Panel>
        <div className="acr-stack">
          <Panel title={t('deal.instructions')}>
            {deal.instructions ? <p className="acr-prewrap">{deal.instructions}</p> : <p className="acr-muted">{t('deal.instructions.none')}</p>}
          </Panel>
          <Panel title={t('deal.definitions')}>
            {defs.length === 0 ? (
              <p className="acr-muted">{t('deal.definitions.none')}</p>
            ) : (
              <dl className="acr-kv acr-kv--stack">
                {defs.map(([k, v]) => (
                  <div key={k}>
                    <dt>{k}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

function KindList({ dealId, kind, rows, loading }: { dealId: string; kind: 'grid' | 'model' | 'deck'; rows: DeliverableRowData[]; loading: boolean }) {
  const { t, fmt } = useI18n();
  const nav = useNavigate();
  const { openPalette } = useShell();
  if (loading) return <SkeletonRows rows={4} label={t('common.loading')} />;
  const cols: Column<DeliverableRowData>[] = [
    { key: 'name', header: t('lib.name'), sortValue: (d) => d.name, render: (d) => <span className="acr-strong">{d.name}</span> },
    { key: 'version', header: t('lib.version'), numeric: true, render: (d) => `v${fmt.integer(d.latest_version)}` },
    { key: 'updated', header: t('lib.updated'), numeric: true, sortValue: (d) => d.updated_at, render: (d) => fmt.relative(d.updated_at) },
    {
      key: 'open',
      header: '',
      render: (d) => {
        const v = viewerPath(dealId, d) ?? (kind === 'grid' ? `/deals/${dealId}/grid` : null);
        return v ? (
          <Link to={v} className="acr-linkbtn" onClick={(e) => e.stopPropagation()}>
            <IconExternal size={13} /> {t('common.open')}
          </Link>
        ) : null;
      },
    },
  ];
  return (
    <Table
      caption={t(`deal.tab.${kind === 'model' ? 'models' : kind === 'deck' ? 'decks' : 'grid'}`)}
      columns={cols}
      rows={rows}
      rowKey={(d) => d.name}
      rowProps={(d) => ({ 'data-testid': 'deliverable-row', 'data-id': `${dealId}/${d.name}`, 'data-kind': d.kind })}
      onRowActivate={(d) => {
        const v = viewerPath(dealId, d) ?? (kind === 'grid' ? `/deals/${dealId}/grid` : null);
        if (v) nav(v);
      }}
      empty={
        <EmptyState
          title={t(`deal.empty.${kind}.title`)}
          body={t(`deal.empty.${kind}.body`)}
          action={{ label: t(`deal.empty.${kind}.cta`), onClick: () => (kind === 'grid' ? nav(`/deals/${dealId}/grid`) : openPalette(t(`deal.empty.${kind}.prompt`))) }}
        />
      }
    />
  );
}

function Activity({ deal }: { deal: DealDetail }) {
  const { t, fmt } = useI18n();
  const nav = useNavigate();
  const rows = deal.activity ?? [];
  if (rows.length === 0) return <EmptyState title={t('deal.activity.empty.title')} body={t('deal.activity.empty.body')} action={{ label: t('deal.tab.documents'), onClick: () => nav(`/deals/${deal.id}?tab=documents`) }} />;
  return (
    <ol className="acr-timeline" data-testid="activity-timeline">
      {rows.map((a, i) => (
        <li key={a.id ?? i} className="acr-timeline__item">
          <span className="acr-timeline__dot" aria-hidden="true" />
          <div>
            <div>
              <strong>{a.actor ?? t('deal.activity.system')}</strong> <span className="acr-muted">{a.title ?? a.summary ?? a.action}</span>
              {a.status && <span className="acr-faint"> · {a.status}</span>}
              {a.target && <span className="acr-mono acr-faint"> {a.target}</span>}
            </div>
            <time className="acr-faint acr-num" dateTime={a.at}>
              {fmt.dateTime(a.at)}
            </time>
          </div>
        </li>
      ))}
    </ol>
  );
}

interface WatchState {
  enabled: boolean;
  ticker: string;
  last_checked: string | null;
}

/** Roll forward (member+) and the automatic-update switch (`POST /deals/{id}/rollforward`, `GET/PUT /deals/{id}/watch`). */
function RollForward({ dealId }: { dealId: string }) {
  const { t, fmt } = useI18n();
  const { me } = useMe();
  const toast = useToast();
  const canAct = me?.role === 'owner' || me?.role === 'member';
  const watch = useResource<WatchState | null>(async (signal) => (canAct ? api.get<WatchState>(`/deals/${dealId}/watch`, { signal }) : null), [dealId, canAct]);
  const [busy, setBusy] = useState(false);
  const [ask, setAsk] = useState<null | 'roll' | 'watch'>(null);
  const [ticker, setTicker] = useState('');
  if (!canAct) return null;

  async function roll(tk?: string) {
    setBusy(true);
    try {
      await api.post(`/deals/${dealId}/rollforward`, tk ? { ticker: tk } : {});
      toast.push({ kind: 'success', title: t('deal.rollforward.started'), body: t('deal.rollforward.startedBody') });
      setAsk(null);
    } catch (e) {
      if (e instanceof ApiError && e.code === 'ticker_needed') setAsk('roll');
      else toast.push(errorToast(e, t('deal.rollforward.failed')));
    } finally {
      setBusy(false);
    }
  }
  async function setWatch(enabled: boolean, tk?: string) {
    setBusy(true);
    try {
      await api.put(`/deals/${dealId}/watch`, tk ? { enabled, ticker: tk } : { enabled });
      toast.push({ kind: 'success', title: t(enabled ? 'deal.watch.on' : 'deal.watch.off') });
      setAsk(null);
      watch.reload();
    } catch (e) {
      if (enabled && e instanceof ApiError && e.code === 'ticker_needed') setAsk('watch');
      else toast.push(errorToast(e, t('deal.watch.failed')));
    } finally {
      setBusy(false);
    }
  }
  const w = watch.data;
  return (
    <div className="acr-rollforward" data-testid="rollforward-actions" style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--acr-s-3) var(--acr-s-4)' }}>
      <Switch
        checked={!!w?.enabled}
        disabled={busy || watch.loading}
        label={t('deal.watch.label')}
        hint={w?.enabled ? (w.last_checked ? t('deal.watch.checked', { when: fmt.relative(w.last_checked) }) : t('deal.watch.never')) : undefined}
        onChange={(v) => setWatch(v)}
        testId="watch-toggle"
      />
      <Button variant="secondary" loading={busy} title={t('deal.rollforward.hint')} data-testid="rollforward-button" onClick={() => roll()}>
        {t('deal.rollforward')}
      </Button>
      <Dialog
        open={ask !== null}
        onClose={() => setAsk(null)}
        title={t('deal.rollforward.ticker.title')}
        description={t('deal.rollforward.ticker.body')}
        closeLabel={t('common.close')}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setAsk(null)}>
              {t('common.cancel')}
            </Button>
            <Button variant="primary" disabled={!ticker.trim()} loading={busy} onClick={() => (ask === 'watch' ? setWatch(true, ticker.trim()) : roll(ticker.trim()))}>
              {t('deal.rollforward.ticker.go')}
            </Button>
          </>
        }
      >
        <Input label={t('deal.rollforward.ticker.label')} value={ticker} dir="ltr" onChange={(e) => setTicker(e.target.value.toUpperCase())} />
      </Dialog>
    </div>
  );
}
