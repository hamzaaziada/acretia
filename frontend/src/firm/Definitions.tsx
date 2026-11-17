import { useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { Badge, Button, Checkbox, Dialog, EmptyState, IconAlert, IconButton, IconPlus, IconX, Input, Panel, SkeletonRows, Textarea, useToast } from '../ds';
import { api } from '../api/client';
import { useResource } from '../api/hooks';
import { errorToast } from '../app/lib';
import { useI18n } from '../i18n';
import { LoadError, ReadOnlyNote, slug, useIsOwner } from './lib/shared';
import type { ApplyResp, DefinitionItem, DefinitionsResp } from './lib/types';
import './lib/firm.css';

interface Draft {
  key: string;
  label: string;
  text: string;
  formula_hint: string;
  isNew?: boolean;
}

const toDraft = (d: DefinitionItem): Draft => ({ key: d.key, label: d.label, text: d.text, formula_hint: d.formula_hint });
const sig = (rows: Draft[]) => JSON.stringify(rows.map(({ key, label, text, formula_hint }) => [key, label, text, formula_hint]));

export default function Definitions() {
  const { t, fmt } = useI18n();
  const toast = useToast();
  const owner = useIsOwner();
  const res = useResource<DefinitionsResp>((signal) => api.get<DefinitionsResp>('/firm/definitions', { signal }), []);
  const [rows, setRows] = useState<Draft[]>([]);
  const [saved, setSaved] = useState('');
  const [busy, setBusy] = useState(false);
  const [applyKey, setApplyKey] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!res.data) return;
    const d = res.data.items.map(toDraft);
    setRows(d);
    setSaved(sig(d));
  }, [res.data]);

  const dirty = sig(rows) !== saved;
  const stale = useMemo(() => new Map((res.data?.items ?? []).map((d) => [d.key, d])), [res.data]);

  if (res.error) return <LoadError error={res.error} retry={res.reload} />;
  if (!res.data) return <SkeletonRows rows={5} label={t('common.loading')} />;

  function patch(i: number, p: Partial<Draft>) {
    setRows((r) => r.map((x, j) => (j === i ? { ...x, ...p } : x)));
  }
  function add() {
    setRows((r) => [...r, { key: '', label: '', text: '', formula_hint: '', isNew: true }]);
  }
  function validate(): boolean {
    const e: Record<string, string> = {};
    const seen = new Set<string>();
    rows.forEach((r, i) => {
      const k = r.key || slug(r.label);
      if (!r.label.trim()) e[`${i}.label`] = t('firm.def.labelRequired');
      else if (!k) e[`${i}.label`] = t('firm.def.keyInvalid');
      else if (seen.has(k)) e[`${i}.label`] = t('firm.def.keyDuplicate');
      seen.add(k);
      if (!r.text.trim()) e[`${i}.text`] = t('firm.def.textRequired');
    });
    setErrors(e);
    return Object.keys(e).length === 0;
  }
  async function save(ev: FormEvent) {
    ev.preventDefault();
    if (!owner || !validate()) return;
    setBusy(true);
    try {
      const items = rows.map((r) => ({ key: r.key || slug(r.label), label: r.label.trim(), text: r.text.trim(), formula_hint: r.formula_hint.trim() }));
      const r = await api.put<DefinitionsResp>('/firm/definitions', { items });
      res.reload();
      const n = r.items.reduce((a, d) => a + d.outdated_deals, 0);
      toast.push({ kind: 'success', title: t('firm.def.saved'), body: n > 0 ? t('firm.def.savedStale', { n }) : undefined });
    } catch (x) {
      toast.push(errorToast(x, t('firm.def.saveFailed')));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="acr-firm">
      <p className="acr-firm__intro">{t('firm.def.intro')}</p>
      <Panel
        title={t('firm.def.title')}
        flush
        actions={
          owner ? (
            <Button size="sm" variant="secondary" icon={<IconPlus size={13} />} onClick={add} data-testid="definition-add">
              {t('firm.def.add')}
            </Button>
          ) : undefined
        }
      >
        {!owner && <ReadOnlyNote>{t('firm.ownerOnly')}</ReadOnlyNote>}
        <form data-testid="definitions-form" onSubmit={save} noValidate>
          {rows.length === 0 && (
            <EmptyState title={t('firm.def.empty.title')} body={t('firm.def.empty.body')} action={{ label: t('firm.def.add'), onClick: add }} />
          )}
          {rows.map((r, i) => {
            const k = r.key || slug(r.label);
            const meta = stale.get(r.key);
            return (
              <section key={r.key || `new-${i}`} className="acr-firm-def" aria-label={r.label || t('firm.def.new')}>
                <div className="acr-firm-def__head">
                  <Input
                    label={t('firm.def.label')}
                    value={r.label}
                    onChange={(e) => patch(i, { label: e.target.value })}
                    disabled={!owner}
                    error={errors[`${i}.label`]}
                    maxLength={80}
                    data-testid={`definition-label-${k || i}`}
                    data-autofocus={r.isNew || undefined}
                  />
                  <span className="acr-firm-def__key" dir="ltr">
                    {k || '—'}
                  </span>
                  {owner && (
                    <IconButton aria-label={t('firm.def.remove', { name: r.label || k })} size="sm" onClick={() => setRows((x) => x.filter((_, j) => j !== i))} data-testid={`definition-remove-${k || i}`}>
                      <IconX size={14} />
                    </IconButton>
                  )}
                </div>
                <Textarea
                  label={t('firm.def.text')}
                  hint={t('firm.def.textHint')}
                  value={r.text}
                  onChange={(e) => patch(i, { text: e.target.value })}
                  disabled={!owner}
                  error={errors[`${i}.text`]}
                  rows={3}
                  maxLength={2000}
                  data-testid={`definition-${k || i}`}
                />
                <Input
                  label={t('firm.def.hint')}
                  value={r.formula_hint}
                  onChange={(e) => patch(i, { formula_hint: e.target.value })}
                  disabled={!owner}
                  maxLength={300}
                  mono
                  data-testid={`definition-hint-${k || i}`}
                />
                {meta && meta.outdated_deals > 0 && (
                  <div className="acr-firm-def__stale" role="status" data-testid={`definition-stale-${r.key}`}>
                    <IconAlert size={14} />
                    <span>{t('firm.def.stale', { n: fmt.integer(meta.outdated_deals), name: meta.label })}</span>
                    {owner && (
                      <Button size="sm" variant="secondary" onClick={() => setApplyKey(r.key)} data-testid={`definition-apply-${r.key}`}>
                        {t('firm.def.apply')}
                      </Button>
                    )}
                  </div>
                )}
                {meta?.updated_at && (
                  <span className="acr-firm__meta">{t('firm.def.updated', { when: fmt.dateTime(meta.updated_at) })}</span>
                )}
              </section>
            );
          })}
          {owner && (
            <div className="acr-firm__footer">
              {dirty && <Badge tone="warning">{t('firm.unsaved')}</Badge>}
              <span className="acr-spacer-flex" />
              <Button variant="ghost" disabled={!dirty || busy} onClick={() => { setRows(res.data!.items.map(toDraft)); setErrors({}); }}>
                {t('firm.revert')}
              </Button>
              <Button variant="primary" type="submit" loading={busy} disabled={!dirty} data-testid="definitions-save">
                {t('common.save')}
              </Button>
            </div>
          )}
        </form>
      </Panel>
      <ApplyDialog
        data={res.data}
        defKey={applyKey}
        onClose={() => setApplyKey(null)}
        onDone={() => {
          setApplyKey(null);
          res.reload();
        }}
      />
    </div>
  );
}

