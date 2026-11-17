import { useEffect, useRef, useState } from 'react';
import type { DragEvent, KeyboardEvent } from 'react';
import { api } from '../../api/client';
import { Button, Checkbox, Drawer, IconChevronDown, IconChevronUp, IconPlay, IconPlus, IconX, Input, Select, Textarea, cx, useToast } from '../../ds';
import { useT } from '../../i18n';
import { errText } from './common';
import { COL_TYPES, NO_VALUE_OPS, OPS, TONES } from './types';
import type { ColType, Column, FormatRule, ModelInfo, Op, RuleNode, RunCondition, Tone } from './types';

interface Props {
  open: boolean;
  gridId: string;
  columns: Column[];
  models: ModelInfo[];
  focusCol: string | null;
  onClose: () => void;
  onChanged: () => void;
}

const leaf = (): RuleNode => ({ op: 'gt', value: '' });

/** One node of an AND/OR rule tree: a group (AND / OR over children) or a single comparison (parity item 7). */
function NodeEditor({ node, onChange, onRemove, columns, depth }: { node: RuleNode; onChange: (n: RuleNode) => void; onRemove?: () => void; columns: Column[]; depth: number }) {
  const t = useT();
  if (node.op === 'and' || node.op === 'or') {
    const g = node;
    const setChild = (i: number, n: RuleNode) => onChange({ ...g, children: g.children.map((c, k) => (k === i ? n : c)) });
    return (
      <div className={cx('vw-group-node', depth > 0 && 'is-nested')}>
        <div className="vw-group-node__head">
          <Select
            label={t('viewers2.rules.match')}
            hideLabel
            value={g.op}
            onChange={(e) => onChange({ ...g, op: e.target.value as 'and' | 'or' })}
            options={[
              { value: 'and', label: t('viewers2.rules.and') },
              { value: 'or', label: t('viewers2.rules.or') },
            ]}
          />
          <span className="vw-muted">{t('viewers2.rules.groupHint')}</span>
          {onRemove && (
            <button type="button" className="vw-iconbtn" aria-label={t('viewers2.rules.removeGroup')} onClick={onRemove}>
              <IconX size={13} />
            </button>
          )}
        </div>
        {g.children.map((c, i) => (
          <NodeEditor key={i} node={c} depth={depth + 1} columns={columns} onChange={(n) => setChild(i, n)} onRemove={() => onChange({ ...g, children: g.children.filter((_, k) => k !== i) })} />
        ))}
        <div className="vw-group-node__add">
          <Button size="sm" variant="ghost" icon={<IconPlus size={12} />} onClick={() => onChange({ ...g, children: [...g.children, leaf()] })}>
            {t('viewers2.rules.addCondition')}
          </Button>
          {depth < 2 && (
            <Button size="sm" variant="ghost" icon={<IconPlus size={12} />} onClick={() => onChange({ ...g, children: [...g.children, { op: g.op === 'and' ? 'or' : 'and', children: [leaf()] }] })}>
              {t('viewers2.rules.addGroup')}
            </Button>
          )}
        </div>
      </div>
    );
  }
  const l = node as Extract<RuleNode, { op: Op }>;
  return (
    <div className="vw-leaf">
      <Select
        label={t('viewers2.rules.column')}
        hideLabel
        value={l.col ?? ''}
        onChange={(e) => onChange({ ...l, col: e.target.value || undefined })}
        options={[{ value: '', label: t('viewers2.rules.thisColumn') }, ...columns.map((c) => ({ value: c.id, label: c.name }))]}
      />
      <Select label={t('viewers2.rules.operator')} hideLabel value={l.op} onChange={(e) => onChange({ ...l, op: e.target.value as Op })} options={OPS.map((o) => ({ value: o, label: t(`viewers2.op.${o}`) }))} />
      {!NO_VALUE_OPS.includes(l.op) && <Input label={t('viewers2.rules.value')} hideLabel value={String(l.value ?? '')} onChange={(e) => onChange({ ...l, value: e.target.value })} />}
      {onRemove && (
        <button type="button" className="vw-iconbtn" aria-label={t('viewers2.rules.removeCondition')} onClick={onRemove}>
          <IconX size={13} />
        </button>
      )}
    </div>
  );
}

