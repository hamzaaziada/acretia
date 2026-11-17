import { useEffect, useRef, useState } from 'react';
import { api } from '../../api/client';
import { Button, IconClock, IconDollar, IconPlus, Select, Textarea, Input, useToast } from '../../ds';
import { useI18n } from '../../i18n';
import { errText, useDebounced } from './common';
import { COL_TYPES } from './types';
import type { ColType, Column, Estimate, ModelInfo } from './types';

interface Props {
  gridId: string;
  models: ModelInfo[];
  columns: Column[];
  onAdded: () => void;
}

/** "+ Column" popover: a plain-language prompt, a type, a live cost and time estimate, then the cells stream in (parity item 1). */
export function AddColumn({ gridId, models, columns, onAdded }: Props) {
  const { t, fmt } = useI18n();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [name, setName] = useState('');
  const [type, setType] = useState<ColType>('text');
  const [model, setModel] = useState('extractive');
  const [est, setEst] = useState<Estimate | null>(null);
  const [busy, setBusy] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const dPrompt = useDebounced(prompt, 250);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  useEffect(() => {
    if (!open || !dPrompt.trim()) {
      setEst(null);
      return;
    }
    const ctl = new AbortController();
    api
      .get<Estimate>(`/grids/${gridId}/estimate`, { query: { prompt: dPrompt, type, model }, signal: ctl.signal })
      .then(setEst)
      .catch(() => setEst(null));
    return () => ctl.abort();
  }, [open, dPrompt, type, model, gridId]);

  async function submit() {
    if (!prompt.trim() || busy) return;
    setBusy(true);
    try {
      await api.post(`/grids/${gridId}/columns`, { prompt: prompt.trim(), name: name.trim() || undefined, type, model });
      setPrompt('');
      setName('');
      setOpen(false);
      onAdded();
    } catch (e) {
      const m = errText(e);
      toast.push({ kind: 'error', title: m.title, hint: m.hint });
    } finally {
      setBusy(false);
    }
  }

  const refs = Array.from(prompt.matchAll(/\{\{\s*([^{}]+?)\s*\}\}/g)).map((m) => m[1]);
  return (
    <div className="vw-pop" ref={root}>
      <Button size="md" variant="primary" icon={<IconPlus size={14} />} data-testid="grid-add-column" aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen((o) => !o)}>
        {t('viewers2.grid.addColumn')}
      </Button>
      {open && (
        <div className="vw-pop__panel" role="dialog" aria-label={t('viewers2.grid.addColumn')}>
          <Textarea
            label={t('viewers2.grid.prompt')}
            hint={t('viewers2.grid.promptHint')}
            data-testid="column-prompt"
            data-autofocus
            value={prompt}
            rows={3}
            placeholder={t('viewers2.grid.promptPlaceholder')}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') void submit();
            }}
          />
          {refs.length > 0 && (
            <div className="vw-refs" aria-label={t('viewers2.grid.refs')}>
              {refs.map((r) => (
                <span key={r} className={columns.some((c) => c.name.toLowerCase() === r.toLowerCase()) ? 'vw-ref is-col' : 'vw-ref is-input'}>
                  {r}
                </span>
              ))}
            </div>
          )}
          <div className="vw-pop__row">
            <Input label={t('viewers2.grid.columnName')} value={name} placeholder={t('viewers2.grid.autoName')} onChange={(e) => setName(e.target.value)} />
            <Select
              label={t('viewers2.grid.typeLabel')}
              value={type}
              onChange={(e) => setType(e.target.value as ColType)}
              options={COL_TYPES.map((c) => ({ value: c, label: t(`viewers2.grid.type.${c}`) }))}
            />
          </div>
          <Select
            label={t('viewers2.grid.model')}
            value={model}
            onChange={(e) => setModel(e.target.value)}
            options={models.map((m) => ({ value: m.id, label: m.available ? m.label : `${m.label} (${t('viewers2.grid.unavailable')})` }))}
          />
          <div className="vw-estimate" data-testid="grid-estimate" aria-live="polite">
            {est ? (
              <>
                <span className="vw-estimate__item">
                  <IconClock size={13} />
                  {t('viewers2.grid.estTime', { cells: est.cells, seconds: fmt.number(est.est_seconds, { maximumFractionDigits: 1 }) })}
                </span>
                <span className="vw-estimate__item">
                  <IconDollar size={13} />
                  {est.est_cost_usd === 0 ? t('viewers2.grid.estFree') : fmt.currency(est.est_cost_usd, 'USD', 3)}
                </span>
              </>
            ) : (
              <span className="vw-muted">{t('viewers2.grid.estEmpty')}</span>
            )}
          </div>
          <div className="vw-pop__foot">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t('viewers2.common.cancel')}
            </Button>
            <Button variant="primary" data-testid="column-submit" loading={busy} disabled={!prompt.trim()} onClick={() => void submit()}>
              {t('viewers2.grid.runColumn')}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
