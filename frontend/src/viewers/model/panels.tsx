import { useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Badge, Button, IconAlert, IconCheck, IconChevronDown, IconChevronRight, IconExternal, IconLink, IconSearch, Skeleton } from '../../ds';
import { useI18n } from '../../i18n';
import type { Assumption, Audit, AskResult, Explain, ModelCell, ModelCheck } from '../shared/api';
import { editText, formatValue, parseInput } from './format';

type Val = ModelCell['v'];

const CLASS_TONE: Record<string, 'info' | 'neutral' | 'positive'> = { input: 'info', calc: 'neutral', link: 'positive' };

/* ------------------------------------------------------------------ cell inspector */

export interface InspectorProps {
  refKey: string;
  cell: ModelCell | undefined;
  explain: Explain | null;
  loading: boolean;
  valueOf: (ref: string) => Val;
  fmtOf: (ref: string) => string | undefined;
  onJump: (ref: string) => void;
  edited: boolean;
}

function RefRow({ label, refKey, value, fmt, onJump, range }: { label: string; refKey: string; value: Val; fmt?: string; onJump: (r: string) => void; range?: boolean }) {
  const { arabicDigits } = useI18n();
  return (
    <li>
      <button type="button" className="mv__ref" onClick={() => onJump(refKey)} disabled={range}>
        <span className="mv__ref-label" dir="auto">
          {label || refKey}
        </span>
        <span className="mv__ref-id acr-mono" dir="ltr">
          {refKey}
        </span>
        <span className="mv__ref-val acr-num" dir="ltr">
          {value === null || value === undefined ? '–' : formatValue(value, fmt, { arabicDigits })}
        </span>
      </button>
    </li>
  );
}