function ApplyDialog({ data, defKey, onClose, onDone }: { data: DefinitionsResp; defKey: string | null; onClose: () => void; onDone: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const def = data.items.find((d) => d.key === defKey);
  const names = new Map(data.deals.map((d) => [d.deal_id, d.name]));
  const ids = def?.outdated_deal_ids ?? [];
  const [pick, setPick] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  useEffect(() => setPick(new Set(ids)), [defKey]); // eslint-disable-line react-hooks/exhaustive-deps

  async function apply() {
    if (!def) return;
    setBusy(true);
    try {
      const r = await api.post<ApplyResp>('/firm/definitions/apply', { deal_ids: [...pick], keys: [def.key] });
      toast.push({ kind: 'success', title: t('firm.def.applied', { n: r.applied.length }) });
      onDone();
    } catch (e) {
      toast.push(errorToast(e, t('firm.def.applyFailed')));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      open={!!def}
      onClose={onClose}
      title={t('firm.def.applyTitle', { name: def?.label ?? '' })}
      description={t('firm.def.applyBody')}
      closeLabel={t('common.close')}
      testId="definition-apply-dialog"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" loading={busy} disabled={pick.size === 0} onClick={apply} data-testid="definition-apply-confirm">
            {t('firm.def.applyN', { n: pick.size })}
          </Button>
        </>
      }
    >
      <div className="acr-stack">
        <div className="acr-firm-deals" role="group" aria-label={t('firm.def.dealsGroup')}>
          {ids.map((id) => (
            <Checkbox
              key={id}
              label={names.get(id) ?? id}
              checked={pick.has(id)}
              onChange={(e) =>
                setPick((p) => {
                  const n = new Set(p);
                  if (e.target.checked) n.add(id);
                  else n.delete(id);
                  return n;
                })
              }
            />
          ))}
        </div>
        <p className="acr-firm__meta">{t('firm.def.overridesKept')}</p>
      </div>
    </Dialog>
  );
}
