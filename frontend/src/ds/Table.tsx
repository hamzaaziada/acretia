import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';
import { cx } from './util';
import { IconChevronDown, IconChevronUp } from './icons';

export interface Column<T> {
  key: string;
  header: string;
  render?: (row: T) => ReactNode;
  /** Right-aligned (logical end) with tabular figures. */
  numeric?: boolean;
  mono?: boolean;
  sortValue?: (row: T) => string | number | null | undefined;
  width?: string;
}

export interface TableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  caption: string;
  onRowActivate?: (row: T) => void;
  empty?: ReactNode;
  /** Pixel height of the scroll area; required behaviour for virtualised tables. */
  maxHeight?: number;
  initialSort?: { key: string; dir: 'asc' | 'desc' };
  className?: string;
  /** Rows above which windowing kicks in. */
  virtualizeAbove?: number;
  /** Extra attributes per row (data-testid, data-id, ...). */
  rowProps?: (row: T) => Record<string, string>;
  testId?: string;
}

const ROW_H = 28;
const OVERSCAN = 8;

function cmp(a: unknown, b: unknown): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true });
}

export function Table<T>({
  columns,
  rows,
  rowKey,
  caption,
  onRowActivate,
  empty,
  maxHeight = 560,
  initialSort,
  className,
  virtualizeAbove = 200,
  rowProps,
  testId,
}: TableProps<T>) {
  const uid = useId();
  const [sort, setSort] = useState(initialSort ?? null);
  const [active, setActive] = useState(0);
  const [scrollTop, setScrollTop] = useState(0);
  const scroller = useRef<HTMLDivElement>(null);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col?.sortValue) return rows;
    const get = col.sortValue;
    const out = [...rows].sort((a, b) => cmp(get(a), get(b)));
    return sort.dir === 'desc' ? out.reverse() : out;
  }, [rows, sort, columns]);

  const virtual = sorted.length > virtualizeAbove;
  const viewH = Math.min(maxHeight, 4000);
  const start = virtual ? Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN) : 0;
  const end = virtual ? Math.min(sorted.length, Math.ceil((scrollTop + viewH) / ROW_H) + OVERSCAN) : sorted.length;
  const visible = sorted.slice(start, end);

  useEffect(() => {
    if (active >= sorted.length) setActive(Math.max(0, sorted.length - 1));
  }, [sorted.length, active]);

  const reveal = useCallback(
    (idx: number) => {
      const el = scroller.current;
      if (!el) return;
      const top = idx * ROW_H;
      const headerH = ROW_H;
      if (top < el.scrollTop) el.scrollTop = top;
      else if (top + ROW_H + headerH > el.scrollTop + el.clientHeight) el.scrollTop = top + ROW_H + headerH - el.clientHeight;
    },
    [],
  );

  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    if (e.target !== e.currentTarget) return;
    let n = active;
    if (e.key === 'j' || e.key === 'ArrowDown') n = Math.min(sorted.length - 1, active + 1);
    else if (e.key === 'k' || e.key === 'ArrowUp') n = Math.max(0, active - 1);
    else if (e.key === 'Home') n = 0;
    else if (e.key === 'End') n = sorted.length - 1;
    else if (e.key === 'PageDown') n = Math.min(sorted.length - 1, active + 10);
    else if (e.key === 'PageUp') n = Math.max(0, active - 10);
    else if (e.key === 'Enter' && sorted[active] && onRowActivate) {
      e.preventDefault();
      onRowActivate(sorted[active]);
      return;
    } else return;
    e.preventDefault();
    setActive(n);
    reveal(n);
  }

  function toggleSort(col: Column<T>) {
    if (!col.sortValue) return;
    setSort((s) => (s?.key === col.key ? (s.dir === 'asc' ? { key: col.key, dir: 'desc' } : null) : { key: col.key, dir: 'asc' }));
  }

  if (sorted.length === 0 && empty) return <>{empty}</>;

  const activeId = sorted[active] ? `${uid}-r-${active}` : undefined;
  return (
    <div
      ref={scroller}
      className={cx('acr-tablewrap', virtual && 'is-virtual', className)}
      style={virtual ? { maxBlockSize: maxHeight } : undefined}
      tabIndex={0}
      role="group"
      aria-label={caption}
      data-testid={testId}
      aria-activedescendant={activeId}
      onKeyDown={onKey}
      onScroll={virtual ? (e) => setScrollTop(e.currentTarget.scrollTop) : undefined}
    >
      <table className="acr-table" aria-rowcount={sorted.length + 1}>
        <caption className="acr-sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((c) => {
              const dir = sort?.key === c.key ? sort.dir : null;
              return (
                <th
                  key={c.key}
                  scope="col"
                  className={cx(c.numeric && 'is-num')}
                  style={c.width ? { inlineSize: c.width } : undefined}
                  aria-sort={dir ? (dir === 'asc' ? 'ascending' : 'descending') : c.sortValue ? 'none' : undefined}
                >
                  {c.sortValue ? (
                    <button type="button" className="acr-th-btn" onClick={() => toggleSort(c)}>
                      {c.header}
                      {dir === 'asc' && <IconChevronUp size={12} />}
                      {dir === 'desc' && <IconChevronDown size={12} />}
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {virtual && start > 0 && (
            <tr aria-hidden="true" className="acr-spacer">
              <td colSpan={columns.length} style={{ blockSize: start * ROW_H }} />
            </tr>
          )}
          {visible.map((row, i) => {
            const idx = start + i;
            return (
              <tr
                key={rowKey(row)}
                id={`${uid}-r-${idx}`}
                aria-rowindex={idx + 2}
                {...(rowProps ? rowProps(row) : {})}
                className={cx(idx === active && 'is-active', onRowActivate && 'is-clickable')}
                onClick={() => {
                  setActive(idx);
                  onRowActivate?.(row);
                }}
              >
                {columns.map((c) => (
                  <td key={c.key} className={cx(c.numeric && 'is-num', c.mono && 'acr-mono')}>
                    {c.render ? c.render(row) : String((row as Record<string, unknown>)[c.key] ?? '')}
                  </td>
                ))}
              </tr>
            );
          })}
          {virtual && end < sorted.length && (
            <tr aria-hidden="true" className="acr-spacer">
              <td colSpan={columns.length} style={{ blockSize: (sorted.length - end) * ROW_H }} />
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