export function CellInspector({ refKey, cell, explain, loading, valueOf, fmtOf, onJump, edited }: InspectorProps) {
  const { t, arabicDigits } = useI18n();
  const [more, setMore] = useState(false);
  useEffect(() => setMore(false), [refKey]);
  const v = valueOf(refKey);
  const cls = cell?.cls ?? 'label';
  const prec = (explain?.precedents ?? []).filter((p) => !p.empty);
  const deps = explain?.dependents ?? [];
  const LIM = 6;
  return (
    <section className="mv__card mv__insp" aria-label={t('viewers.model.inspector')} data-testid="cell-inspector" data-ref={refKey}>
      <header className="mv__insp-head">
        <div className="mv__insp-title" dir="auto">
          {explain?.label || refKey}
        </div>
        <div className="mv__insp-meta">
          <span className="acr-mono mv__insp-ref" dir="ltr">
            {refKey}
          </span>
          <Badge tone={CLASS_TONE[cls] ?? 'neutral'}>{t(`viewers.model.cls.${cls}`)}</Badge>
          {edited && <Badge tone="accent">{t('viewers.model.edited')}</Badge>}
        </div>
      </header>
      <div className="mv__insp-value acr-num" dir="ltr" data-testid="inspector-value">
        {v === null || v === undefined || v === '' ? '–' : formatValue(v, cell?.fmt, { arabicDigits })}
      </div>
      {cell?.f && (
        <div className="mv__formula" dir="ltr" data-testid="inspector-formula">
          <span className="mv__fx">fx</span>
          <code>{cell.f}</code>
        </div>
      )}
      {(cell?.citation_token || cell?.note || cell?.xbrl_concept || cell?.url) && (
        <div className="mv__source">
          <div className="mv__label">{t('viewers.model.source')}</div>
          {cell.note && <p dir="auto">{cell.note}</p>}
          {cell.xbrl_concept && (
            <p className="acr-mono mv__dim" dir="ltr">
              {cell.xbrl_concept}
            </p>
          )}
          <div className="mv__source-actions">
            {cell.citation_token && (
              <button type="button" className="mv__link" data-cite={cell.citation_token} data-testid="inspector-citation">
                <IconLink size={13} /> {t('viewers.model.openSource')}
              </button>
            )}
            {cell.url && /^https?:\/\//.test(cell.url) && (
              <a className="mv__link" href={cell.url} target="_blank" rel="noopener noreferrer">
                <IconExternal size={13} /> {t('viewers.model.openLink')}
              </a>
            )}
          </div>
        </div>
      )}
      {loading && !explain && (
        <div className="mv__skel">
          <Skeleton height={12} />
          <Skeleton width="70%" height={12} />
        </div>
      )}
      {explain && (
        <>
          <div className="mv__trace" data-testid="inspector-precedents">
            <div className="mv__label">
              {t('viewers.model.precedents')} <span className="mv__count acr-num">{prec.length}</span>
            </div>
            {prec.length === 0 ? (
              <p className="mv__dim">{cell?.f ? t('viewers.model.noPrecedents') : t('viewers.model.hardcoded')}</p>
            ) : (
              <ul>
                {(more ? prec : prec.slice(0, LIM)).map((p) => (
                  <RefRow key={p.cell} label={p.label} refKey={p.cell} value={p.range ? null : valueOf(p.cell)} fmt={fmtOf(p.cell)} onJump={onJump} range={p.range} />
                ))}
              </ul>
            )}
          </div>
          <div className="mv__trace" data-testid="inspector-dependents">
            <div className="mv__label">
              {t('viewers.model.dependents')} <span className="mv__count acr-num">{explain.n_dependents ?? deps.length}</span>
            </div>
            {deps.length === 0 ? (
              <p className="mv__dim">{t('viewers.model.noDependents')}</p>
            ) : (
              <ul>
                {(more ? deps : deps.slice(0, LIM)).map((p) => (
                  <RefRow key={p.cell} label={p.label} refKey={p.cell} value={valueOf(p.cell)} fmt={fmtOf(p.cell)} onJump={onJump} />
                ))}
              </ul>
            )}
          </div>
          {(prec.length > LIM || deps.length > LIM) && (
            <button type="button" className="mv__more" onClick={() => setMore((m) => !m)}>
              {more ? t('viewers.model.less') : t('viewers.model.more')}
            </button>
          )}
        </>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ assumptions */

interface AssumptionsProps {
  items: Assumption[];
  edits: Record<string, number | string>;
  editable: boolean;
  onChange: (ref: string, value: number) => void;
  onReset: () => void;
  onJump: (ref: string) => void;
}

function shortPeriod(p: string | null) {
  return p ? p.replace(/^FY(20)?/, "FY'") : '';
}

function AssumptionInput({ a, value, edited, disabled, onCommit, onJump }: { a: Assumption; value: number; edited: boolean; disabled: boolean; onCommit: (n: number) => void; onJump: () => void }) {
  const { t, arabicDigits } = useI18n();
  const [draft, setDraft] = useState<string | null>(null);
  const [bad, setBad] = useState(false);
  const shown = formatValue(value, a.fmt, { arabicDigits }).replace(/[ \s]+$/g, '');
  const done = () => {
    if (draft === null) return;
    const n = parseInput(draft, a.fmt);
    if (n === null) {
      setBad(true);
      window.setTimeout(() => setBad(false), 1600);
    } else if (Math.abs(n - value) > 1e-12) onCommit(n);
    setDraft(null);
  };
  return (
    <input
      className={`mv__ain acr-num${edited ? ' is-edited' : ''}${bad ? ' is-bad' : ''}`}
      data-testid="assumption-input"
      data-ref={a.ref}
      aria-label={`${a.label}${a.period && !a.label.includes(a.period) ? ` ${a.period}` : ''}`}
      aria-invalid={bad || undefined}
      title={bad ? t('viewers.model.badNumber') : a.ref}
      inputMode="decimal"
      dir="ltr"
      disabled={disabled}
      value={draft ?? shown}
      onFocus={(e) => {
        setDraft(editText(value, a.fmt));
        window.setTimeout(() => e.target.select(), 0);
        onJump();
      }}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={done}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          done();
          (e.target as HTMLInputElement).blur();
        } else if (e.key === 'Escape') {
          setDraft(null);
          (e.target as HTMLInputElement).blur();
        }
      }}
    />
  );
}

