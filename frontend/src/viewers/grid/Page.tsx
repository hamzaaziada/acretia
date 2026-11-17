import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { api } from '../../api/client';
import { openStream } from '../../api/sse';
import { useMe } from '../../api/hooks';
import {
  Badge,
  Button,
  Checkbox,
  EmptyState,
  IconComment,
  IconDownload,
  IconFilter,
  IconAlert,
  IconGrid,
  IconPlus,
  IconSearch,
  IconSettings,
  Input,
  Select,
  SkeletonRows,
  ProgressBar,
  useToast,
} from '../../ds';
import { useI18n } from '../../i18n';
import { AddColumn } from './AddColumn';
import { ColumnManager } from './ColumnManager';
import { Dock } from './Dock';
import type { DockTab } from './Dock';
import { GridTable } from './GridTable';
import type { Item, Sel, Sort } from './GridTable';
import { Wizard } from './Wizard';
import { WorkflowView } from './WorkflowView';
import { CellStore, cellText, compareCells, useStoreVersion } from './store';
import { errText } from './common';
import type { Cell, GridPayload } from './types';
import './grid.css';

interface GridList {
  items: { id: string; name: string; auto_rows: number }[];
}

function InputsBar({ gridId, inputs, canEdit, onChanged }: { gridId: string; inputs: Record<string, string>; canEdit: boolean; onChanged: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const [draft, setDraft] = useState<Record<string, string>>(inputs);
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState('');
  useEffect(() => setDraft(inputs), [inputs]);

  async function commit(name: string, value: string) {
    if (value === (inputs[name] ?? '')) return;
    try {
      const r = await api.put<{ rerun_columns: string[]; queued: number }>(`/grids/${gridId}/inputs/${encodeURIComponent(name)}`, { value });
      if (r.queued) toast.push({ kind: 'info', title: t('viewers2.inputs.rerun', { count: r.rerun_columns.length }) });
      onChanged();
    } catch (e) {
      toast.push({ kind: 'error', ...errText(e) });
    }
  }
  const names = Object.keys(inputs);
  if (names.length === 0 && !canEdit) return null;
  return (
    <div className="vw-inputs" aria-label={t('viewers2.inputs.label')}>
      <span className="vw-inputs__label">{t('viewers2.inputs.label')}</span>
      {names.map((n) => (
        <label key={n} className="vw-input-chip">
          <span className="vw-input-chip__name">{n}</span>
          <input
            className="vw-input-chip__field"
            value={draft[n] ?? ''}
            disabled={!canEdit}
            aria-label={t('viewers2.inputs.value', { name: n })}
            onChange={(e) => setDraft((d) => ({ ...d, [n]: e.target.value }))}
            onBlur={(e) => void commit(n, e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
          />
        </label>
      ))}
      {names.length === 0 && <span className="vw-muted">{t('viewers2.inputs.none')}</span>}
      {canEdit &&
        (adding ? (
          <form
            className="vw-input-chip"
            onSubmit={(e) => {
              e.preventDefault();
              const n = newName.trim();
              if (n) void api.put(`/grids/${gridId}/inputs/${encodeURIComponent(n)}`, { value: '' }).then(onChanged);
              setNewName('');
              setAdding(false);
            }}
          >
            <input className="vw-input-chip__field" autoFocus value={newName} placeholder={t('viewers2.inputs.newName')} aria-label={t('viewers2.inputs.newName')} onChange={(e) => setNewName(e.target.value)} onBlur={() => !newName && setAdding(false)} />
          </form>
        ) : (
          <button type="button" className="vw-linkbtn" onClick={() => setAdding(true)}>
            <IconPlus size={12} /> {t('viewers2.inputs.add')}
          </button>
        ))}
    </div>
  );
}

export default function GridPage() {
  const { id: dealId = '' } = useParams<{ id: string }>();
  const [params, setParams] = useSearchParams();
  const gridParam = params.get('grid');
  const { t, fmt } = useI18n();
  const toast = useToast();
  const { me } = useMe();
  const canEdit = me?.role !== 'viewer';

  const storeRef = useRef<CellStore>();
  if (!storeRef.current) storeRef.current = new CellStore();
  const store = storeRef.current;
  const storeVersion = useStoreVersion(store);

  const [data, setData] = useState<GridPayload | null>(null);
  const [error, setError] = useState<{ title: string; hint?: string } | null>(null);
  const [grids, setGrids] = useState<GridList['items']>([]);
  const [sel, setSel] = useState<Sel | null>(null);
  const [sort, setSort] = useState<Sort | null>(null);
  const [filter, setFilter] = useState('');
  const [dock, setDock] = useState<DockTab | null>(null);
  const [wizard, setWizard] = useState(false);
  const [manager, setManager] = useState<{ col: string | null } | null>(null);
  const [workflow, setWorkflow] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [logo, setLogo] = useState(true);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [streamOn, setStreamOn] = useState(false);

  const load = useCallback(
    async (silent = false) => {
      try {
        const p = gridParam ? await api.get<GridPayload>(`/grids/${gridParam}`) : await api.get<GridPayload>(`/deals/${dealId}/grid`);
        store.replaceAll(p.cells);
        setData(p);
        setError(null);
      } catch (e) {
        if (!silent) setError(errText(e));
      }
    },
    [dealId, gridParam, store],
  );

  useEffect(() => {
    setData(null);
    setSel(null);
    void load();
  }, [load]);

  useEffect(() => {
    api.get<GridList>(`/deals/${dealId}/grids`).then((r) => setGrids(r.items)).catch(() => undefined);
  }, [dealId, data?.grid?.id]);

  // stream cell updates; when the stream goes idle the grid is re-read once so formatting and ordering settle
  const gid = data?.grid?.id;
  const pending = data?.pending ?? 0;
  const seq = data?.seq ?? 0;
  useEffect(() => {
    if (!gid || pending === 0) return;
    setStreamOn(true);
    let polled = 0;
    const close = openStream(`/grids/${gid}/events?after=${seq}`, {
      events: {
        cell: (d) => store.set(d as Cell),
        idle: () => {
          close();
          setStreamOn(false);
          void load(true);
        },
      },
      onState: (s) => {
        if (s === 'closed') setStreamOn(false);
      },
    });
    const tick = window.setInterval(() => {
      const c = store.stateCounts();
      const total = store.values().length;
      setProgress({ done: (c.done ?? 0) + (c.skipped ?? 0) + (c.failed ?? 0), total });
      polled += 1;
      if (polled % 12 === 0 && !streamOn) void load(true); // safety net if the stream is blocked by a proxy
    }, 400);
    return () => {
      close();
      window.clearInterval(tick);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gid, pending, seq, store]);

  const rows = data?.rows ?? [];
  const columns = data?.columns ?? [];

  const items: Item[] = useMemo(() => {
    const q = filter.trim().toLowerCase();
    let list = rows;
    if (q) {
      list = rows.filter((r) => r.name.toLowerCase().includes(q) || columns.some((c) => cellText(store.get(r.id, c.id)).toLowerCase().includes(q)));
    }
    if (sort) {
      const dir = sort.dir === 'asc' ? 1 : -1;
      list = [...list].sort((a, b) => dir * compareCells(store.get(a.id, sort.col), store.get(b.id, sort.col)));
    }
    const grouped = rows.some((r) => r.folder);
    if (!grouped) return list.map((row) => ({ kind: 'row', row }));
    const byFolder = new Map<string, typeof list>();
    for (const r of list) byFolder.set(r.folder, [...(byFolder.get(r.folder) ?? []), r]);
    const out: Item[] = [];
    for (const [folder, rs] of [...byFolder.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
      out.push({ kind: 'group', id: `g:${folder}`, folder, count: rs.length });
      for (const row of rs) out.push({ kind: 'row', row });
    }
    return out;
    // storeVersion: cells bulk-loaded or a stream settled
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, columns, filter, sort, storeVersion, store]);

  const visibleRows = items.filter((i) => i.kind === 'row').length;
  const filtered = filter.trim() !== '' && visibleRows < rows.length;

  function onSort(col: string) {
    setSort((s) => (s?.col !== col ? { col, dir: 'asc' } : s.dir === 'asc' ? { col, dir: 'desc' } : null));
  }

  const selected = useMemo(() => {
    if (!sel) return null;
    const row = rows.find((r) => r.id === sel.row);
    const col = columns.find((c) => c.id === sel.col);
    return row && col ? { row, col } : null;
  }, [sel, rows, columns]);

  function openCell(s: Sel) {
    setSel(s);
    setDock('cell');
  }

  async function rerunCell(rowId: string, colId: string) {
    try {
      await api.post(`/grids/${gid}/run`, { col_ids: [colId], row_ids: [rowId] });
      void load(true);
    } catch (e) {
      toast.push({ kind: 'error', ...errText(e) });
    }
  }

  async function transfer() {
    const ids = items.filter((i): i is Extract<Item, { kind: 'row' }> => i.kind === 'row').map((i) => i.row.id);
    try {
      const g = await api.post<GridPayload>(`/grids/${gid}/transfer`, { row_ids: ids });
      toast.push({ kind: 'success', title: t('viewers2.grid.transferred', { count: ids.length }) });
      setParams({ grid: g.grid!.id });
    } catch (e) {
      toast.push({ kind: 'error', ...errText(e) });
    }
  }

  if (error && !data) {
    return (
      <div className="vw-page">
        <EmptyState title={error.title} body={error.hint} icon={<IconAlert size={28} />} action={{ label: t('viewers2.common.retry'), onClick: () => void load() }} />
      </div>
    );
  }
  if (!data) {
    return (
      <div className="vw-page" aria-busy="true">
        <SkeletonRows rows={10} label={t('viewers2.common.loading')} />
      </div>
    );
  }
  if (!data.grid) {
    return (
      <div className="vw-page">
        <EmptyState title={t('viewers2.grid.noGridTitle')} body={data.hint ?? t('viewers2.grid.noGridBody')} icon={<IconGrid size={28} />} action={{ label: t('viewers2.common.retry'), onClick: () => void load() }} />
      </div>
    );
  }

  const grid = data.grid;
  const exportHref = `/api/v1/grids/${grid.id}/export.xlsx${logo ? '?logo=1' : ''}`;
  return (
    <div className="vw-page vw-gridpage" data-testid="grid-page">
      <header className="vw-toolbar">
        <div className="vw-toolbar__title">
          <h1 className="vw-title">{t('viewers2.grid.title')}</h1>
          {grids.length > 1 ? (
            <Select
              label={t('viewers2.grid.switch')}
              hideLabel
              value={grid.id}
              onChange={(e) => setParams(grids.find((g) => g.id === e.target.value)?.auto_rows ? {} : { grid: e.target.value })}
              options={grids.map((g) => ({ value: g.id, label: g.name }))}
              fieldClassName="vw-switch"
            />
          ) : (
            <span className="vw-muted">{grid.name}</span>
          )}
          <Badge tone="neutral">{t('viewers2.grid.counts', { rows: fmt.integer(rows.length), cols: fmt.integer(columns.length) })}</Badge>
        </div>
        <div className="vw-toolbar__tools">
          <Input
            label={t('viewers2.grid.filter')}
            hideLabel
            value={filter}
            startSlot={<IconSearch size={13} />}
            placeholder={t('viewers2.grid.filter')}
            onChange={(e) => setFilter(e.target.value)}
            fieldClassName="vw-filter"
          />
          {filtered && canEdit && (
            <Button size="md" variant="secondary" icon={<IconFilter size={13} />} onClick={() => void transfer()}>
              {t('viewers2.grid.transfer', { count: visibleRows })}
            </Button>
          )}
          <Button size="md" variant="ghost" icon={<IconGrid size={14} />} onClick={() => setWorkflow(true)}>
            {t('viewers2.grid.workflow')}
          </Button>
          <Button size="md" variant="ghost" icon={<IconComment size={14} />} data-testid="grid-chat-toggle" onClick={() => setDock(dock === 'chat' ? null : 'chat')}>
            {t('viewers2.dock.chat')}
          </Button>
          <Button size="md" variant="ghost" icon={<IconAlert size={14} />} onClick={() => setDock(dock === 'risks' ? null : 'risks')}>
            {t('viewers2.dock.risks')}
          </Button>
          <div className="vw-pop">
            <Button size="md" variant="ghost" icon={<IconDownload size={14} />} data-testid="grid-export" aria-expanded={exportOpen} onClick={() => setExportOpen((o) => !o)}>
              {t('viewers2.grid.export')}
            </Button>
            {exportOpen && (
              <div className="vw-pop__panel vw-pop__panel--sm" role="dialog" aria-label={t('viewers2.grid.export')}>
                <Checkbox label={t('viewers2.grid.exportLogo')} checked={logo} onChange={(e) => setLogo(e.target.checked)} />
                <p className="vw-muted">{t('viewers2.grid.exportHint')}</p>
                <a className="acr-btn acr-btn--primary acr-btn--md" href={exportHref} download onClick={() => setExportOpen(false)}>
                  <IconDownload size={14} />
                  <span className="acr-btn__label">{t('viewers2.grid.exportDownload')}</span>
                </a>
              </div>
            )}
          </div>
          {canEdit && (
            <>
              <Button size="md" variant="ghost" icon={<IconSettings size={14} />} onClick={() => setManager({ col: null })}>
                {t('viewers2.manager.open')}
              </Button>
              <Button size="md" variant="secondary" icon={<IconPlus size={14} />} onClick={() => setWizard(true)}>
                {t('viewers2.grid.newMatrix')}
              </Button>
              <AddColumn gridId={grid.id} models={data.models} columns={columns} onAdded={() => void load(true)} />
            </>
          )}
        </div>
      </header>

      <InputsBar gridId={grid.id} inputs={data.inputs} canEdit={canEdit} onChanged={() => void load(true)} />
      {pending > 0 && (
        <div className="vw-fill" role="status">
          <ProgressBar value={progress.total ? (progress.done / progress.total) * 100 : null} label={t('viewers2.grid.filling')} />
          <span className="vw-muted acr-num">{t('viewers2.grid.fillingCount', { done: progress.done, total: progress.total || pending })}</span>
        </div>
      )}

      <div className={dock ? 'vw-main has-dock' : 'vw-main'}>
        <div className="vw-main__grid">
          {rows.length === 0 ? (
            <EmptyState title={t('viewers2.grid.noRowsTitle')} body={t('viewers2.grid.noRowsBody')} icon={<IconGrid size={28} />} action={{ label: t('viewers2.grid.newMatrix'), onClick: () => setWizard(true) }} />
          ) : columns.length === 0 ? (
            <EmptyState
              title={t('viewers2.grid.noColsTitle')}
              body={t('viewers2.grid.noColsBody', { count: rows.length })}
              icon={<IconGrid size={28} />}
              action={{ label: t('viewers2.grid.newMatrix'), onClick: () => setWizard(true) }}
            />
          ) : (
            <GridTable store={store} columns={columns} items={items} sel={sel} sort={sort} canEdit={canEdit} onSelect={setSel} onOpen={openCell} onSort={onSort} onManage={(c) => setManager({ col: c })} />
          )}
        </div>
        {dock && (
          <Dock
            tab={dock}
            setTab={setDock}
            onClose={() => setDock(null)}
            dealId={dealId}
            gridId={grid.id}
            store={store}
            cell={selected}
            canEdit={canEdit}
            onRerun={(r, c) => void rerunCell(r, c)}
          />
        )}
      </div>

      <Wizard dealId={dealId} open={wizard} onClose={() => setWizard(false)} onCreated={(g) => setParams({ grid: g })} />
      <ColumnManager open={manager !== null} gridId={grid.id} columns={columns} models={data.models} focusCol={manager?.col ?? null} onClose={() => setManager(null)} onChanged={() => void load(true)} />
      <WorkflowView open={workflow} gridId={grid.id} version={columns.length} onClose={() => setWorkflow(false)} />
    </div>
  );
}
