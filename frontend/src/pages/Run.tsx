import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  Badge,
  Button,
  Dialog,
  EmptyState,
  IconAlert,
  IconButton,
  IconClock,
  IconDownload,
  IconExternal,
  IconInfo,
  IconStop,
  IconPlay,
  IconThumbDown,
  IconThumbUp,
  PageHeader,
  Panel,
  Skeleton,
  SkeletonRows,
  Stepper,
  Textarea,
  Tooltip,
  useToast,
  cx,
} from '../ds';
import type { StepItem } from '../ds';
import { api } from '../api/client';
import { useJob } from '../api/hooks';
import type { RunState } from '../api/hooks';
import { TERMINAL_JOB } from '../api/types';
import type { DeliverableData } from '../api/types';
import { useI18n } from '../i18n';
import { CitationChip } from '../features/citations';
import { ApprovalCard } from '../features/Approvals';
import { errorToast, savedEstimate, statusTone, viewerPath } from '../app/lib';

export default function Run() {
  const { jobId } = useParams();
  const { t, fmt } = useI18n();
  const nav = useNavigate();
  const toast = useToast();
  const run = useJob(jobId);
  const { state, elapsed } = run;
  const job = state.job;
  const status = state.status;
  const active = !TERMINAL_JOB.includes(status);
  const [now, setNow] = useState(() => Date.now());
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!active) return;
    const h = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(h);
  }, [active]);

  if (run.error?.status === 404) {
    return (
      <div className="acr-page">
        <h1 className="acr-sr-only">{t('run.notFound.title')}</h1>
        <EmptyState title={t('run.notFound.title')} body={t('run.notFound.body')} action={{ label: t('nav.home'), onClick: () => nav('/') }} />
      </div>
    );
  }
  if (run.loading && !job) {
    return (
      <div className="acr-page" aria-busy="true">
        <h1 className="acr-sr-only">{t('common.loading')}</h1>
        <Skeleton width={320} height={22} />
        <div className="acr-page__gap" />
        <SkeletonRows rows={6} label={t('common.loading')} />
      </div>
    );
  }

  async function cancel() {
    setBusy(true);
    try {
      await api.post(`/jobs/${jobId}/cancel`);
      setConfirmCancel(false);
    } catch (e) {
      toast.push(errorToast(e, t('run.cancelFailed')));
    } finally {
      setBusy(false);
    }
  }
  async function resume() {
    setBusy(true);
    try {
      await api.post(`/jobs/${jobId}/resume`);
      run.reconnect();
      run.reload();
    } catch (e) {
      toast.push(errorToast(e, t('run.resumeFailed')));
    } finally {
      setBusy(false);
    }
  }

  const stepSeconds = (id: string): number | null => {
    const s = state.steps[id];
    if (s?.seconds != null && s.status !== 'running') return s.seconds;
    if (!s?.started_at) return null;
    const end = s.finished_at ? new Date(s.finished_at).getTime() : s.status === 'running' ? now : null;
    return end ? Math.max(0, (end - new Date(s.started_at).getTime()) / 1000) : null;
  };

  const items: StepItem[] = state.order.map((id) => {
    const s = state.steps[id];
    const secs = stepSeconds(id);
    const meta = [secs != null ? fmt.duration(secs) : null, s.cost_usd != null ? fmt.currency(s.cost_usd, 'USD', 4) : null].filter(Boolean).join(' · ');
    const attach = state.approval && state.approval.step_id === id;
    return {
      id,
      title: s.title,
      status: s.status,
      detail: s.detail,
      meta: meta || undefined,
      statusLabel: t(`step.${s.status}`),
      children: attach && jobId ? <ApprovalCard key={state.approval?.step_id} jobId={jobId} approval={state.approval!} onDone={() => run.dispatchLocal({ kind: 'clear-approval' })} /> : undefined,
    };
  });
  const orphanApproval = state.approval && !state.order.includes(state.approval.step_id);

  // The deal id is known once the job has one (given, or created by the run). Never build a deal route without it.
  const dealId = job?.deal_id ?? state.dealId ?? null;
  const title = job?.prompt ?? t('run.title');
  return (
    <div className="acr-page acr-run" data-testid="run-view" data-status={status} data-id={jobId}>
      <PageHeader
        breadcrumb={
          <nav aria-label={t('common.breadcrumbs')} data-testid="breadcrumbs" className="acr-crumbs">
            <Link to="/">{t('nav.home')}</Link>
            <span aria-hidden="true">/</span>
            {dealId ? <Link to={`/deals/${dealId}`}>{job?.deal_name ?? t('run.deal')}</Link> : <span>{t('run.noDeal')}</span>}
            <span aria-hidden="true">/</span>
            <span aria-current="page">{t('run.crumb')}</span>
          </nav>
        }
        title={title}
        meta={
          <div className="acr-run__meta">
            <span data-testid="run-status" data-status={status} className="acr-run__status">
              <Badge tone={statusTone(status)} dot>
                {t(`status.${status}`)}
              </Badge>
            </span>
            <span className="acr-muted">{job?.agent_name ?? job?.kind ?? t('run.agentAuto')}</span>
            {job?.source && job.source !== 'app' && <Badge tone="info">{t(`source.via.${job.source}`)}</Badge>}
            <span className="acr-run__elapsed acr-num" data-testid="run-elapsed" title={t('run.elapsed')}>
              <IconClock size={13} /> {fmt.duration(elapsed)}
            </span>
          </div>
        }
        actions={
          <>
            {active && (
              <Button variant="secondary" icon={<IconStop size={13} />} data-testid="run-cancel" onClick={() => setConfirmCancel(true)}>
                {t('run.cancel')}
              </Button>
            )}
            {status === 'failed' && (
              <Button variant="primary" icon={<IconPlay size={13} />} loading={busy} data-testid="run-resume" onClick={resume}>
                {t('run.resume')}
              </Button>
            )}
          </>
        }
      />

      {status === 'failed' && (
        <div className="acr-banner acr-banner--negative" role="alert">
          <IconAlert size={16} />
          <div>
            <strong>{state.error || t('run.failed')}</strong>
            <div>{state.hint || t('run.failedHint')}</div>
          </div>
        </div>
      )}
      {run.connection === 'retrying' && active && (
        <div className="acr-banner acr-banner--warning" role="status">
          <IconInfo size={16} /> {t('run.reconnecting')}
        </div>
      )}

      <div className="acr-run__grid">
        <div className="acr-run__main">
          <Panel
            title={t('run.plan')}
            actions={
              state.estimate && active ? (
                <span className="acr-faint acr-num">
                  {t('run.estimate', { cost: fmt.currency(state.estimate.cost_usd, 'USD', 2), time: fmt.duration(state.estimate.seconds) })}
                </span>
              ) : undefined
            }
          >
            {items.length === 0 ? (
              <div aria-busy="true">
                <SkeletonRows rows={4} label={t('run.planning')} />
              </div>
            ) : (
              <Stepper steps={items} label={t('run.plan')} />
            )}
            {orphanApproval && jobId && <ApprovalCard jobId={jobId} approval={state.approval!} onDone={() => run.dispatchLocal({ kind: 'clear-approval' })} />}
          </Panel>
          {state.logs.length > 0 && (
            <details className="acr-log">
              <summary>{t('run.log', { n: state.logs.length })}</summary>
              <ul>
                {state.logs.map((l, i) => (
                  <li key={i} className={cx('acr-log__row', `is-${l.level}`)}>
                    <span className="acr-log__lvl">{l.level}</span> {l.message}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
        <aside className="acr-run__rail" aria-label={t('run.rail')}>
          <CostPanel state={state} />
          <TimeSavedPanel run={run.state} />
          <SourcesPanel state={state} dealId={dealId} jobId={jobId ?? ''} />
          <DeliverablesPanel items={state.deliverables} done={status === 'done'} />
          <FeedbackPanel jobId={jobId ?? ''} />
        </aside>
      </div>

      <Dialog
        open={confirmCancel}
        onClose={() => setConfirmCancel(false)}
        title={t('run.cancelConfirm.title')}
        description={t('run.cancelConfirm.body')}
        closeLabel={t('common.close')}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmCancel(false)}>
              {t('run.cancelConfirm.keep')}
            </Button>
            <Button variant="danger" loading={busy} onClick={cancel}>
              {t('run.cancel')}
            </Button>
          </>
        }
      >
        <p className="acr-muted">{t('run.cancelConfirm.note')}</p>
      </Dialog>
    </div>
  );
}

function CostPanel({ state }: { state: RunState }) {
  const { t, fmt } = useI18n();
  return (
    <Panel title={t('run.cost')}>
      <dl className="acr-kv">
        <div>
          <dt>{t('run.cost.usd')}</dt>
          <dd className="acr-num" data-testid="run-cost">
            {fmt.currency(state.cost.cost_usd, 'USD', 4)}
          </dd>
        </div>
        <div>
          <dt>{t('run.cost.tokens')}</dt>
          <dd className="acr-num" data-testid="run-tokens">
            {fmt.integer(state.cost.tokens)}
          </dd>
        </div>
      </dl>
    </Panel>
  );
}

function TimeSavedPanel({ run }: { run: RunState }) {
  const { t, fmt } = useI18n();
  const ts = run.timeSaved ?? run.job?.time_saved ?? null;
  const est = savedEstimate(ts);
  const tip = t('run.saved.tip', { source: est?.source || ts?.baseline || t('run.saved.noSource') });
  let body: React.ReactNode;
  if (!ts) {
    body = <p className="acr-muted">{TERMINAL_JOB.includes(run.status) ? t('run.saved.none') : t('run.saved.pending')}</p>;
  } else if (!est) {
    body = <p className="acr-muted">{ts.baseline ?? t('run.saved.noBaseline')}</p>;
  } else {
    body = (
      <>
        <div className="acr-saved__big acr-num" data-testid="run-time-saved-value">
          {t('run.savedMin', { n: fmt.integer(Math.round(est.saved)) })}
        </div>
        <div className="acr-muted acr-num">
          {t('run.saved.range', { low: fmt.integer(Math.round(est.low)), high: fmt.integer(Math.round(est.high)) })}
          {est.pct != null && <> · {fmt.percent(est.pct, 0)}</>}
        </div>
        <div className="acr-saved__basis">
          {t('run.saved.basis')}: <span className="acr-faint">{est.source}</span>
        </div>
      </>
    );
  }
  return (
    <Panel
      title={t('run.saved.title')}
      actions={
        <Tooltip text={tip}>
          <span tabIndex={0} className="acr-infotip" aria-label={tip}>
            <IconInfo size={14} />
          </span>
        </Tooltip>
      }
    >
      <div data-testid="run-time-saved">
        {body}
        <Badge tone="warning">{t('run.saved.estimate')}</Badge>
      </div>
    </Panel>
  );
}

function SourcesPanel({ state, dealId, jobId }: { state: RunState; dealId: string | null; jobId: string }) {
  const { t, fmt } = useI18n();
  const n = state.sources.length;
  return (
    <Panel
      title={`${t('run.sources')}${n ? ` (${fmt.integer(n)})` : ''}`}
      actions={
        n > 0 ? (
          <a className="acr-linkbtn" data-testid="download-sources" href={`/api/v1/jobs/${jobId}/sources.zip`} download>
            <IconDownload size={13} /> {t('run.sources.download')}
          </a>
        ) : undefined
      }
    >
      {n === 0 ? (
        <p className="acr-muted">{t('run.sources.empty')}</p>
      ) : (
        <ul className="acr-sources">
          {state.sources.map((s) => (
            <li key={s.citation_token}>
              <CitationChip source={s} dealId={dealId} />
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function DeliverablesPanel({ items, done }: { items: DeliverableData[]; done: boolean }) {
  const { t } = useI18n();
  return (
    <Panel title={t('run.deliverables')}>
      {items.length === 0 ? (
        <p className="acr-muted">{done ? t('run.deliverables.none') : t('run.deliverables.empty')}</p>
      ) : (
        <ul className="acr-list">
          {items.map((d) => {
            const v = viewerPath(d.deal_id, d);
            const dl = d.url || `/api/v1/deals/${d.deal_id}/deliverables/${encodeURIComponent(d.name)}/versions/${d.version}/download`;
            return (
              <li key={`${d.name}-${d.version}`} className="acr-list__row" data-testid="deliverable-row-run" data-id={`${d.deal_id}/${d.name}`}>
                <div className="acr-list__main">
                  <span className="acr-list__title acr-truncate">{d.name}</span>
                  <span className="acr-list__sub">
                    {d.kind} · v{d.version}
                  </span>
                </div>
                {v ? (
                  <Link to={v} className="acr-linkbtn" data-testid="deliverable-link" data-kind={d.kind}>
                    <IconExternal size={13} /> {t('run.open')}
                  </Link>
                ) : (
                  <a className="acr-linkbtn" href={dl} download data-testid="deliverable-link" data-kind={d.kind}>
                    <IconDownload size={13} /> {t('common.download')}
                  </a>
                )}
                {v && (
                  <a className="acr-linkbtn" href={dl} download data-testid="deliverable-download" aria-label={`${t('common.download')} ${d.name}`}>
                    <IconDownload size={13} />
                  </a>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

function FeedbackPanel({ jobId }: { jobId: string }) {
  const { t } = useI18n();
  const toast = useToast();
  const [rating, setRating] = useState<'up' | 'down' | null>(null);
  const [comment, setComment] = useState('');
  const [sent, setSent] = useState(false);

  async function post(r: 'up' | 'down', c?: string): Promise<boolean> {
    try {
      // POST /jobs/{id}/feedback {rating: 'up'|'down', comment?} (parity item 69); one row per (run, user), posting again replaces it.
      await api.post(`/jobs/${jobId}/feedback`, { rating: r, comment: c || undefined });
      return true;
    } catch (e) {
      toast.push(errorToast(e, t('feedback.failed')));
      return false;
    }
  }
  async function choose(r: 'up' | 'down') {
    setRating(r);
    const ok = await post(r);
    if (ok) toast.push({ kind: 'success', title: t('feedback.thanks') });
  }
  async function sendComment() {
    if (!rating) return;
    if (await post(rating, comment)) {
      setSent(true);
      toast.push({ kind: 'success', title: t('feedback.thanks') });
    }
  }
  return (
    <Panel title={t('feedback.title')}>
      <div className="acr-row">
        <IconButton aria-label={t('feedback.up')} variant="secondary" data-testid="feedback-up" aria-pressed={rating === 'up'} className={cx(rating === 'up' && 'is-on')} onClick={() => choose('up')}>
          <IconThumbUp size={15} />
        </IconButton>
        <IconButton aria-label={t('feedback.down')} variant="secondary" data-testid="feedback-down" aria-pressed={rating === 'down'} className={cx(rating === 'down' && 'is-on')} onClick={() => choose('down')}>
          <IconThumbDown size={15} />
        </IconButton>
      </div>
      {rating && !sent && (
        <div className="acr-stack acr-feedback__comment">
          <Textarea label={t('feedback.comment')} rows={2} value={comment} onChange={(e) => setComment(e.target.value)} />
          <Button size="sm" disabled={!comment.trim()} onClick={sendComment}>
            {t('feedback.send')}
          </Button>
        </div>
      )}
    </Panel>
  );
}
