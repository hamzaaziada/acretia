import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { cx, IconAlert, IconChevronDown, IconChevronUp, IconClock, IconLink, IconSettings } from '../../ds';
import { useT } from '../../i18n';
import { CellStore, useCell } from './store';
import type { Cell, Column, Row } from './types';

export type Item = { kind: 'group'; id: string; folder: string; count: number } | { kind: 'row'; row: Row };
export interface Sort {
  col: string;
  dir: 'asc' | 'desc';
}
export interface Sel {
  row: string;
  col: string;
}

export const HEAD_H = 40;
export const ROW_H = 46;
export const GROUP_H = 30;
export const DOC_W = 300;
export const COL_W = 264;
const OVERSCAN_ROWS = 8;

const NUMERIC = new Set(['number', 'percent', 'currency']);

/** Binary search: index of the last item whose offset is <= y. */
function indexAt(offs: number[], y: number): number {
  let lo = 0;
  let hi = offs.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (offs[mid] <= y) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

interface CellViewProps {
  store: CellStore;
  row: Row;
  col: Column;
  x: number;
  w: number;
  selected: boolean;
  onSelect: (s: Sel) => void;
  onOpen: (s: Sel) => void;
}

const CellView = memo(function CellView({ store, row, col, x, w, selected, onSelect, onOpen }: CellViewProps) {
  const t = useT();
  const cell = useCell(store, row.id, col.id);
  const state = cell?.state ?? 'queued';
  const notFound = state === 'done' && /^not found/i.test(cell?.value ?? '');
  const tone = state === 'done' && cell?.fmt ? cell.fmt.tone : null;
  const page = cell?.citations?.[0]?.page ?? null;
  return (
    <div
      role="gridcell"
      aria-selected={selected}
      tabIndex={selected ? 0 : -1}
      data-testid="grid-cell"
      data-row={row.id}
      data-col={col.id}
      data-state={state}
      className={cx('vw-cell', `is-${state}`, notFound && 'is-notfound', tone && `tone-${tone}`, NUMERIC.has(col.type) && 'is-num', selected && 'is-selected')}
      style={{ insetInlineStart: x, inlineSize: w }}
      onClick={() => onSelect({ row: row.id, col: col.id })}
      onDoubleClick={() => onOpen({ row: row.id, col: col.id })}
    >
      {state === 'queued' || state === 'running' ? (
        <span className="vw-shimmer" aria-label={t(state === 'running' ? 'viewers2.grid.state.running' : 'viewers2.grid.state.queued')}>
          <span />
          <span />
        </span>
      ) : state === 'skipped' ? (
        <span className="vw-cell__muted" title={cell?.reason ?? ''}>
          <IconClock size={12} />
          <span className="vw-clamp">{t('viewers2.grid.skipped', { reason: cell?.reason ?? '' })}</span>
        </span>
      ) : state === 'failed' ? (
        <span className="vw-cell__err" title={cell?.error ?? ''}>
          <IconAlert size={12} />
          <span className="vw-clamp">{t('viewers2.grid.failed')}</span>
        </span>
      ) : (
        <>
          <span className="vw-clamp">{cell?.value || ' '}</span>
          {page != null && !notFound && (
            <span className="vw-cell__src" aria-label={t('viewers2.grid.sourcePage', { page })}>
              <IconLink size={10} />
              {page}
            </span>
          )}
        </>
      )}
    </div>
  );
});

interface Props {
  store: CellStore;
  columns: Column[];
  items: Item[];
  sel: Sel | null;
  sort: Sort | null;
  canEdit: boolean;
  onSelect: (s: Sel | null) => void;
  onOpen: (s: Sel) => void;
  onSort: (col: string) => void;
  onManage: (col: string) => void;
}

export function GridTable({ store, columns, items, sel, sort, canEdit, onSelect, onOpen, onSort, onManage }: Props) {
  const t = useT();
  const scroller = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ top: 0, left: 0, w: 1200, h: 700 });
  const raf = useRef(0);

  const rowOffs = useMemo(() => {
    const offs: number[] = [];
    let y = 0;
    for (const it of items) {
      offs.push(y);
      y += it.kind === 'group' ? GROUP_H : ROW_H;
    }
    return { offs, total: y };
  }, [items]);
  const colOffs = useMemo(() => {
    const xs: number[] = [];
    let x = DOC_W;
    for (let i = 0; i < columns.length; i += 1) {
      xs.push(x);
      x += COL_W;
    }
    return { xs, total: x };
  }, [columns.length]);

  const readView = useCallback(() => {
    const el = scroller.current;
    if (!el) return;
    setView((v) => {
      const top = el.scrollTop;
      const left = Math.abs(el.scrollLeft);
      const w = el.clientWidth;
      const h = el.clientHeight;
      // only re-render when the visible window moves by more than a row / column
      if (Math.abs(top - v.top) < ROW_H / 2 && Math.abs(left - v.left) < COL_W / 2 && w === v.w && h === v.h) return v;
      return { top, left, w, h };
    });
  }, []);

  useLayoutEffect(() => {
    readView();
    const el = scroller.current;
    if (!el) return;
    const ro = new ResizeObserver(readView);
    ro.observe(el);
    return () => ro.disconnect();
  }, [readView]);
  useEffect(() => () => cancelAnimationFrame(raf.current), []);

  function onScroll() {
    cancelAnimationFrame(raf.current);
    raf.current = requestAnimationFrame(readView);
  }

  const first = items.length ? Math.max(0, indexAt(rowOffs.offs, view.top) - OVERSCAN_ROWS) : 0;
  const last = items.length ? Math.min(items.length - 1, indexAt(rowOffs.offs, view.top + view.h) + OVERSCAN_ROWS) : -1;
  const cFirst = Math.max(0, Math.floor((view.left - DOC_W) / COL_W) - 1);
  const cLast = Math.min(columns.length - 1, Math.ceil((view.left + view.w - DOC_W) / COL_W) + 1);
  const visCols = columns.slice(cFirst, cLast + 1);

  const rowItems = useMemo(() => items.filter((i): i is Extract<Item, { kind: 'row' }> => i.kind === 'row'), [items]);

  function reveal(rowId: string, colId: string) {
    const el = scroller.current;
    if (!el) return;
    const ri = items.findIndex((i) => i.kind === 'row' && i.row.id === rowId);
    const ci = columns.findIndex((c) => c.id === colId);
    if (ri >= 0) {
      const y = rowOffs.offs[ri];
      if (y < el.scrollTop) el.scrollTop = y;
      else if (y + ROW_H > el.scrollTop + el.clientHeight - HEAD_H) el.scrollTop = y + ROW_H - el.clientHeight + HEAD_H;
    }
    if (ci >= 0) {
      const x = colOffs.xs[ci];
      const left = Math.abs(el.scrollLeft);
      const sign = el.scrollLeft < 0 ? -1 : 1;
      if (x - DOC_W < left) el.scrollLeft = sign * (x - DOC_W);
      else if (x + COL_W > left + el.clientWidth) el.scrollLeft = sign * (x + COL_W - el.clientWidth);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (!rowItems.length || !columns.length) return;
    const rtl = document.documentElement.dir === 'rtl';
    const cur = sel ?? { row: rowItems[0].row.id, col: columns[0].id };
    let ri = rowItems.findIndex((r) => r.row.id === cur.row);
    let ci = columns.findIndex((c) => c.id === cur.col);
    if (ri < 0) ri = 0;
    if (ci < 0) ci = 0;
    const page = Math.max(1, Math.floor(view.h / ROW_H) - 1);
    switch (e.key) {
      case 'ArrowDown': ri += 1; break;
      case 'ArrowUp': ri -= 1; break;
      case 'ArrowRight': ci += rtl ? -1 : 1; break;
      case 'ArrowLeft': ci += rtl ? 1 : -1; break;
      case 'PageDown': ri += page; break;
      case 'PageUp': ri -= page; break;
      case 'Home': ci = 0; if (e.ctrlKey || e.metaKey) ri = 0; break;
      case 'End': ci = columns.length - 1; if (e.ctrlKey || e.metaKey) ri = rowItems.length - 1; break;
      case 'Enter': case ' ':
        if (sel) { e.preventDefault(); onOpen(sel); }
        return;
      case 'Escape': onSelect(null); return;
      default: return;
    }
    e.preventDefault();
    ri = Math.max(0, Math.min(rowItems.length - 1, ri));
    ci = Math.max(0, Math.min(columns.length - 1, ci));
    const next = { row: rowItems[ri].row.id, col: columns[ci].id };
    onSelect(next);
    reveal(next.row, next.col);
    requestAnimationFrame(() => scroller.current?.querySelector<HTMLElement>('[role=gridcell][tabindex="0"]')?.focus({ preventScroll: true }));
  }

  return (
    <div
      ref={scroller}
      className="vw-grid"
      data-testid="grid"
      role="grid"
      aria-label={t('viewers2.grid.title')}
      aria-rowcount={rowItems.length + 1}
      aria-colcount={columns.length + 1}
      tabIndex={sel ? -1 : 0}
      onScroll={onScroll}
      onKeyDown={onKeyDown}
    >
      <div className="vw-grid__canvas" style={{ inlineSize: colOffs.total, blockSize: HEAD_H + rowOffs.total }}>
        <div className="vw-grid__head" role="row" style={{ inlineSize: colOffs.total, blockSize: HEAD_H }}>
          <div className="vw-hcell vw-hcell--doc" role="columnheader" style={{ inlineSize: DOC_W }}>
            {t('viewers2.grid.document')}
            <span className="vw-hcell__count acr-num">{rowItems.length}</span>
          </div>
          {visCols.map((c, i) => {
            const idx = cFirst + i;
            const active = sort?.col === c.id;
            return (
              <div
                key={c.id}
                className="vw-hcell"
                role="columnheader"
                aria-sort={active ? (sort!.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                style={{ insetInlineStart: colOffs.xs[idx], inlineSize: COL_W }}
              >
                <button type="button" className="vw-hcell__main" onClick={() => onSort(c.id)} title={c.prompt}>
                  <span className="vw-hcell__name">{c.name}</span>
                  <span className="vw-hcell__type">{t(`viewers2.grid.type.${c.type}`)}</span>
                  {active && (sort!.dir === 'asc' ? <IconChevronUp size={12} /> : <IconChevronDown size={12} />)}
                </button>
                {(c.depends_on.cols.length > 0 || c.depends_on.inputs.length > 0 || c.run_condition) && (
                  <span className="vw-hcell__dep" title={t('viewers2.grid.hasDeps')}>
                    <IconLink size={12} />
                  </span>
                )}
                {canEdit && (
                  <button type="button" className="vw-hcell__cfg" aria-label={t('viewers2.grid.manageColumn', { name: c.name })} onClick={() => onManage(c.id)}>
                    <IconSettings size={13} />
                  </button>
                )}
              </div>
            );
          })}
        </div>
        {items.slice(first, last + 1).map((it, k) => {
          const i = first + k;
          const top = HEAD_H + rowOffs.offs[i];
          if (it.kind === 'group') {
            return (
              <div key={it.id} className="vw-group" role="row" style={{ insetBlockStart: top, blockSize: GROUP_H, inlineSize: colOffs.total }}>
                <span className="vw-group__label">
                  <span className="vw-group__name">{it.folder || t('viewers2.grid.unfiled')}</span>
                  <span className="vw-group__count acr-num">{it.count}</span>
                </span>
              </div>
            );
          }
          return (
            <div key={it.row.id} className="vw-row" role="row" data-id={it.row.id} style={{ insetBlockStart: top, blockSize: ROW_H, inlineSize: colOffs.total }}>
              <div className="vw-docell" role="rowheader" title={it.row.name}>
                <span className="vw-docell__name vw-clamp">{it.row.name}</span>
              </div>
              {visCols.map((c, ci) => (
                <CellView
                  key={c.id}
                  store={store}
                  row={it.row}
                  col={c}
                  x={colOffs.xs[cFirst + ci]}
                  w={COL_W}
                  selected={sel?.row === it.row.id && sel?.col === c.id}
                  onSelect={onSelect}
                  onOpen={onOpen}
                />
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export type { Cell };
