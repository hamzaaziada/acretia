import { useSyncExternalStore } from 'react';
import type { Cell } from './types';

/**
 * Cells live in a Map outside React state. A cell component subscribes to its own key, so a streamed update re-renders one cell,
 * never the table (parity item 12: 60 fps scroll and sort on 500 rows).
 */
export class CellStore {
  private cells = new Map<string, Cell>();
  private subs = new Map<string, Set<() => void>>();
  private anySubs = new Set<() => void>();
  /** Bumped on bulk loads and when a stream goes idle; table-level memos (sort, filter) key off it, not off single cells. */
  version = 0;

  static key(row: string, col: string): string {
    return `${row}|${col}`;
  }

  get(row: string, col: string): Cell | undefined {
    return this.cells.get(CellStore.key(row, col));
  }

  getByKey = (key: string): Cell | undefined => this.cells.get(key);

  replaceAll(cells: Cell[]): void {
    const old = this.cells;
    this.cells = new Map(cells.map((c) => [CellStore.key(c.row, c.col), c]));
    this.version += 1;
    for (const key of new Set([...old.keys(), ...this.cells.keys()])) this.subs.get(key)?.forEach((f) => f());
    this.anySubs.forEach((f) => f());
  }

  set(cell: Cell): void {
    const key = CellStore.key(cell.row, cell.col);
    const prev = this.cells.get(key);
    // streamed events omit fields the full payload carries; keep what the event does not send
    this.cells.set(key, { ...prev, ...cell, citations: cell.citations ?? prev?.citations ?? [] });
    this.subs.get(key)?.forEach((f) => f());
  }

  markQueued(colId: string, rowIds: string[]): void {
    for (const r of rowIds) this.set({ row: r, col: colId, state: 'queued', value: '', citations: [] });
  }

  bump(): void {
    this.version += 1;
    this.anySubs.forEach((f) => f());
  }

  subscribe = (key: string, fn: () => void): (() => void) => {
    let set = this.subs.get(key);
    if (!set) this.subs.set(key, (set = new Set()));
    set.add(fn);
    return () => {
      set!.delete(fn);
      if (set!.size === 0) this.subs.delete(key);
    };
  };

  subscribeAny = (fn: () => void): (() => void) => {
    this.anySubs.add(fn);
    return () => this.anySubs.delete(fn);
  };

  values(): Cell[] {
    return [...this.cells.values()];
  }

  stateCounts(): Record<string, number> {
    const out: Record<string, number> = {};
    for (const c of this.cells.values()) out[c.state] = (out[c.state] ?? 0) + 1;
    return out;
  }
}

export function useCell(store: CellStore, row: string, col: string): Cell | undefined {
  const key = CellStore.key(row, col);
  return useSyncExternalStore(
    (fn) => store.subscribe(key, fn),
    () => store.getByKey(key),
    () => undefined,
  );
}

export function useStoreVersion(store: CellStore): number {
  return useSyncExternalStore(store.subscribeAny, () => store.version, () => 0);
}

/** Display text of a cell for sorting and filtering. */
export function cellText(c: Cell | undefined): string {
  if (!c) return '';
  if (c.state === 'done') return c.value;
  return '';
}

export function compareCells(a: Cell | undefined, b: Cell | undefined): number {
  const x = cellText(a);
  const y = cellText(b);
  const nx = Number(x.replace(/[,$%\s]/g, ''));
  const ny = Number(y.replace(/[,$%\s]/g, ''));
  if (x !== '' && y !== '' && Number.isFinite(nx) && Number.isFinite(ny)) return nx - ny;
  if (x === '' && y !== '') return 1;
  if (y === '' && x !== '') return -1;
  return x.localeCompare(y, undefined, { numeric: true, sensitivity: 'base' });
}
