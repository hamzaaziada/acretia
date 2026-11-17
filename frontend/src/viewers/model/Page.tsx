import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  Badge,
  Button,
  EmptyState,
  IconDownload,
  IconModel,
  SplitPane,
  Skeleton,
  TabPanel,
  Tabs,
  isTypingTarget,
} from '../../ds';
import { api } from '../../api/client';
import { useResource } from '../../api/hooks';
import { useI18n } from '../../i18n';
import { CitationPopoverHost } from '../shared/CitationPopover';
import { downloadHref, modelPath } from '../shared/api';
import type { AskResult, Audit, Explain, ModelCell, ModelCheck, ModelView, RecomputeResult } from '../shared/api';
import { useSafeToast } from '../shared/util';
import { Grid, colLetter } from './Grid';
import type { Flag } from './Grid';
import { formatValue, editText } from './format';
import { AskPanel, AssumptionsPanel, AuditPanel, CellInspector, ChecksPanel } from './panels';
import type { QA } from './panels';
import './model.css';

type Val = ModelCell['v'];
interface Sel {
  sheet: string;
  r: number;
  c: number;
}
type Status = { kind: 'idle' } | { kind: 'busy' } | { kind: 'done'; ms: number; n: number } | { kind: 'error'; message: string; hint?: string | null };

function parseRef(ref: string): Sel | null {
  const m = /^(.*)!\$?([A-Z]{1,3})\$?(\d+)$/.exec(ref);
  if (!m) return null;
  let c = 0;
  for (const ch of m[2]) c = c * 26 + ch.charCodeAt(0) - 64;
  return { sheet: m[1].replace(/^'|'$/g, ''), r: Number(m[3]), c };
}

export default function ModelViewerPage() {
  const { id: dealId = '', name = '' } = useParams();
  const [sp, setSp] = useSearchParams();
  const version = sp.get('version');
  const { t } = useI18n();
  const nav = useNavigate();
  const view = useResource<ModelView>((signal) => api.get<ModelView>(modelPath(dealId, name), { signal, query: { version } }), [dealId, name, version]);

  return (
    <div className="mv" data-testid="model-view">
      <CitationPopoverHost />
      {view.loading && !view.data && (
        <div className="mv__loading" role="status" aria-label={t('viewers.model.loading')}>
          <Skeleton width="30%" height={22} />
          <Skeleton height={320} />
        </div>
      )}
      {view.error && (
        <div className="mv__center">
          <EmptyState
            icon={<IconModel size={22} />}
            title={view.error.status === 404 ? t('viewers.model.notfound') : t('viewers.model.error')}
            body={view.error.hint ?? view.error.message ?? t('viewers.model.errorBody')}
            action={{ label: t('viewers.model.back'), onClick: () => nav(`/deals/${encodeURIComponent(dealId)}`) }}
            secondary={view.error.status === 404 ? undefined : { label: t('viewers.retry'), onClick: view.reload }}
          />
        </div>
      )}
      {view.data && (
        <Model
          key={`${view.data.name}:${view.data.version}`}
          data={view.data}
          onVersion={(v) => {
            const n = new URLSearchParams(sp);
            if (v === view.data!.latest) n.delete('version');
            else n.set('version', String(v));
            setSp(n);
          }}
          onSaved={() => {
            const n = new URLSearchParams(sp);
            n.delete('version');
            setSp(n);
            view.reload();
          }}
        />
      )}
    </div>
  );
}