function ColumnEditor({ col, columns, models, gridId, onChanged, defaultOpen }: { col: Column; columns: Column[]; models: ModelInfo[]; gridId: string; onChanged: () => void; defaultOpen: boolean }) {
  const t = useT();
  const toast = useToast();
  const [name, setName] = useState(col.name);
  const [prompt, setPrompt] = useState(col.prompt);
  const [type, setType] = useState<ColType>(col.type);
  const [model, setModel] = useState(col.model);
  const [cond, setCond] = useState<RunCondition | null>(col.run_condition);
  const [rules, setRules] = useState<FormatRule[]>(col.format_rules);
  const [busy, setBusy] = useState(false);
  const others = columns.filter((c) => c.id !== col.id);

  useEffect(() => {
    setName(col.name);
    setPrompt(col.prompt);
    setType(col.type);
    setModel(col.model);
    setCond(col.run_condition);
    setRules(col.format_rules);
  }, [col]);

  async function save() {
    setBusy(true);
    try {
      const r = await api.patch<{ queued: number }>(`/grids/${gridId}/columns/${col.id}`, { name, prompt, type, model, run_condition: cond, format_rules: rules });
      toast.push({ kind: 'success', title: r.queued ? t('viewers2.manager.savedRerun', { count: r.queued }) : t('viewers2.manager.saved') });
      onChanged();
    } catch (e) {
      toast.push({ kind: 'error', ...errText(e) });
    } finally {
      setBusy(false);
    }
  }
  async function remove() {
    if (!window.confirm(t('viewers2.manager.confirmDelete', { name: col.name }))) return;
    try {
      await api.del(`/grids/${gridId}/columns/${col.id}`);
      onChanged();
    } catch (e) {
      toast.push({ kind: 'error', ...errText(e) });
    }
  }

  return (
    <details className="vw-coled" open={defaultOpen}>
      <summary className="vw-coled__sum">
        <span className="vw-coled__name">{col.name}</span>
        <span className="vw-muted">{t(`viewers2.grid.type.${col.type}`)}</span>
      </summary>
      <div className="vw-coled__body">
        <Input label={t('viewers2.grid.columnName')} value={name} onChange={(e) => setName(e.target.value)} />
        <Textarea label={t('viewers2.grid.prompt')} hint={t('viewers2.grid.promptHint')} rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
        <div className="vw-pop__row">
          <Select label={t('viewers2.grid.typeLabel')} value={type} onChange={(e) => setType(e.target.value as ColType)} options={COL_TYPES.map((c) => ({ value: c, label: t(`viewers2.grid.type.${c}`) }))} />
          <Select
            label={t('viewers2.grid.model')}
            value={model}
            onChange={(e) => setModel(e.target.value)}
            options={models.map((m) => ({ value: m.id, label: m.available ? m.label : `${m.label} (${t('viewers2.grid.unavailable')})` }))}
          />
        </div>

        <fieldset className="vw-fieldset">
          <legend>{t('viewers2.manager.runCondition')}</legend>
          {cond ? (
            <div className="vw-leaf">
              <Select label={t('viewers2.rules.column')} hideLabel value={cond.col} onChange={(e) => setCond({ ...cond, col: e.target.value })} options={others.map((c) => ({ value: c.id, label: c.name }))} />
              <Select label={t('viewers2.rules.operator')} hideLabel value={cond.op} onChange={(e) => setCond({ ...cond, op: e.target.value as Op })} options={OPS.map((o) => ({ value: o, label: t(`viewers2.op.${o}`) }))} />
              {!NO_VALUE_OPS.includes(cond.op) && <Input label={t('viewers2.rules.value')} hideLabel value={cond.value ?? ''} onChange={(e) => setCond({ ...cond, value: e.target.value })} />}
              <button type="button" className="vw-iconbtn" aria-label={t('viewers2.manager.clearCondition')} onClick={() => setCond(null)}>
                <IconX size={13} />
              </button>
            </div>
          ) : (
            <>
              <p className="vw-muted">{t('viewers2.manager.runConditionHint')}</p>
              <Button size="sm" variant="secondary" disabled={others.length === 0} icon={<IconPlus size={12} />} onClick={() => setCond({ col: others[0].id, op: 'not_empty' })}>
                {t('viewers2.manager.addCondition')}
              </Button>
            </>
          )}
        </fieldset>

        <fieldset className="vw-fieldset">
          <legend>{t('viewers2.manager.formatting')}</legend>
          {rules.map((r, i) => (
            <div key={i} className="vw-rule">
              <div className="vw-rule__head">
                <span className={cx('vw-tone', `tone-${r.tone}`)} aria-hidden="true" />
                <Select
                  label={t('viewers2.rules.tone')}
                  hideLabel
                  value={r.tone}
                  onChange={(e) => setRules((l) => l.map((x, k) => (k === i ? { ...x, tone: e.target.value as Tone } : x)))}
                  options={TONES.map((x) => ({ value: x, label: t(`viewers2.tone.${x}`) }))}
                />
                <span className="vw-muted">{t('viewers2.rules.when')}</span>
                <button type="button" className="vw-iconbtn" aria-label={t('viewers2.rules.removeRule')} onClick={() => setRules((l) => l.filter((_, k) => k !== i))}>
                  <IconX size={13} />
                </button>
              </div>
              <NodeEditor node={r.when} depth={0} columns={columns} onChange={(n) => setRules((l) => l.map((x, k) => (k === i ? { ...x, when: n } : x)))} />
            </div>
          ))}
          <Button size="sm" variant="secondary" icon={<IconPlus size={12} />} onClick={() => setRules((l) => [...l, { tone: 'warning', when: { op: 'and', children: [leaf()] } }])}>
            {t('viewers2.manager.addRule')}
          </Button>
        </fieldset>

        <div className="vw-coled__foot">
          <Button variant="danger" size="sm" onClick={() => void remove()}>
            {t('viewers2.manager.delete')}
          </Button>
          <span className="vw-spacer" />
          <Button variant="primary" loading={busy} onClick={() => void save()}>
            {t('viewers2.manager.save')}
          </Button>
        </div>
      </div>
    </details>
  );
}

