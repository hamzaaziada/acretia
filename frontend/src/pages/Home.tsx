import { useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Badge, Button, EmptyState, IconDeck, IconDeal, IconDoc, IconGrid, IconHistory, IconModel, IconPlus, Panel, SectionLabel, SkeletonRows, Table, useToast } from '../ds';
import type { Column } from '../ds';
import { api } from '../api/client';
import { items, useDeals, useOrgEvents, useResource } from '../api/hooks';
import type { Job, JobCreate, Page } from '../api/types';
import { useI18n } from '../i18n';
import { PromptBox } from '../features/PromptBox';
import { NewDealDialog } from '../features/NewDealDialog';
import { SAMPLE_DEAL } from '../features/NewDealDialog';
import { STARTERS, createJob, errorToast, jobDuration, rememberPrompt, statusTone, useAgents, useAllDeliverables, viewerPath } from '../app/lib';

const ICON = { model: IconModel, grid: IconGrid, deck: IconDeck, doc: IconDoc, deal: IconDeal, history: IconHistory } as const;

export function timeSavedLabel(j: Job, fmt: { number: (n: number) => string }, t: (k: string, v?: Record<string, string | number>) => string): string {
  const ts = j.time_saved;
  const h = ts?.t_h_minutes;
  if (!ts || !h || ts.t_a_minutes == null) return '—';
  const saved = Math.max(0, h.mid - ts.t_a_minutes);
  return t('run.savedMin', { n: fmt.number(Math.round(saved)) });
}

