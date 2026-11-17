import { useState } from 'react';
import { Button, Checkbox, IconChevronDown, IconChevronUp, IconPlus, IconX, IconButton, Input, useToast } from '../ds';
import { api } from '../api/client';
import type { ApprovalData } from '../api/types';
import { useT } from '../i18n';
import { errorToast } from '../app/lib';

type Done = () => void;

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
      {approval.kind === 'source_review' && <SourceReview approval={approval} busy={busy} onApprove={send} />}
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
  const keyOf = (s: (typeof sources)[number], i: number) => s.id ?? s.name ?? s.doc_name ?? String(i);
  const [picked, setPicked] = useState<Set<string>>(new Set(sources.map(keyOf)));
  const [skip, setSkip] = useState(false);
  return (
    <>
      <ul className="acr-approval__list">
        {sources.map((s, i) => {
          const k = keyOf(s, i);
          return (
            <li key={k}>
              <Checkbox
                label={s.name ?? s.doc_name ?? k}
                hint={[s.kind, s.detail].filter(Boolean).join(' · ') || undefined}
                checked={picked.has(k)}
                onChange={(e) =>
                  setPicked((p) => {
                    const n = new Set(p);
                    if (e.target.checked) n.add(k);
                    else n.delete(k);
                    return n;
                  })
                }
              />
            </li>
          );
        })}
        {sources.length === 0 && <li className="acr-muted">{t('approval.source_review.none')}</li>}
      </ul>
      <div className="acr-approval__foot">
        <Checkbox label={t('approval.source_review.skip')} checked={skip} onChange={(e) => setSkip(e.target.checked)} />
        <span className="acr-spacer-flex" />
        <Button variant="primary" loading={busy} data-testid="approval-approve" onClick={() => onApprove({ selected: sources.map(keyOf).filter((k) => picked.has(k)), skip_next_time: skip })}>
          {t('approval.approve')}
        </Button>
      </div>
    </>
  );
}

function GhostDeck({ approval, busy, onApprove }: Inner) {
  const t = useT();
  const initial = approval.payload.titles ?? (approval.payload.slides ?? []).map((s) => s.title);
  const [titles, setTitles] = useState<Array<{ k: number; v: string }>>(initial.map((v, k) => ({ k, v })));
  const [next, setNext] = useState(initial.length);
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
        <Button
          variant="ghost"
          icon={<IconPlus size={14} />}
          onClick={() => {
            setTitles((l) => [...l, { k: next, v: '' }]);
            setNext((n) => n + 1);
          }}
        >
          {t('approval.addSlide')}
        </Button>
        <span className="acr-spacer-flex" />
        <Button variant="primary" loading={busy} disabled={titles.every((x) => !x.v.trim())} data-testid="approval-approve" onClick={() => onApprove({ titles: titles.map((x) => x.v.trim()).filter(Boolean) })}>
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
