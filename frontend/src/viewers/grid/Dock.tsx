import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../../api/client';
import { Badge, Button, EmptyState, IconDownload, IconPlay, IconX, Skeleton, cx, useToast } from '../../ds';
import type { Tone as BadgeTone } from '../../ds';
import { useI18n } from '../../i18n';
import { SourceChip, errText } from './common';
import { useCell } from './store';
import type { CellStore } from './store';
import type { ChatReply, Column, Finding, RisksPayload, Row, TableInfo } from './types';

export type DockTab = 'cell' | 'chat' | 'risks';

interface DockProps {
  tab: DockTab;
  setTab: (t: DockTab) => void;
  onClose: () => void;
  dealId: string;
  gridId: string;
  store: CellStore;
  cell: { row: Row; col: Column } | null;
  canEdit: boolean;
  onRerun: (rowId: string, colId: string) => void;
}

export function Dock(p: DockProps) {
  const { t } = useI18n();
  const tabs: { id: DockTab; label: string }[] = [
    { id: 'cell', label: t('viewers2.dock.cell') },
    { id: 'chat', label: t('viewers2.dock.chat') },
    { id: 'risks', label: t('viewers2.dock.risks') },
  ];
  return (
    <aside className="vw-dock" aria-label={t('viewers2.dock.label')}>
      <div className="vw-dock__tabs" role="tablist">
        {tabs.map((x) => (
          <button key={x.id} type="button" role="tab" aria-selected={p.tab === x.id} className={cx('vw-dock__tab', p.tab === x.id && 'is-on')} onClick={() => p.setTab(x.id)}>
            {x.label}
          </button>
        ))}
        <span className="vw-spacer" />
        <button type="button" className="vw-iconbtn" aria-label={t('viewers2.common.close')} onClick={p.onClose}>
          <IconX size={14} />
        </button>
      </div>
      <div className="vw-dock__body">
        {p.tab === 'cell' && <CellPanel {...p} />}
        {p.tab === 'chat' && <ChatPanel dealId={p.dealId} gridId={p.gridId} />}
        {p.tab === 'risks' && <RisksPanel dealId={p.dealId} />}
      </div>
    </aside>
  );
}