export default function Home() {
  const { t, fmt } = useI18n();
  const nav = useNavigate();
  const toast = useToast();
  const deals = useDeals();
  const agents = useAgents();
  const jobs = useResource<Job[]>(async (signal) => items(await api.get<Page<Job> | Job[]>('/jobs', { query: { limit: 10 }, signal })), []);
  const lib = useAllDeliverables(deals.data);
  const [prompt, setPrompt] = useState('');
  const [dealId, setDealId] = useState('');
  const [busy, setBusy] = useState(false);
  const [newDeal, setNewDeal] = useState(false);
  const askRef = useRef<HTMLTextAreaElement>(null);
  useOrgEvents((e) => {
    if (e.name === 'job') jobs.reload();
  });

  async function start(body: JobCreate) {
    setBusy(true);
    try {
      rememberPrompt(body.prompt);
      const job = await createJob(body);
      nav(`/runs/${job.id}`);
    } catch (e) {
      setBusy(false);
      toast.push(errorToast(e, t('ask.failed')));
    }
  }

  const rows = jobs.data ?? [];
  const dealList = deals.data ?? [];
  const firstRun = !jobs.loading && rows.length === 0;
  const columns: Column<Job>[] = [
    { key: 'prompt', header: t('runs.prompt'), render: (j) => <Link to={`/runs/${j.id}`} className="acr-truncate acr-runlink">{j.prompt}</Link> },
    { key: 'status', header: t('runs.status'), render: (j) => <Badge tone={statusTone(j.status)} dot>{t(`status.${j.status}`)}</Badge>, sortValue: (j) => j.status },
    { key: 'agent', header: t('runs.agent'), render: (j) => j.agent_name ?? j.kind, sortValue: (j) => j.agent_name ?? j.kind },
    { key: 'deal', header: t('runs.deal'), render: (j) => j.deal_name ?? '—' },
    { key: 'cost', header: t('runs.cost'), numeric: true, render: (j) => fmt.currency(j.cost_usd, 'USD', 4), sortValue: (j) => j.cost_usd },
    { key: 'dur', header: t('runs.duration'), numeric: true, render: (j) => { const d = jobDuration(j); return d == null ? '—' : fmt.duration(d); } },
    { key: 'saved', header: t('runs.timeSaved'), numeric: true, render: (j) => timeSavedLabel(j, fmt, t) },
    { key: 'when', header: t('runs.when'), numeric: true, render: (j) => fmt.relative(j.created_at ?? j.started_at ?? new Date()), sortValue: (j) => j.created_at ?? j.started_at ?? '' },
  ];

  const recentDeliverables = (lib.data ?? []).slice(0, 6);

  return (
    <div className="acr-page acr-home">
      <section className="acr-home__hero">
        <h1 className="acr-home__title">{t('home.title')}</h1>
        <p className="acr-muted acr-home__sub">{t('home.subtitle')}</p>
        <PromptBox ref={askRef} prompt={prompt} onPrompt={setPrompt} deals={dealList} agents={agents.data ?? []} dealId={dealId} onDeal={setDealId} onSubmit={start} busy={busy} />
      </section>

      <section aria-labelledby="starters-h">
        <SectionLabel>
          <span id="starters-h">{t('home.starters')}</span>
        </SectionLabel>
        <div className="acr-starters">
          {STARTERS.map((s) => {
            const Ic = ICON[s.icon];
            return (
              <button
                key={s.task}
                type="button"
                className="acr-starter"
                data-testid="starter-task"
                data-task={s.task}
                onClick={() => {
                  setPrompt(t(s.promptKey));
                  askRef.current?.focus();
                  askRef.current?.scrollIntoView({ block: 'nearest' });
                }}
              >
                <span className="acr-starter__icon">
                  <Ic size={16} />
                </span>
                <span className="acr-starter__title">{t(s.titleKey)}</span>
                <span className="acr-starter__prompt">{t(s.promptKey)}</span>
              </button>
            );
          })}
        </div>
      </section>

      {!deals.loading && dealList.length === 0 && (
        <section className="acr-sample">
          <div>
            <h2 className="acr-sample__title">{t('home.sample.title')}</h2>
            <p className="acr-muted">{t('home.sample.body')}</p>
          </div>
          <Button variant="primary" icon={<IconPlus size={14} />} onClick={() => setNewDeal(true)}>
            {t('home.sample.cta')}
          </Button>
        </section>
      )}

      <div className="acr-home__cols acr-home__cols--stack">
        <Panel title={t('home.recentRuns')} flush className="acr-home__runs">
          <div data-testid="recent-runs">
            {jobs.loading && !jobs.data ? (
              <SkeletonRows rows={4} label={t('common.loading')} />
            ) : firstRun ? (
              <EmptyState
                title={t('home.noRuns.title')}
                body={t('home.noRuns.body')}
                action={{ label: t('home.noRuns.cta'), onClick: () => { setPrompt(t(STARTERS[0].promptKey)); askRef.current?.focus(); } }}
              />
            ) : (
              <Table
                caption={t('home.recentRuns')}
                columns={columns}
                rows={rows}
                rowKey={(j) => j.id}
                onRowActivate={(j) => nav(`/runs/${j.id}`)}
                rowProps={(j) => ({ 'data-testid': 'run-row', 'data-id': j.id, 'data-status': j.status })}
              />
            )}
          </div>
        </Panel>
        <Panel title={t('home.recentDeliverables')} flush className="acr-home__deliv">
          {lib.loading && !lib.data ? (
            <SkeletonRows rows={4} label={t('common.loading')} />
          ) : recentDeliverables.length === 0 ? (
            <EmptyState title={t('home.noDeliverables.title')} body={t('home.noDeliverables.body')} action={{ label: t('nav.deals'), onClick: () => nav('/deals') }} />
          ) : (
            <ul className="acr-list">
              {recentDeliverables.map((d) => {
                const v = viewerPath(d.deal_id, d);
                return (
                  <li key={`${d.deal_id}/${d.name}`} className="acr-list__row">
                    <Link to={v ?? `/deals/${d.deal_id}?tab=library`} className="acr-list__main">
                      <span className="acr-list__title acr-truncate">{d.name}</span>
                      <span className="acr-list__sub acr-truncate">
                        {d.deal_name} · v{d.latest_version} · {fmt.relative(d.updated_at)}
                      </span>
                    </Link>
                    <Badge>{d.kind}</Badge>
                  </li>
                );
              })}
            </ul>
          )}
        </Panel>
      </div>
      <NewDealDialog open={newDeal} onClose={() => setNewDeal(false)} initial={SAMPLE_DEAL} onCreated={(d) => nav(`/deals/${d.id}`)} />
    </div>
  );
}