function Model({ data, onVersion, onSaved }: { data: ModelView; onVersion: (v: number) => void; onSaved: () => void }) {
  const { t, fmt, arabicDigits } = useI18n();
  const toast = useSafeToast();
  const base = modelPath(data.deal_id, data.name);
  const cells = data.cells;

  const firstSheet = data.sheets.find((s) => s.name === 'IS')?.name ?? data.sheets[0]?.name ?? '';
  const [sel, setSel] = useState<Sel>(() => {
    const s = data.sheets.find((x) => x.name === firstSheet);
    return { sheet: firstSheet, r: (s?.freeze.rows ?? 0) + 1, c: (s?.freeze.cols ?? 0) + 1 };
  });
  const lastSel = useRef<Record<string, { r: number; c: number }>>({});
  const [overlay, setOverlay] = useState(false);
  const [rail, setRail] = useState('assumptions');
  const [focusToken, setFocusToken] = useState(0);

  const [edits, setEdits] = useState<Record<string, number | string>>({});
  const [over, setOver] = useState<Record<string, Val>>({});
  const [checks, setChecks] = useState<ModelCheck[]>(data.checks);
  const [outputs, setOutputs] = useState<Record<string, number | null>>({});
  const [status, setStatus] = useState<Status>({ kind: 'idle' });
  const [flash, setFlash] = useState<Record<string, number>>({});
  const [saving, setSaving] = useState(false);
  const seq = useRef(0);
  const nonce = useRef(0);
  const timer = useRef<number | undefined>(undefined);
  const flashTimer = useRef<number | undefined>(undefined);
  const abort = useRef<AbortController | null>(null);

  const editsRef = useRef(edits);
  editsRef.current = edits;
  const overRef = useRef(over);
  overRef.current = over;

  const valueOf = useCallback(
    (ref: string): Val => {
      if (ref in edits) return edits[ref] as Val;
      if (ref in over) return over[ref];
      return cells[ref]?.v ?? null;
    },
    [edits, over, cells],
  );
  const fmtOf = useCallback((ref: string) => cells[ref]?.fmt, [cells]);

  /* ---- live recompute ---- */
  const run = useCallback(
    (next: Record<string, number | string>) => {
      window.clearTimeout(timer.current);
      abort.current?.abort();
      const mine = ++seq.current;
      if (Object.keys(next).length === 0) {
        setOver({});
        setChecks(data.checks);
        setOutputs({});
        setStatus({ kind: 'idle' });
        return;
      }
      setStatus({ kind: 'busy' });
      timer.current = window.setTimeout(() => {
        const ctl = new AbortController();
        abort.current = ctl;
        api
          .post<RecomputeResult>(`${base}/recompute`, { changes: next, version: data.version }, { signal: ctl.signal })
          .then((res) => {
            if (mine !== seq.current) return;
            const prev = overRef.current;
            const nextOver: Record<string, Val> = {};
            const fl: Record<string, number> = {};
            nonce.current += 1;
            for (const [ref, d] of Object.entries(res.changed)) {
              nextOver[ref] = d.v_new;
              const before = ref in prev ? prev[ref] : (cells[ref]?.v ?? null);
              if (before !== d.v_new && !(ref in next)) fl[ref] = nonce.current;
            }
            setOver(nextOver);
            setFlash(fl);
            window.clearTimeout(flashTimer.current);
            flashTimer.current = window.setTimeout(() => setFlash({}), 1100);
            setChecks(res.checks);
            setOutputs(Object.fromEntries(res.outputs.map((o) => [o.ref, o.value])));
            setStatus({ kind: 'done', ms: res.ms, n: Object.keys(res.changed).length });
          })
          .catch((e: { name?: string; message?: string; hint?: string | null }) => {
            if (e?.name === 'AbortError' || mine !== seq.current) return;
            setStatus({ kind: 'error', message: e?.message || t('viewers.model.recomputeFailed'), hint: e?.hint });
          });
      }, 250);
    },
    [base, cells, data.checks, data.version, t],
  );

  useEffect(
    () => () => {
      window.clearTimeout(timer.current);
      window.clearTimeout(flashTimer.current);
      abort.current?.abort();
    },
    [],
  );

  const setInput = useCallback(
    (ref: string, value: number | string) => {
      const next = { ...editsRef.current };
      const orig = cells[ref]?.v;
      if (value === orig) delete next[ref];
      else next[ref] = value;
      setEdits(next);
      run(next);
    },
    [cells, run],
  );
  const reset = () => {
    setEdits({});
    run({});
  };

  /* ---- navigation inside the model ---- */
  const sheet = data.sheets.find((s) => s.name === sel.sheet) ?? data.sheets[0];
  const jump = useCallback(
    (ref: string) => {
      const p = parseRef(ref);
      if (!p || !data.sheets.some((s) => s.name === p.sheet)) return;
      setSel(p);
      setFocusToken((n) => n + 1);
    },
    [data.sheets],
  );
  const setSheet = useCallback(
    (name: string) => {
      lastSel.current[sel.sheet] = { r: sel.r, c: sel.c };
      const s = data.sheets.find((x) => x.name === name);
      const mem = lastSel.current[name];
      setSel({ sheet: name, r: mem?.r ?? (s?.freeze.rows ?? 0) + 1, c: mem?.c ?? (s?.freeze.cols ?? 0) + 1 });
    },
    [data.sheets, sel],
  );
  const stepSheet = useCallback(
    (d: 1 | -1) => {
      const i = data.sheets.findIndex((s) => s.name === sel.sheet);
      const n = data.sheets[(i + d + data.sheets.length) % data.sheets.length];
      if (n) setSheet(n.name);
    },
    [data.sheets, sel.sheet, setSheet],
  );
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || isTypingTarget(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === '[') stepSheet(-1);
      else if (e.key === ']') stepSheet(1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [stepSheet]);

  const selRef = `${sel.sheet}!${colLetter(sel.c)}${sel.r}`;
  const selCell = cells[selRef];

  /* ---- explain (precedents / dependents), cached per ref ---- */
  const explainCache = useRef(new Map<string, Explain>());
  const [explain, setExplain] = useState<Explain | null>(null);
  const [explainBusy, setExplainBusy] = useState(false);
  useEffect(() => {
    setExplain(null);
    if (!selCell) {
      setExplainBusy(false);
      return;
    }
    const hit = explainCache.current.get(selRef);
    if (hit) {
      setExplain(hit);
      return;
    }
    const ctl = new AbortController();
    setExplainBusy(true);
    const tm = window.setTimeout(() => {
      api
        .get<Explain>(`${base}/explain`, { query: { ref: selRef, version: data.version }, signal: ctl.signal })
        .then((x) => {
          explainCache.current.set(selRef, x);
          setExplain(x);
        })
        .catch(() => undefined)
        .finally(() => !ctl.signal.aborted && setExplainBusy(false));
    }, 90);
    return () => {
      window.clearTimeout(tm);
      ctl.abort();
    };
  }, [selRef, selCell, base, data.version]);

  /* ---- audit (tab audit + overlay flags), loaded on first need ---- */
  const [audit, setAudit] = useState<Audit | null>(null);
  const [auditBusy, setAuditBusy] = useState(false);
  const [auditErr, setAuditErr] = useState<string | null>(null);
  const loadAudit = useCallback(() => {
    setAuditBusy(true);
    setAuditErr(null);
    api
      .get<Audit>(`${base}/audit`, { query: { version: data.version } })
      .then(setAudit)
      .catch((e: { message?: string }) => setAuditErr(e?.message || t('viewers.model.auditFailed')))
      .finally(() => setAuditBusy(false));
  }, [base, data.version, t]);
  useEffect(() => {
    if ((overlay || rail === 'audit') && !audit && !auditBusy && !auditErr) loadAudit();
  }, [overlay, rail, audit, auditBusy, auditErr, loadAudit]);
  const flags = useMemo(() => {
    const f: Record<string, Flag> = {};
    if (audit) {
      for (const s of audit.sheets) {
        for (const h of s.hardcodes) f[h.ref] = 'hard';
        for (const e of s.errors) f[e.ref] = 'err';
      }
    }
    return f;
  }, [audit]);

  const checkStatus = useMemo(() => {
    const o: Record<string, 'pass' | 'fail'> = {};
    if (sel.sheet !== 'Checks') return o;
    for (const ref of Object.keys(cells)) {
      if (!ref.startsWith('Checks!')) continue;
      const v = valueOf(ref);
      if (v === 'OK') o[ref] = 'pass';
      else if (v === 'ERROR') o[ref] = 'fail';
    }
    return o;
  }, [sel.sheet, cells, valueOf]);

  /* ---- ask ---- */
  const [qa, setQa] = useState<QA[]>([]);
  const [asking, setAsking] = useState(false);
  const ask = (q: string) => {
    setRail('ask');
    setQa((h) => [...h, { q }]);
    setAsking(true);
    api
      .post<AskResult>(`${base}/ask`, { question: q, version: data.version })
      .then((a) => setQa((h) => h.map((x, i) => (i === h.length - 1 ? { ...x, a } : x))))
      .catch((e: { message?: string; hint?: string | null }) =>
        setQa((h) => h.map((x, i) => (i === h.length - 1 ? { ...x, error: [e?.message, e?.hint].filter(Boolean).join(' ') || t('viewers.model.askFailed') } : x))),
      )
      .finally(() => setAsking(false));
  };

  /* ---- save ---- */
  async function save() {
    const refs = Object.keys(edits);
    if (!refs.length || saving) return;
    setSaving(true);
    const note =
      t('viewers.model.saveNote') +
      ' ' +
      refs
        .slice(0, 3)
        .map((r) => `${cells[r] ? (data.assumptions.find((a) => a.ref === r)?.label ?? r) : r} → ${editText(edits[r], cells[r]?.fmt)}`)
        .join('; ') +
      (refs.length > 3 ? ` +${refs.length - 3}` : '');
    try {
      const res = await api.post<{ version: number }>(`${base}/save`, { changes: edits, version: data.version, note });
      toast({ kind: 'success', title: t('viewers.model.saved', { v: res.version }), body: note });
      onSaved();
    } catch (e) {
      const err = e as { message?: string; hint?: string | null };
      setStatus({ kind: 'error', message: err.message || t('viewers.model.saveFailed'), hint: err.hint });
      toast({ kind: 'error', title: t('viewers.model.saveFailed'), body: err.message, hint: err.hint ?? undefined });
    } finally {
      setSaving(false);
    }
  }

  const nEdits = Object.keys(edits).length;
  const failing = checks.filter((c) => c.status === 'fail').length;
  const stale = data.version !== data.latest;
  const suggestions = useMemo(() => data.outputs.slice(0, 3).map((o) => t('viewers.model.askWhat', { what: o.label })), [data.outputs, t]);

  const statusText =
    status.kind === 'busy'
      ? t('viewers.model.calculating')
      : status.kind === 'done'
        ? t('viewers.model.recomputed', { ms: fmt.integer(Math.round(status.ms)), n: fmt.integer(status.n) })
        : status.kind === 'error'
          ? [status.message, status.hint].filter(Boolean).join(' ')
          : t('viewers.model.upToDate');

  const railItems = [
    { id: 'assumptions', label: t('viewers.model.tab.assumptions'), count: data.assumptions.length || undefined },
    { id: 'checks', label: t('viewers.model.tab.checks'), count: failing || undefined },
    { id: 'ask', label: t('viewers.model.tab.ask') },
    { id: 'audit', label: t('viewers.model.tab.audit'), count: audit && audit.totals.hardcodes + audit.totals.errors ? audit.totals.hardcodes + audit.totals.errors : undefined },
  ];

  const selFormula = selCell?.f ?? (valueOf(selRef) === null ? '' : formatValue(valueOf(selRef), selCell?.fmt, { arabicDigits }));

  const left = (
    <div className="mv__left">
      <div className="mv__fbar" data-testid="formula-bar">
        <span className="mv__fbar-ref acr-mono" dir="ltr">
          {selRef}
        </span>
        <span className="mv__fx" aria-hidden="true">
          fx
        </span>
        <span className="mv__fbar-text acr-mono" dir="ltr" title={selFormula}>
          {selFormula}
        </span>
      </div>
      {sheet && (
        <Grid
          sheet={sheet}
          cells={cells}
          valueOf={valueOf}
          overlay={overlay}
          editable={data.editable && !stale}
          selected={{ r: sel.r, c: sel.c }}
          onSelect={(r, c) => setSel((s) => ({ ...s, r, c }))}
          onCommit={setInput}
          edits={edits}
          flash={flash}
          flags={flags}
          checkStatus={checkStatus}
          onSheetStep={stepSheet}
          focusToken={focusToken}
        />
      )}
      <div className="mv__sheets" role="tablist" aria-label={t('viewers.model.sheets')}>
        {data.sheets.map((s) => (
          <button
            key={s.name}
            type="button"
            role="tab"
            className={`mv__sheet${s.name === sel.sheet ? ' is-active' : ''}`}
            aria-selected={s.name === sel.sheet}
            data-testid="sheet-tab"
            data-sheet={s.name}
            onClick={() => setSheet(s.name)}
          >
            {s.name}
          </button>
        ))}
        <span className="mv__keys">
          <kbd>[</kbd> <kbd>]</kbd> {t('viewers.model.keysSheets')} · <kbd>E</kbd> {t('viewers.model.keysEdit')}
        </span>
      </div>
    </div>
  );

  const right = (
    <aside className="mv__rail" aria-label={t('viewers.model.rail')}>
      <CellInspector refKey={selRef} cell={selCell} explain={explain} loading={explainBusy} valueOf={valueOf} fmtOf={fmtOf} onJump={jump} edited={selRef in edits} />
      <div className="mv__tabs">
        <Tabs items={railItems} value={rail} onChange={setRail} label={t('viewers.model.rail')} idPrefix="mv" />
        <TabPanel idPrefix="mv" id={rail}>
          {rail === 'assumptions' && (
            <AssumptionsPanel items={data.assumptions} edits={edits} editable={data.editable && !stale} onChange={setInput} onReset={reset} onJump={jump} />
          )}
          {rail === 'checks' && <ChecksPanel checks={checks} onJump={jump} />}
          {rail === 'ask' && <AskPanel history={qa} busy={asking} onAsk={ask} onJump={jump} suggestions={suggestions} dirty={nEdits > 0} valueOf={valueOf} />}
          {rail === 'audit' && <AuditPanel audit={audit} loading={auditBusy} error={auditErr} onJump={jump} onRetry={loadAudit} />}
        </TabPanel>
      </div>
    </aside>
  );

  return (
    <>
      <header className="mv__top">
        <div className="mv__title">
          <nav className="mv__crumbs" aria-label={t('viewers.model.crumbs')}>
            <Link to={`/deals/${encodeURIComponent(data.deal_id)}`}>{t('viewers.pdf.deal')}</Link>
            <span aria-hidden="true">/</span>
          </nav>
          <h1 dir="auto">{data.name}</h1>
          <label className="mv__ver">
            <span className="acr-sr-only">{t('viewers.model.version')}</span>
            <select value={data.version} onChange={(e) => onVersion(Number(e.target.value))} aria-label={t('viewers.model.version')} data-testid="model-version">
              {Array.from({ length: data.latest }, (_, i) => data.latest - i).map((v) => (
                <option key={v} value={v}>
                  {v === data.latest ? t('viewers.model.versionLatest', { v }) : `v${v}`}
                </option>
              ))}
            </select>
          </label>
          {stale && <Badge tone="warning">{t('viewers.model.older')}</Badge>}
          <Badge tone={failing ? 'negative' : 'positive'} dot>
            {failing ? t('viewers.model.checksFail', { n: failing }) : t('viewers.model.checksOk')}
          </Badge>
        </div>
        <div className="mv__actions">
          <span className={`mv__status is-${status.kind}`} data-testid="recompute-status" data-state={status.kind} role="status" aria-live="polite">
            <span className="mv__dot" aria-hidden="true" />
            {statusText}
          </span>
          <button
            type="button"
            role="switch"
            aria-checked={overlay}
            className={`mv__toggle${overlay ? ' is-on' : ''}`}
            data-testid="audit-overlay-toggle"
            onClick={() => setOverlay((o) => !o)}
          >
            <span className="mv__toggle-track" aria-hidden="true">
              <span className="mv__toggle-knob" />
            </span>
            {t('viewers.model.overlay')}
          </button>
          <a className="acr-btn acr-btn--secondary acr-btn--md" href={downloadHref(data.deal_id, data.name, data.version)} download data-testid="model-download">
            <IconDownload size={14} />
            <span className="acr-btn__label">{t('viewers.model.download')}</span>
          </a>
          <Button variant="primary" onClick={save} loading={saving} disabled={nEdits === 0 || !data.editable || stale} data-testid="model-save" title={nEdits === 0 ? t('viewers.model.saveHint') : undefined}>
            {nEdits ? t('viewers.model.saveN', { n: nEdits }) : t('viewers.model.save')}
          </Button>
        </div>
      </header>

      {data.outputs.length > 0 && (
        <div className="mv__kpis" role="group" aria-label={t('viewers.model.outputs')} data-testid="model-outputs">
          {data.outputs.map((o) => {
            const cur = outputs[o.ref] ?? (cells[o.ref]?.v as number | null | undefined) ?? null;
            const orig = cells[o.ref]?.v;
            const delta = typeof cur === 'number' && typeof orig === 'number' && orig !== 0 && Math.abs(cur - orig) > 1e-9 ? cur / orig - 1 : null;
            return (
              <button type="button" key={o.ref} className="mv__kpi" onClick={() => jump(o.ref)} data-ref={o.ref}>
                <span className="mv__kpi-label" dir="auto">
                  {o.label}
                </span>
                <span key={cur ?? 'x'} className={`mv__kpi-val acr-num${delta !== null ? ' is-flash' : ''}`} dir="ltr">
                  {formatValue(cur, cells[o.ref]?.fmt, { arabicDigits }).trim() || '–'}
                </span>
                {delta !== null && (
                  <span className={`mv__kpi-delta acr-num ${delta > 0 ? 'is-up' : 'is-down'}`} dir="ltr">
                    {delta > 0 ? '+' : '−'}
                    {fmt.number(Math.abs(delta) * 100, { maximumFractionDigits: 1 })}%
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}

      <div className="mv__body">
        <SplitPane start={left} end={right} initial={70} min={45} max={82} label={t('viewers.model.resize')} />
      </div>
    </>
  );
}
