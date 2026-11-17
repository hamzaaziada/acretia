import { useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client';
import { Button, Checkbox, Dialog, IconPlus, IconX, Input, Select, Textarea, cx, useToast } from '../../ds';
import { useT } from '../../i18n';
import { errText } from './common';
import { COL_TYPES } from './types';
import type { ColType, DocsPayload, GridPayload, SplitColumn } from './types';

interface Props {
  dealId: string;
  open: boolean;
  onClose: () => void;
  onCreated: (gridId: string) => void;
}

/** Two steps (parity item 2): 1. choose documents, singly or by data-room folder; 2. write the question, split it into columns, edit them. */
export function Wizard({ dealId, open, onClose, onCreated }: Props) {
  const t = useT();
  const toast = useToast();
  const [step, setStep] = useState<1 | 2>(1);
  const [docs, setDocs] = useState<DocsPayload | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [q, setQ] = useState('');
  const [name, setName] = useState('');
  const [question, setQuestion] = useState('');
  const [cols, setCols] = useState<SplitColumn[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setStep(1);
    setQuestion('');
    setCols([]);
    setName('');
    api
      .get<DocsPayload>(`/deals/${dealId}/grid/documents`)
      .then((d) => {
        setDocs(d);
        setPicked(new Set(d.documents.map((x) => x.id)));
      })
      .catch((e) => toast.push({ kind: 'error', ...errText(e) }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, dealId]);

  const byFolder = useMemo(() => {
    const m = new Map<string, DocsPayload['documents']>();
    for (const d of docs?.documents ?? []) {
      if (q && !d.full_name.toLowerCase().includes(q.toLowerCase())) continue;
      const k = d.folder || '';
      m.set(k, [...(m.get(k) ?? []), d]);
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [docs, q]);

  function toggle(ids: string[], on: boolean) {
    setPicked((s) => {
      const n = new Set(s);
      for (const i of ids) (on ? n.add(i) : n.delete(i));
      return n;
    });
  }

  async function split() {
    if (!question.trim()) return;
    try {
      const r = await api.post<{ columns: SplitColumn[] }>(`/deals/${dealId}/grids/split`, { question });
      setCols(r.columns);
    } catch (e) {
      toast.push({ kind: 'error', ...errText(e) });
    }
  }

  async function create() {
    setBusy(true);
    try {
      const g = await api.post<GridPayload>(`/deals/${dealId}/grids`, { name: name.trim() || undefined, doc_ids: [...picked], columns: cols });
      onCreated(g.grid!.id);
      onClose();
    } catch (e) {
      toast.push({ kind: 'error', ...errText(e) });
    } finally {
      setBusy(false);
    }
  }

  const patch = (i: number, p: Partial<SplitColumn>) => setCols((c) => c.map((x, k) => (k === i ? { ...x, ...p } : x)));

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title={t('viewers2.wizard.title')}
      closeLabel={t('viewers2.common.close')}
      footer={
        <>
          <ol className="vw-steps" aria-label={t('viewers2.wizard.steps')}>
            <li className={cx(step === 1 && 'is-on')} aria-current={step === 1 ? 'step' : undefined}>
              1 · {t('viewers2.wizard.step1')}
            </li>
            <li className={cx(step === 2 && 'is-on')} aria-current={step === 2 ? 'step' : undefined}>
              2 · {t('viewers2.wizard.step2')}
            </li>
          </ol>
          <span className="vw-spacer" />
          {step === 1 ? (
            <Button variant="primary" disabled={picked.size === 0} onClick={() => setStep(2)}>
              {t('viewers2.wizard.next', { count: picked.size })}
            </Button>
          ) : (
            <>
              <Button variant="ghost" onClick={() => setStep(1)}>
                {t('viewers2.wizard.back')}
              </Button>
              <Button variant="primary" loading={busy} disabled={cols.length === 0} onClick={() => void create()}>
                {t('viewers2.wizard.create', { docs: picked.size, cols: cols.length })}
              </Button>
            </>
          )}
        </>
      }
    >
      <div data-testid="grid-wizard">
        {step === 1 ? (
          <div className="vw-wiz">
            <Input label={t('viewers2.wizard.search')} hideLabel value={q} placeholder={t('viewers2.wizard.search')} onChange={(e) => setQ(e.target.value)} />
            <div className="vw-wiz__list" role="group" aria-label={t('viewers2.wizard.step1')}>
              {byFolder.length === 0 && <p className="vw-muted">{t('viewers2.wizard.noDocs')}</p>}
              {byFolder.map(([folder, list]) => {
                const all = list.every((d) => picked.has(d.id));
                const some = list.some((d) => picked.has(d.id));
                return (
                  <div key={folder} className="vw-wiz__folder">
                    <Checkbox
                      label={`${folder || t('viewers2.grid.unfiled')} (${list.length})`}
                      checked={all}
                      ref={(el) => {
                        if (el) el.indeterminate = some && !all;
                      }}
                      onChange={(e) => toggle(list.map((d) => d.id), e.target.checked)}
                    />
                    <div className="vw-wiz__docs">
                      {list.map((d) => (
                        <Checkbox key={d.id} label={d.name} checked={picked.has(d.id)} onChange={(e) => toggle([d.id], e.target.checked)} />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="vw-wiz">
            <Input label={t('viewers2.wizard.name')} value={name} placeholder={t('viewers2.wizard.namePlaceholder')} onChange={(e) => setName(e.target.value)} />
            <Textarea
              label={t('viewers2.wizard.question')}
              hint={t('viewers2.wizard.questionHint')}
              rows={3}
              value={question}
              data-autofocus
              placeholder={t('viewers2.grid.promptPlaceholder')}
              onChange={(e) => setQuestion(e.target.value)}
            />
            <div>
              <Button variant="secondary" disabled={!question.trim()} onClick={() => void split()}>
                {t('viewers2.wizard.split')}
              </Button>
            </div>
            {cols.length > 0 && (
              <ul className="vw-wiz__cols" aria-label={t('viewers2.wizard.columns')}>
                {cols.map((c, i) => (
                  <li key={i} className="vw-wiz__col">
                    <Input label={t('viewers2.grid.columnName')} hideLabel value={c.name} onChange={(e) => patch(i, { name: e.target.value })} />
                    <Input label={t('viewers2.grid.prompt')} hideLabel value={c.prompt} onChange={(e) => patch(i, { prompt: e.target.value })} />
                    <Select
                      label={t('viewers2.grid.typeLabel')}
                      hideLabel
                      value={c.type}
                      onChange={(e) => patch(i, { type: e.target.value as ColType })}
                      options={COL_TYPES.map((x) => ({ value: x, label: t(`viewers2.grid.type.${x}`) }))}
                    />
                    <button type="button" className="vw-iconbtn" aria-label={t('viewers2.wizard.removeColumn', { name: c.name })} onClick={() => setCols((l) => l.filter((_, k) => k !== i))}>
                      <IconX size={14} />
                    </button>
                  </li>
                ))}
                <li>
                  <Button size="sm" variant="ghost" icon={<IconPlus size={13} />} onClick={() => setCols((l) => [...l, { name: `${t('viewers2.wizard.newColumn')} ${l.length + 1}`, prompt: '', type: 'text' }])}>
                    {t('viewers2.wizard.addColumn')}
                  </Button>
                </li>
              </ul>
            )}
          </div>
        )}
      </div>
    </Dialog>
  );
}
