import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Button, Dialog, Input, useToast } from '../ds';
import { api } from '../api/client';
import type { Deal, DealInput } from '../api/types';
import { useT } from '../i18n';
import { errorToast } from '../app/lib';

export const SAMPLE_DEAL: DealInput = { name: 'Sample: Apple Inc. trading comps', target: 'Apple Inc.', sector: 'Technology' };

export function NewDealDialog({ open, onClose, onCreated, initial }: { open: boolean; onClose: () => void; onCreated: (d: Deal) => void; initial?: DealInput }) {
  const t = useT();
  const toast = useToast();
  const [name, setName] = useState('');
  const [target, setTarget] = useState('');
  const [sector, setSector] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    if (open) {
      setName(initial?.name ?? '');
      setTarget(initial?.target ?? '');
      setSector(initial?.sector ?? '');
      setErr('');
      setBusy(false);
    }
  }, [open, initial]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setErr(t('deal.new.nameRequired'));
      return;
    }
    setBusy(true);
    try {
      const r = await api.post<{ deal: Deal } | Deal>('/deals', { name: name.trim(), target: target.trim() || undefined, sector: sector.trim() || undefined });
      const deal = 'deal' in r ? r.deal : r;
      onClose();
      onCreated(deal);
    } catch (x) {
      setBusy(false);
      toast.push(errorToast(x, t('deal.new.failed')));
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t('deal.new.title')}
      description={t('deal.new.desc')}
      closeLabel={t('common.close')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" type="submit" form="new-deal-form" loading={busy} data-testid="new-deal-submit">
            {t('deal.new.create')}
          </Button>
        </>
      }
    >
      <form id="new-deal-form" className="acr-stack" onSubmit={submit} noValidate>
        <Input label={t('deal.name')} value={name} onChange={(e) => setName(e.target.value)} error={err} data-autofocus data-testid="new-deal-name" required />
        <Input label={t('deal.target')} value={target} onChange={(e) => setTarget(e.target.value)} hint={t('deal.new.targetHint')} />
        <Input label={t('deal.sector')} value={sector} onChange={(e) => setSector(e.target.value)} />
      </form>
    </Dialog>
  );
}