/** Column Manager drawer: rename, reorder (drag or Alt+Arrow), edit prompt, swap model, run condition, formatting, bulk run (parity item 5). */
export function ColumnManager({ open, gridId, columns, models, focusCol, onClose, onChanged }: Props) {
  const t = useT();
  const toast = useToast();
  const [order, setOrder] = useState<string[]>([]);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const dragId = useRef<string | null>(null);

  useEffect(() => setOrder(columns.map((c) => c.id)), [columns, open]);
  const byId = new Map(columns.map((c) => [c.id, c]));

  async function persist(next: string[]) {
    setOrder(next);
    try {
      await api.patch(`/grids/${gridId}`, { column_order: next });
      onChanged();
    } catch (e) {
      toast.push({ kind: 'error', ...errText(e) });
    }
  }
  function move(id: string, delta: number) {
    const i = order.indexOf(id);
    const j = i + delta;
    if (i < 0 || j < 0 || j >= order.length) return;
    const next = [...order];
    next.splice(j, 0, next.splice(i, 1)[0]);
    void persist(next);
  }
  function onKey(e: KeyboardEvent<HTMLElement>, id: string) {
    if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
      e.preventDefault();
      move(id, e.key === 'ArrowUp' ? -1 : 1);
    }
  }
  function onDrop(e: DragEvent<HTMLElement>, target: string) {
    e.preventDefault();
    const from = dragId.current;
    dragId.current = null;
    if (!from || from === target) return;
    const next = order.filter((x) => x !== from);
    next.splice(next.indexOf(target), 0, from);
    void persist(next);
  }
  async function run(ids: string[] | null) {
    try {
      const r = await api.post<{ queued: number }>(`/grids/${gridId}/run`, ids ? { col_ids: ids } : {});
      toast.push({ kind: 'info', title: t('viewers2.manager.queued', { count: r.queued }) });
      onChanged();
    } catch (e) {
      toast.push({ kind: 'error', ...errText(e) });
    }
  }

  return (
    <Drawer open={open} onClose={onClose} size="lg" title={t('viewers2.manager.title')} closeLabel={t('viewers2.common.close')}>
      <div data-testid="column-manager" className="vw-manager">
        <div className="vw-manager__bar">
          <Button size="sm" variant="secondary" icon={<IconPlay size={12} />} disabled={checked.size === 0} onClick={() => void run([...checked])}>
            {t('viewers2.manager.runSelected', { count: checked.size })}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => void run(null)}>
            {t('viewers2.manager.runAll')}
          </Button>
          <span className="vw-muted vw-spacer">{t('viewers2.manager.reorderHint')}</span>
        </div>
        <ol className="vw-manager__list">
          {order.map((id, i) => {
            const c = byId.get(id);
            if (!c) return null;
            return (
              <li
                key={id}
                className="vw-manager__item"
                draggable
                onDragStart={() => (dragId.current = id)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => onDrop(e, id)}
                onKeyDown={(e) => onKey(e, id)}
                data-id={id}
              >
                <div className="vw-manager__row">
                  <span className="vw-manager__grip" aria-hidden="true">
                    ⋮⋮
                  </span>
                  <Checkbox label={t('viewers2.manager.select', { name: c.name })} className="vw-manager__chk" checked={checked.has(id)} onChange={(e) => setChecked((s) => { const n = new Set(s); if (e.target.checked) n.add(id); else n.delete(id); return n; })} />
                  <span className="vw-spacer" />
                  <button type="button" className="vw-iconbtn" aria-label={t('viewers2.manager.moveUp', { name: c.name })} disabled={i === 0} onClick={() => move(id, -1)}>
                    <IconChevronUp size={14} />
                  </button>
                  <button type="button" className="vw-iconbtn" aria-label={t('viewers2.manager.moveDown', { name: c.name })} disabled={i === order.length - 1} onClick={() => move(id, 1)}>
                    <IconChevronDown size={14} />
                  </button>
                </div>
                <ColumnEditor col={c} columns={columns} models={models} gridId={gridId} onChanged={onChanged} defaultOpen={focusCol === id} />
              </li>
            );
          })}
        </ol>
      </div>
    </Drawer>
  );
}