function CellPanel({ dealId, store, cell, canEdit, onRerun }: DockProps) {
  const { t } = useI18n();
  const live = useCell(store, cell?.row.id ?? '', cell?.col.id ?? '');
  const [tables, setTables] = useState<TableInfo[]>([]);
  const docId = cell?.row.doc_id;
  useEffect(() => {
    setTables([]);
    if (!docId) return;
    const ctl = new AbortController();
    api.get<{ tables: TableInfo[] }>(`/documents/${docId}/tables`, { signal: ctl.signal }).then((r) => setTables(r.tables)).catch(() => undefined);
    return () => ctl.abort();
  }, [docId]);

  if (!cell) return <EmptyState title={t('viewers2.dock.pickCell')} body={t('viewers2.dock.pickCellBody')} action={{ label: t('viewers2.dock.openChat'), onClick: () => undefined }} />;
  const state = live?.state ?? 'queued';
  const tone: BadgeTone = state === 'done' ? 'positive' : state === 'failed' ? 'negative' : state === 'skipped' ? 'neutral' : 'info';
  return (
    <div className="vw-cellpanel" data-testid="cell-panel">
      <div className="vw-cellpanel__crumb">
        <span className="vw-muted">{cell.row.folder || t('viewers2.grid.unfiled')}</span>
        <span className="vw-cellpanel__doc">{cell.row.name}</span>
      </div>
      <h3 className="vw-cellpanel__col">{cell.col.name}</h3>
      <p className="vw-muted vw-cellpanel__prompt">{cell.col.prompt}</p>
      <div className="vw-cellpanel__meta">
        <Badge tone={tone} dot>
          {t(`viewers2.grid.state.${state}`)}
        </Badge>
        {live?.confidence && <Badge tone="neutral">{t('viewers2.dock.confidence', { level: t(`viewers2.dock.conf.${live.confidence}`) })}</Badge>}
        {canEdit && (
          <Button size="sm" variant="ghost" icon={<IconPlay size={12} />} onClick={() => onRerun(cell.row.id, cell.col.id)}>
            {t('viewers2.dock.rerun')}
          </Button>
        )}
      </div>
      {state === 'skipped' && <p className="vw-callout">{t('viewers2.grid.skipped', { reason: live?.reason ?? '' })}</p>}
      {state === 'failed' && <p className="vw-callout is-err">{live?.error ?? t('viewers2.grid.failed')}</p>}
      {(state === 'queued' || state === 'running') && (
        <div className="vw-cellpanel__wait">
          <Skeleton height={14} />
          <Skeleton height={14} width="80%" />
        </div>
      )}
      {state === 'done' && (
        <>
          <section>
            <h4 className="vw-h4">{t('viewers2.dock.answer')}</h4>
            <p className="vw-answer">{live?.value}</p>
          </section>
          {(live?.citations ?? []).length > 0 ? (
            <section>
              <h4 className="vw-h4">{t('viewers2.dock.sources')}</h4>
              <ul className="vw-quotes">
                {live!.citations.map((c, i) => (
                  <li key={c.token + i}>
                    <blockquote data-testid="cell-quote">{c.quote}</blockquote>
                    <SourceChip dealId={dealId} citation={c} label={t('viewers2.dock.sourceChip', { doc: cell.row.name, page: c.page ?? 1 })} />
                  </li>
                ))}
              </ul>
            </section>
          ) : (
            <p className="vw-muted">{t('viewers2.dock.noSource')}</p>
          )}
        </>
      )}
      {tables.length > 0 && (
        <section>
          <h4 className="vw-h4">{t('viewers2.dock.tables')}</h4>
          <ul className="vw-tables">
            {tables.map((x) => (
              <li key={x.n}>
                <span>{t('viewers2.dock.tableLabel', { n: x.n, page: x.page, rows: x.n_rows, cols: x.n_cols })}</span>
                <a className="vw-linkbtn" href={x.csv_url} download>
                  <IconDownload size={12} /> CSV
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function ChatPanel({ dealId, gridId }: { dealId: string; gridId: string }) {
  const { t, fmt } = useI18n();
  const toast = useToast();
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const [thread, setThread] = useState<{ q: string; a: ChatReply }[]>([]);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => end.current?.scrollIntoView({ block: 'nearest' }), [thread, busy]);

  async function ask(e: FormEvent) {
    e.preventDefault();
    const question = q.trim();
    if (!question || busy) return;
    setBusy(true);
    try {
      const a = await api.post<ChatReply>(`/grids/${gridId}/chat`, { question });
      setThread((s) => [...s, { q: question, a }]);
      setQ('');
    } catch (err) {
      toast.push({ kind: 'error', ...errText(err) });
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="vw-chat">
      <div className="vw-chat__log" aria-live="polite">
        {thread.length === 0 && <EmptyState title={t('viewers2.chat.emptyTitle')} body={t('viewers2.chat.emptyBody')} action={{ label: t('viewers2.chat.example'), onClick: () => setQ(t('viewers2.chat.example')) }} />}
        {thread.map((m, i) => (
          <div key={i} className="vw-chat__turn">
            <p className="vw-chat__q">{m.q}</p>
            <div className="vw-chat__a">
              <p className="vw-chat__lead">{m.a.answer.split('\n')[0]}</p>
              <ul className="vw-chat__rows">
                {m.a.rows.map((r) => (
                  <li key={r.row_id} className="vw-chat__row">
                    <div className="vw-chat__rowhead">
                      <span className="vw-chat__name">{r.name}</span>
                      {r.citations.slice(0, 2).map((c) => (
                        <SourceChip key={c.token} dealId={dealId} citation={c} label={`p.${c.page ?? 1}`} />
                      ))}
                    </div>
                    <p className="vw-chat__excerpt">{r.excerpt}</p>
                  </li>
                ))}
              </ul>
              <p className="vw-muted">{t('viewers2.chat.meta', { matched: m.a.matched, total: m.a.total, seconds: fmt.number(m.a.seconds, { maximumFractionDigits: 2 }) })}</p>
            </div>
          </div>
        ))}
        {busy && <Skeleton height={14} />}
        <div ref={end} />
      </div>
      <form className="vw-chat__form" onSubmit={(e) => void ask(e)}>
        <input
          data-testid="grid-chat-input"
          className="acr-input"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t('viewers2.chat.placeholder')}
          aria-label={t('viewers2.chat.placeholder')}
        />
        <Button type="submit" variant="primary" loading={busy} disabled={!q.trim()}>
          {t('viewers2.chat.ask')}
        </Button>
      </form>
    </div>
  );
}

const SEV_TONE: Record<string, BadgeTone> = { high: 'negative', medium: 'warning', low: 'info' };

function RisksPanel({ dealId }: { dealId: string }) {
  const { t } = useI18n();
  const [data, setData] = useState<RisksPayload | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    const ctl = new AbortController();
    api.get<RisksPayload>(`/deals/${dealId}/risks`, { signal: ctl.signal }).then(setData).catch((e) => {
      if (!(e instanceof DOMException)) setErr(errText(e).title);
    });
    return () => ctl.abort();
  }, [dealId]);
  return (
    <div data-testid="risks-panel" className="vw-risks">
      {err && <p className="vw-callout is-err">{err}</p>}
      {!data && !err && (
        <div className="vw-cellpanel__wait">
          <Skeleton height={14} />
          <Skeleton height={14} width="70%" />
        </div>
      )}
      {data && (
        <>
          <div className="vw-risks__sum">
            {Object.entries(data.summary.by_severity).map(([k, v]) => (
              <Badge key={k} tone={SEV_TONE[k] ?? 'neutral'}>
                {t(`viewers2.risks.sev.${k}`)} · {v}
              </Badge>
            ))}
          </div>
          {data.findings.length === 0 && <EmptyState title={t('viewers2.risks.none')} body={t('viewers2.risks.noneBody')} action={{ label: t('viewers2.common.close'), onClick: () => undefined }} />}
          <ul className="vw-risks__list">
            {data.findings.map((f: Finding) => (
              <li key={f.id} className="vw-risk">
                <div className="vw-risk__head">
                  <Badge tone={SEV_TONE[f.severity] ?? 'neutral'} dot>
                    {t(`viewers2.risks.sev.${f.severity}`)}
                  </Badge>
                  <span className="vw-risk__title">{f.title}</span>
                </div>
                <p className="vw-muted">{f.detail}</p>
                {f.quote && <blockquote>{f.quote}</blockquote>}
                {f.doc_id && f.citation_token && (
                  <SourceChip dealId={dealId} citation={{ token: f.citation_token, doc_id: f.doc_id, page: f.page }} label={`${f.doc_name?.split('/').pop() ?? ''} p.${f.page ?? 1}`} />
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