export function AssumptionsPanel({ items, edits, editable, onChange, onReset, onJump }: AssumptionsProps) {
  const { t } = useI18n();
  const [q, setQ] = useState('');
  const groups = useMemo(() => {
    const ql = q.trim().toLowerCase();
    const out: { section: string; rows: { key: string; label: string; items: Assumption[] }[] }[] = [];
    for (const a of items) {
      if (ql && !`${a.row_label} ${a.section ?? ''}`.toLowerCase().includes(ql)) continue;
      const sec = a.section ?? a.sheet;
      let g = out.find((x) => x.section === sec);
      if (!g) out.push((g = { section: sec, rows: [] }));
      const key = `${a.sheet}|${a.row_label}`;
      let r = g.rows.find((x) => x.key === key);
      if (!r) g.rows.push((r = { key, label: a.row_label || a.label, items: [] }));
      r.items.push(a);
    }
    return out;
  }, [items, q]);
  const n = Object.keys(edits).length;
  return (
    <div className="mv__assump" data-testid="assumptions-panel">
      <div className="mv__toolbar">
        <label className="mv__find">
          <IconSearch size={13} aria-hidden="true" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('viewers.model.filterAssumptions')} aria-label={t('viewers.model.filterAssumptions')} dir="auto" />
        </label>
        <Button size="sm" variant="ghost" disabled={n === 0} onClick={onReset} data-testid="assumptions-reset">
          {t('viewers.model.reset', { n })}
        </Button>
      </div>
      {!editable && <p className="mv__note">{t('viewers.model.readOnly')}</p>}
      {groups.length === 0 && <p className="mv__dim mv__pad">{items.length ? t('viewers.model.noMatch') : t('viewers.model.noAssumptions')}</p>}
      {groups.map((g) => (
        <section key={g.section} className="mv__asec">
          <h3 className="mv__label">{g.section}</h3>
          {g.rows.map((r) => {
            const multi = r.items.length > 1;
            return (
              <div key={r.key} className="mv__arow">
                <div className="mv__alabel" dir="auto">
                  {r.label}
                  {r.items[0].unit && <span className="mv__unit">{r.items[0].unit}</span>}
                </div>
                <div className={`mv__ainputs${multi ? ' is-multi' : ''}`} style={multi ? { gridTemplateColumns: `repeat(${Math.min(r.items.length, 5)}, minmax(0, 1fr))` } : undefined}>
                  {r.items.map((a) => (
                    <label key={a.ref} className="mv__acell">
                      {multi && <span className="mv__aper">{shortPeriod(a.period)}</span>}
                      <AssumptionInput
                        a={a}
                        value={typeof edits[a.ref] === 'number' ? (edits[a.ref] as number) : a.value}
                        edited={a.ref in edits}
                        disabled={!editable}
                        onCommit={(v) => onChange(a.ref, v)}
                        onJump={() => onJump(a.ref)}
                      />
                    </label>
                  ))}
                </div>
              </div>
            );
          })}
        </section>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ checks */

export function ChecksPanel({ checks, onJump }: { checks: ModelCheck[]; onJump: (ref: string) => void }) {
  const { t } = useI18n();
  const failing = checks.filter((c) => c.status === 'fail');
  if (!checks.length) return <p className="mv__dim mv__pad">{t('viewers.model.noChecks')}</p>;
  return (
    <div className="mv__checks" data-testid="checks-panel">
      <div className={`mv__summary ${failing.length ? 'is-fail' : 'is-pass'}`} role="status">
        {failing.length ? <IconAlert size={16} /> : <IconCheck size={16} />}
        <span>{failing.length ? t('viewers.model.checksFail', { n: failing.length }) : t('viewers.model.checksPass', { n: checks.length })}</span>
      </div>
      <ul>
        {checks.map((c) => (
          <li key={c.name + c.ref}>
            <button type="button" className="mv__check-row" onClick={() => onJump(c.failing?.[0] ?? c.ref)}>
              <span className="mv__check-badge" data-testid="check-badge" data-status={c.status} role="img" aria-label={t(c.status === 'pass' ? 'viewers.model.checkPass' : 'viewers.model.checkFail')}>
                {c.status === 'pass' ? <IconCheck size={12} /> : <IconAlert size={12} />}
              </span>
              <span className="mv__check-name" dir="auto">
                {c.name}
              </span>
              <span className="mv__check-val acr-mono">{c.value}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ------------------------------------------------------------------ ask */

export interface QA {
  q: string;
  a?: AskResult;
  error?: string;
}

export function AskPanel({ history, busy, onAsk, onJump, suggestions, dirty, valueOf }: { history: QA[]; busy: boolean; onAsk: (q: string) => void; onJump: (ref: string) => void; suggestions: string[]; dirty: boolean; valueOf: (ref: string) => Val }) {
  const { t, arabicDigits } = useI18n();
  const [q, setQ] = useState('');
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => end.current?.scrollIntoView({ block: 'nearest' }), [history.length, busy]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const s = q.trim();
    if (s && !busy) {
      onAsk(s);
      setQ('');
    }
  };
  return (
    <div className="mv__ask" data-testid="ask-panel">
      <div className="mv__ask-log" aria-live="polite">
        {history.length === 0 && (
          <div className="mv__ask-empty">
            <p>{t('viewers.model.askIntro')}</p>
            <div className="mv__chips">
              {suggestions.map((s) => (
                <button key={s} type="button" className="mv__chip" onClick={() => onAsk(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {history.map((h, i) => (
          <div key={i} className="mv__qa">
            <div className="mv__q" dir="auto">
              {h.q}
            </div>
            {h.a && (
              <div className="mv__a" data-testid="ask-answer">
                <p dir="auto">{h.a.answer}</p>
                {h.a.cells_detail.length > 0 && (
                  <div className="mv__chips">
                    {h.a.cells_detail.slice(0, 8).map((c) => (
                      <button key={c.ref} type="button" className="mv__chip is-ref" onClick={() => onJump(c.ref)} title={c.label}>
                        <span className="acr-mono">{c.ref}</span>
                        <span className="acr-num">{formatValue(valueOf(c.ref), c.fmt ?? undefined, { arabicDigits })}</span>
                      </button>
                    ))}
                  </div>
                )}
                <p className="mv__how">
                  {h.a.reconciled && h.a.cells.length > 0 && <IconCheck size={12} />} {h.a.cells.length > 0 ? t('viewers.model.reconciled') : ''} <span className="mv__dim">{h.a.method}</span>
                </p>
              </div>
            )}
            {h.error && (
              <p className="mv__err" role="alert">
                {h.error}
              </p>
            )}
          </div>
        ))}
        {busy && (
          <div className="mv__skel">
            <Skeleton width="80%" height={12} />
          </div>
        )}
        <div ref={end} />
      </div>
      {dirty && <p className="mv__note">{t('viewers.model.askDirty')}</p>}
      <form className="mv__ask-form" onSubmit={submit}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('viewers.model.askPlaceholder')} aria-label={t('viewers.model.askPlaceholder')} data-testid="ask-input" dir="auto" maxLength={600} />
        <Button type="submit" variant="primary" size="sm" disabled={!q.trim() || busy} data-testid="ask-submit">
          {t('viewers.model.ask')}
        </Button>
      </form>
    </div>
  );
}

/* ------------------------------------------------------------------ tab audit */

export function AuditPanel({ audit, loading, error, onJump, onRetry }: { audit: Audit | null; loading: boolean; error: string | null; onJump: (ref: string) => void; onRetry: () => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState<string | null>(null);
  if (loading && !audit) return <div className="mv__skel mv__pad"><Skeleton height={14} /><Skeleton width="60%" height={14} /></div>;
  if (error)
    return (
      <div className="mv__pad">
        <p className="mv__err" role="alert">
          {error}
        </p>
        <Button size="sm" onClick={onRetry}>
          {t('viewers.retry')}
        </Button>
      </div>
    );
  if (!audit) return null;
  const tone = (s: string) => (s === 'fail' ? 'negative' : s === 'warn' ? 'warning' : 'positive');
  return (
    <div className="mv__audit" data-testid="audit-panel">
      <div className="mv__tiles">
        <div>
          <b className="acr-num">{audit.totals.links}</b>
          <span>{t('viewers.model.auditLinks')}</span>
        </div>
        <div className={audit.totals.hardcodes ? 'is-warn' : ''}>
          <b className="acr-num">{audit.totals.hardcodes}</b>
          <span>{t('viewers.model.auditHard')}</span>
        </div>
        <div className={audit.totals.errors ? 'is-fail' : ''}>
          <b className="acr-num">{audit.totals.errors}</b>
          <span>{t('viewers.model.auditErrors')}</span>
        </div>
      </div>
      <ul className="mv__audit-list">
        {audit.sheets.map((s) => {
          const isOpen = open === s.sheet;
          const items = [...s.errors.map((i) => ({ ...i, kind: 'error' })), ...s.hardcodes.map((i) => ({ ...i, kind: 'hard' })), ...s.links.slice(0, 40).map((i) => ({ ...i, kind: 'link' }))];
          return (
            <li key={s.sheet}>
              <button type="button" className="mv__audit-row" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : s.sheet)}>
                {isOpen ? <IconChevronDown size={13} /> : <IconChevronRight size={13} />}
                <span className="mv__audit-name">{s.sheet}</span>
                <span className="mv__audit-n acr-num">
                  {s.n_links} / {s.n_hardcodes} / {s.n_errors}
                </span>
                <Badge tone={tone(s.status)}>{t(`viewers.model.audit.${s.status}`)}</Badge>
              </button>
              {isOpen && (
                <ul className="mv__audit-items">
                  {items.length === 0 && <li className="mv__dim">{t('viewers.model.auditNone')}</li>}
                  {items.map((i) => (
                    <li key={`${i.kind}${i.ref}`}>
                      <button type="button" className={`mv__ref is-${i.kind}`} onClick={() => onJump(i.ref)}>
                        <span className="mv__kind">{t(`viewers.model.auditKind.${i.kind}`)}</span>
                        <span className="mv__ref-label" dir="auto">
                          {i.label || i.ref}
                        </span>
                        <span className="mv__ref-id acr-mono" dir="ltr">
                          {i.ref.replace(`${s.sheet}!`, '')}
                          {i.to?.[0] ? ` ← ${i.to[0]}` : ''}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
