import { useState } from 'react';
import { Button, Checkbox, IconChevronDown, IconChevronUp, IconX, IconButton, Input, useToast } from '../ds';
import { api } from '../api/client';
import type { ApprovalData } from '../api/types';
import { useT } from '../i18n';
import { errorToast } from '../app/lib';

type Done = () => void;

/*
 * Approval contract (SPEC section 5; om/api/jobs.py). The run pauses with an `approval` event {step_id, kind, payload}; the UI answers
 *   POST /jobs/{id}/approve  {step: <step_id>, payload: {...}}
 * kind "sources"     (step_id "source_review"): payload {selected: [source id, ...], skip_next_time: boolean}; ids come from approval.payload.sources[].id
 * kind "ghost_deck"  (step_id "approve_outline"): payload {titles: {<slide id>: <title>}, order: [<slide id> kept, in order]}; ids come from approval.payload.titles[].id
 * kind "assumptions": payload {assumptions: [{key, value}]}
 */

export function ApprovalCard({ jobId, approval, onDone }: { jobId: string; approval: ApprovalData; onDone: Done }) {
  const t = useT();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  async function send(payload: Record<string, unknown>) {
    setBusy(true);
    try {
      await api.post(`/jobs/${jobId}/approve`, { step: approval.step_id, payload });
      onDone();
    } catch (e) {
      toast.push(errorToast(e, t('approval.failed')));
      setBusy(false);
    }
  }

  return (
    <section className="acr-approval" data-testid="approval-card" data-kind={approval.kind} aria-label={t(`approval.${approval.kind}.title`)}>
      <h3 className="acr-approval__title">{t(`approval.${approval.kind}.title`)}</h3>
      <p className="acr-muted acr-approval__lead">{t(`approval.${approval.kind}.lead`)}</p>
      {approval.kind === 'sources' && <SourceReview approval={approval} busy={busy} onApprove={send} />}
      {approval.kind === 'ghost_deck' && <GhostDeck approval={approval} busy={busy} onApprove={send} />}
      {approval.kind === 'assumptions' && <Assumptions approval={approval} busy={busy} onApprove={send} />}
    </section>
  );
}

interface Inner {
  approval: ApprovalData;
  busy: boolean;
  onApprove: (payload: Record<string, unknown>) => void;
}

function SourceReview({ approval, busy, onApprove }: Inner) {
  const t = useT();
  const sources = approval.payload.sources ?? [];
  const [picked, setPicked] = useState<Set<string>>(new Set(sources.filter((x) => x.available !== false).map((x) => x.id)));
  const [skip, setSkip] = useState(false);
  return (
    <>
      <ul className="acr-approval__list" data-testid="source-review-list">
        {sources.map((s) => (
          <li key={s.id} data-testid="source-review-item" data-id={s.id}>
            <Checkbox
              label={s.label}
              hint={[s.kind, s.detail, s.available === false ? t('approval.sources.unavailable') : null].filter(Boolean).join(' · ') || undefined}
              checked={picked.has(s.id)}
              disabled={s.available === false}
              onChange={(e) =>
                setPicked((p) => {
                  const n = new Set(p);
                  if (e.target.checked) n.add(s.id);
                  else n.delete(s.id);
                  return n;
                })
              }
            />
          </li>
        ))}
        {sources.length === 0 && <li className="acr-muted">{t('approval.sources.none')}</li>}
      </ul>
      <div className="acr-approval__foot">
        <Checkbox label={t('approval.sources.skip')} checked={skip} onChange={(e) => setSkip(e.target.checked)} />
        <span className="acr-spacer-flex" />
        <Button variant="primary" loading={busy} data-testid="approval-approve" onClick={() => onApprove({ selected: sources.map((x) => x.id).filter((k) => picked.has(k)), skip_next_time: skip })}>
          {t('approval.approve')}
        </Button>
      </div>
    </>
  );
}

function GhostDeck({ approval, busy, onApprove }: Inner) {
  const t = useT();
  const initial = (approval.payload.titles ?? []).map((x) => (typeof x === 'string' ? { id: '', title: x } : x));
  const [titles, setTitles] = useState<Array<{ k: number; v: string; id: string }>>(initial.map((x, k) => ({ k, v: x.title, id: x.id })));
  function move(i: number, d: -1 | 1) {
    setTitles((l) => {
      const j = i + d;
      if (j < 0 || j >= l.length) return l;
      const c = [...l];
      [c[i], c[j]] = [c[j], c[i]];
      return c;
    });
  }
  return (
    <>
      <ol className="acr-approval__slides">
        {titles.map((row, i) => (
          <li key={row.k} className="acr-approval__slide">
            <span className="acr-approval__n acr-num">{i + 1}</span>
            <Input
              hideLabel
              label={t('approval.ghost_deck.slide', { n: i + 1 })}
              value={row.v}
              data-testid="ghost-title-input"
              fieldClassName="acr-spacer-flex"
              onChange={(e) => setTitles((l) => l.map((x) => (x.k === row.k ? { ...x, v: e.target.value } : x)))}
            />
            <IconButton size="sm" aria-label={t('approval.moveUp')} disabled={i === 0} onClick={() => move(i, -1)}>
              <IconChevronUp size={14} />
            </IconButton>
            <IconButton size="sm" aria-label={t('approval.moveDown')} disabled={i === titles.length - 1} onClick={() => move(i, 1)}>
              <IconChevronDown size={14} />
            </IconButton>
            <IconButton size="sm" aria-label={t('approval.remove')} onClick={() => setTitles((l) => l.filter((x) => x.k !== row.k))}>
              <IconX size={14} />
            </IconButton>
          </li>
        ))}
      </ol>
      <div className="acr-approval__foot">
        <span className="acr-spacer-flex" />
        <Button variant="primary" loading={busy} disabled={titles.every((x) => !x.v.trim())} data-testid="approval-approve" onClick={() => onApprove({ titles: Object.fromEntries(titles.filter((x) => x.id && x.v.trim()).map((x) => [x.id, x.v.trim()])), order: titles.filter((x) => x.id && x.v.trim()).map((x) => x.id) })}>
          {t('approval.approve')}
        </Button>
      </div>
    </>
  );
}

function Assumptions({ approval, busy, onApprove }: Inner) {
  const t = useT();
  const rows = approval.payload.assumptions ?? [];
  const [vals, setVals] = useState<Record<string, string>>(Object.fromEntries(rows.map((r) => [r.key, String(r.value)])));
  return (
    <>
      <div className="acr-approval__assump">
        {rows.map((r) => (
          <Input key={r.key} label={r.label ?? r.key} value={vals[r.key] ?? ''} className="acr-num" onChange={(e) => setVals((v) => ({ ...v, [r.key]: e.target.value }))} />
        ))}
      </div>
      <div className="acr-approval__foot">
        <span className="acr-spacer-flex" />
        <Button variant="primary" loading={busy} data-testid="approval-approve" onClick={() => onApprove({ assumptions: rows.map((r) => ({ key: r.key, value: vals[r.key] ?? String(r.value) })) })}>
          {t('approval.approve')}
        </Button>
      </div>
    </>
  );
}
