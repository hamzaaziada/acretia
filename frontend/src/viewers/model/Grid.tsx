import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { useI18n } from '../../i18n';
import type { ModelCell, ModelSheet } from '../shared/api';
import { editText, formatValue, parseInput } from './format';

export const ROW_H = 22;
export const HEAD_W = 46;
const MIN_COL = 40;
const DEF_COL = 76;

const cellId = (ref: string) => `mv-${ref.replace(/[^\w-]/g, '_')}`;

export function colLetter(c: number): string {
  let s = '';
  for (let n = c; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + ((n - 1) % 26)) + s;
  return s;
}

export type Flag = 'hard' | 'err';

export interface GridProps {
  sheet: ModelSheet;
  cells: Record<string, ModelCell>;
  valueOf: (ref: string) => ModelCell['v'];
  overlay: boolean;
  editable: boolean;
  selected: { r: number; c: number };
  onSelect: (r: number, c: number) => void;
  /** An edit made in the grid (typed value); the page runs the recompute. */
  onCommit: (ref: string, value: number | string) => void;
  edits: Record<string, number | string>;
  flash: Record<string, number>;
  flags: Record<string, Flag>;
  checkStatus: Record<string, 'pass' | 'fail'>;
  onSheetStep: (d: 1 | -1) => void;
  focusToken: number;
}

interface CellProps {
  refKey: string;
  r: number;
  c: number;
  x: number;
  y: number;
  w: number;
  cell: ModelCell | undefined;
  value: ModelCell['v'];
  overlay: boolean;
  selected: boolean;
  edited: boolean;
  flashN: number | undefined;
  flag: Flag | undefined;
  check: 'pass' | 'fail' | undefined;
  arabicDigits: boolean;
  editing: boolean;
  editInit: string;
  onEditEnd: (commit: boolean, text: string, move?: 'right' | 'down') => void;
  checkLabel: string;
  sourceLabel: string;
}

const Cell = memo(function Cell(p: CellProps) {
  const { cell, value } = p;
  const cls = cell?.cls ?? 'label';
  const isNum = typeof value === 'number';
  const text = cell ? formatValue(value, cell.fmt, { arabicDigits: p.arabicDigits }) : '';
  const bgKind = cell?.bg ? lum(cell.bg) : null;
  const classes = [
    'mv__cell',
    `is-${cls}`,
    isNum || cell?.al === 'right' ? 'is-num' : cell?.al === 'center' ? 'is-center' : 'is-text',
    cell?.b ? 'is-bold' : '',
    cell?.bt ? 'has-bt' : '',
    cell?.bb ? 'has-bb' : '',
    bgKind === 'dark' ? 'bg-dark' : bgKind === 'light' ? 'bg-light' : bgKind === 'mid' ? 'bg-mid' : '',
    p.selected ? 'is-selected' : '',
    p.edited ? 'is-edited' : '',
    p.flag ? `flag-${p.flag}` : '',
    cell?.err ? 'is-err' : '',
  ]
    .filter(Boolean)
    .join(' ');
  return (
    <div
      role="gridcell"
      id={cellId(p.refKey)}
      className={classes}
      data-testid="model-cell"
      data-ref={p.refKey}
      data-class={cls}
      data-row={p.r}
      data-col={p.c}
      aria-selected={p.selected}
      aria-rowindex={p.r}
      aria-colindex={p.c}
      style={{ insetInlineStart: p.x, insetBlockStart: p.y, inlineSize: p.w, blockSize: ROW_H, paddingInlineStart: cell?.ind ? 6 + cell.ind * 10 : undefined }}
      onMouseDown={() => undefined}
    >
      {p.flashN !== undefined && <span key={p.flashN} className="mv__flash" aria-hidden="true" />}
      {p.editing ? (
        <CellEditor init={p.editInit} onEnd={p.onEditEnd} />
      ) : (
        <>
          {p.check && p.overlay && (
            <span className="mv__check" data-testid="check-badge" data-status={p.check} role="img" aria-label={p.checkLabel}>
              {p.check === 'pass' ? '✓' : '✕'}
            </span>
          )}
          <span className="mv__val" dir="auto">
            {text}
          </span>
          {cell && (cell.citation_token || cell.note) && !p.editing && (
            <span
              className="mv__src"
              {...(cell.citation_token ? { 'data-cite': cell.citation_token, tabIndex: -1, role: 'link' } : { title: cell.note })}
              aria-label={cell.citation_token ? p.sourceLabel : cell.note}
            />
          )}
        </>
      )}
    </div>
  );
});

function CellEditor({ init, onEnd }: { init: string; onEnd: CellProps['onEditEnd'] }) {
  const ref = useRef<HTMLInputElement>(null);
  const done = useRef(false);
  useEffect(() => {
    ref.current?.focus();
    ref.current?.select(); // typing replaces the old value, like a spreadsheet's type-over
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const end = (commit: boolean, move?: 'right' | 'down') => {
    if (done.current) return;
    done.current = true;
    onEnd(commit, ref.current?.value ?? init, move);
  };
  return (
    <input
      ref={ref}
      className="mv__editor"
      defaultValue={init}
      inputMode="decimal"
      aria-label="edit"
      dir="ltr"
      onKeyDown={(e) => {
        e.stopPropagation();
        if (e.key === 'Enter') {
          e.preventDefault();
          end(true, 'down');
        } else if (e.key === 'Tab') {
          e.preventDefault();
          end(true, 'right');
        } else if (e.key === 'Escape') {
          e.preventDefault();
          end(false);
        }
      }}
      onBlur={() => end(true)}
    />
  );
}

function lum(hex: string): 'dark' | 'mid' | 'light' {
  const n = parseInt(hex, 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  const l = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return l < 0.4 ? 'dark' : l > 0.88 ? 'light' : 'mid';
}

export function Grid(props: GridProps) {
  const { sheet, cells, valueOf, selected } = props;
  const { t, arabicDigits } = useI18n();
  const hostRef = useRef<HTMLDivElement>(null);
  const mainRef = useRef<HTMLDivElement>(null);
  const [vp, setVp] = useState({ w: 900, h: 500 });
  const [scroll, setScroll] = useState({ x: 0, y: 0 });
  const [editing, setEditing] = useState<{ ref: string; init: string } | null>(null);
  const raf = useRef(0);

  const nR = Math.max(sheet.rows + 2, 30);
  const nC = Math.max(sheet.cols, 1);
  const fr = sheet.freeze.rows;
  const fc = sheet.freeze.cols;

  const widths = useMemo(() => {
    const w = [HEAD_W];
    for (let c = 1; c <= nC; c++) {
      const chars = sheet.widths[colLetter(c)];
      w.push(chars ? Math.max(MIN_COL, Math.round(chars * 7.6 + 6)) : DEF_COL);
    }
    return w;
  }, [sheet, nC]);
  const xs = useMemo(() => {
    const a = [0];
    for (let c = 0; c <= nC; c++) a.push(a[c] + widths[c]);
    return a; // a[c] = left edge of column c (0 is the row-header column)
  }, [widths, nC]);
  const leftW = xs[fc + 1];
  const topH = (fr + 1) * ROW_H;
  const totalW = xs[nC + 1];
  const totalH = (nR + 1) * ROW_H;

  useLayoutEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setVp({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setVp({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    mainRef.current?.scrollTo({ left: 0, top: 0 });
    setScroll({ x: 0, y: 0 });
    setEditing(null);
  }, [sheet.name]);

  const onScroll = useCallback(() => {
    cancelAnimationFrame(raf.current);
    raf.current = requestAnimationFrame(() => {
      const m = mainRef.current;
      if (m) setScroll({ x: m.scrollLeft, y: m.scrollTop });
    });
  }, []);

  // visible window (data region)
  const viewW = Math.max(0, vp.w - leftW);
  const viewH = Math.max(0, vp.h - topH);
  const r0 = Math.max(fr + 1, Math.floor(scroll.y / ROW_H) + fr + 1 - 1);
  const r1 = Math.min(nR, r0 + Math.ceil(viewH / ROW_H) + 3);
  const cols = useMemo(() => {
    const out: number[] = [];
    for (let c = fc + 1; c <= nC; c++) {
      const x = xs[c] - leftW;
      if (x + widths[c] >= scroll.x - 80 && x <= scroll.x + viewW + 80) out.push(c);
    }
    return out;
  }, [fc, nC, xs, leftW, widths, scroll.x, viewW]);

  // keep the selection on screen
  useEffect(() => {
    const m = mainRef.current;
    if (!m) return;
    const { r, c } = selected;
    if (c > fc) {
      const x = xs[c] - leftW;
      if (x < m.scrollLeft) m.scrollLeft = x;
      else if (x + widths[c] > m.scrollLeft + m.clientWidth) m.scrollLeft = x + widths[c] - m.clientWidth;
    }
    if (r > fr) {
      const y = (r - fr - 1) * ROW_H;
      if (y < m.scrollTop) m.scrollTop = y;
      else if (y + ROW_H > m.scrollTop + m.clientHeight) m.scrollTop = y + ROW_H - m.clientHeight;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected.r, selected.c]);

  useEffect(() => {
    if (props.focusToken) hostRef.current?.focus({ preventScroll: true });
  }, [props.focusToken]);

  const refOf = (r: number, c: number) => `${sheet.name}!${colLetter(c)}${r}`;
  const selRef = refOf(selected.r, selected.c);
  const selCell = cells[selRef];
  const canEdit = (ref: string) => props.editable && cells[ref]?.cls === 'input';

  function startEdit(ref: string, seed?: string) {
    if (!canEdit(ref)) return;
    const v = props.edits[ref] ?? valueOf(ref);
    setEditing({ ref, init: seed ?? editText(v, cells[ref]?.fmt) });
  }

  const endRef = useRef<CellProps['onEditEnd']>(() => undefined);
  const stableEnd = useCallback<CellProps['onEditEnd']>((c, t2, m) => endRef.current(c, t2, m), []);
  function endEdit(commit: boolean, text: string, move?: 'right' | 'down') {
    const e = editing;
    setEditing(null);
    if (e && commit && text !== e.init) {
      const n = parseInput(text, cells[e.ref]?.fmt);
      if (n !== null) props.onCommit(e.ref, n);
    }
    window.setTimeout(() => hostRef.current?.focus({ preventScroll: true }), 0);
    if (move === 'down') props.onSelect(Math.min(nR, selected.r + 1), selected.c);
    else if (move === 'right') props.onSelect(selected.r, Math.min(nC, selected.c + 1));
  }

  endRef.current = endEdit;

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (editing) return;
    const { r, c } = selected;
    const page = Math.max(1, Math.floor(viewH / ROW_H) - 1);
    let nr = r;
    let nc = c;
    switch (e.key) {
      case 'ArrowDown':
        nr = Math.min(nR, r + 1);
        break;
      case 'ArrowUp':
        nr = Math.max(1, r - 1);
        break;
      case 'ArrowRight':
        nc = Math.min(nC, c + 1);
        break;
      case 'ArrowLeft':
        nc = Math.max(1, c - 1);
        break;
      case 'Tab':
        nc = e.shiftKey ? Math.max(1, c - 1) : Math.min(nC, c + 1);
        break;
      case 'Home':
        nc = 1;
        if (e.ctrlKey || e.metaKey) nr = 1;
        break;
      case 'End':
        nc = nC;
        break;
      case 'PageDown':
        nr = Math.min(nR, r + page);
        break;
      case 'PageUp':
        nr = Math.max(1, r - page);
        break;
      case 'Enter':
      case 'F2':
        if (canEdit(selRef)) {
          e.preventDefault();
          startEdit(selRef);
        } else if (e.key === 'Enter') nr = Math.min(nR, r + 1);
        break;
      case '[':
        e.preventDefault();
        props.onSheetStep(-1);
        return;
      case ']':
        e.preventDefault();
        props.onSheetStep(1);
        return;
      default:
        if (!e.ctrlKey && !e.metaKey && !e.altKey) {
          if (e.key === 'e' && canEdit(selRef)) {
            e.preventDefault();
            startEdit(selRef);
            return;
          }
          if (/^[0-9.\-]$/.test(e.key) && canEdit(selRef)) {
            e.preventDefault();
            startEdit(selRef, e.key);
            return;
          }
        }
        return;
    }
    e.preventDefault();
    if (nr !== r || nc !== c) props.onSelect(nr, nc);
  }

  function renderCell(r: number, c: number, x: number, y: number) {
    const ref = refOf(r, c);
    const cell = cells[ref];
    const spill = spanOf(r, c);
    const w = spill > 0 ? widths[c] + spill : widths[c];
    return (
      <Cell
        key={`${ref}:${props.flash[ref] ?? 0}`}
        refKey={ref}
        r={r}
        c={c}
        x={x}
        y={y}
        w={w}
        cell={cell}
        value={cell ? valueOf(ref) : null}
        overlay={props.overlay}
        selected={selected.r === r && selected.c === c}
        edited={ref in props.edits}
        flashN={props.flash[ref]}
        flag={props.flags[ref]}
        check={props.checkStatus[ref]}
        arabicDigits={arabicDigits}
        editing={editing?.ref === ref}
        editInit={editing?.ref === ref ? editing.init : ''}
        onEditEnd={stableEnd}
        checkLabel={t(props.checkStatus[ref] === 'pass' ? 'viewers.model.checkPass' : 'viewers.model.checkFail')}
        sourceLabel={t('viewers.model.openSource')}
      />
    );
  }

  /** Text spills across following empty cells, like Excel, but never across the frozen-pane boundary. */
  function spanOf(r: number, c: number): number {
    const cell = cells[refOf(r, c)];
    if (!cell || typeof cell.v !== 'string' || !cell.v || cell.cls === 'header') return 0;
    let extra = 0;
    for (let k = c + 1; k <= nC && k - c <= 10; k++) {
      if (c <= fc && k > fc) break;
      const n = cells[refOf(r, k)];
      if (n && (n.v !== null && n.v !== '')) break;
      extra += widths[k];
    }
    return extra;
  }

  const rowsData: number[] = [];
  for (let r = r0; r <= r1; r++) rowsData.push(r);
  const rowsFrozen = Array.from({ length: fr }, (_, i) => i + 1);
  const colsFrozen = Array.from({ length: fc }, (_, i) => i + 1);

  const headCell = (kind: 'col' | 'row' | 'corner', n: number, x: number, y: number, w: number) => (
    <div
      key={`${kind}${n}`}
      role={kind === 'col' ? 'columnheader' : 'rowheader'}
      className={`mv__head is-${kind}${(kind === 'col' && selected.c === n) || (kind === 'row' && selected.r === n) ? ' is-active' : ''}`}
      style={{ insetInlineStart: x, insetBlockStart: y, inlineSize: w, blockSize: ROW_H }}
      aria-hidden={kind === 'corner' || undefined}
    >
      {kind === 'col' ? colLetter(n) : kind === 'row' ? n : ''}
    </div>
  );

  return (
    <div
      ref={hostRef}
      className="mv__grid"
      dir="ltr"
      role="grid"
      tabIndex={0}
      aria-label={sheet.name}
      aria-rowcount={nR}
      aria-colcount={nC}
      aria-activedescendant={cellId(selRef)}
      onKeyDown={onKeyDown}
      onMouseDown={(e) => {
        const el = (e.target as HTMLElement).closest<HTMLElement>('[data-ref]');
        if (el && !(e.target as HTMLElement).closest('.mv__editor')) {
          props.onSelect(Number(el.dataset.row), Number(el.dataset.col));
          hostRef.current?.focus({ preventScroll: true });
        }
      }}
      onDoubleClick={(e) => {
        const el = (e.target as HTMLElement).closest<HTMLElement>('[data-ref]');
        if (el?.dataset.ref) startEdit(el.dataset.ref);
      }}
      data-overlay={props.overlay}
      data-selected={selRef}
      data-cell-class={selCell?.cls}
    >
      {/* corner: frozen rows x frozen cols (+ the headers) */}
      <div className="mv__pane is-corner" style={{ inlineSize: leftW, blockSize: topH }}>
        {headCell('corner', 0, 0, 0, HEAD_W)}
        {colsFrozen.map((c) => headCell('col', c, xs[c], 0, widths[c]))}
        {rowsFrozen.map((r) => headCell('row', r, 0, r * ROW_H, HEAD_W))}
        {rowsFrozen.flatMap((r) => colsFrozen.map((c) => renderCell(r, c, xs[c], r * ROW_H)))}
      </div>
      {/* top: column headers + frozen rows for the scrolling columns */}
      <div className="mv__pane is-top" style={{ insetInlineStart: leftW, inlineSize: viewW, blockSize: topH }}>
        <div className="mv__inner" style={{ transform: `translateX(${-scroll.x}px)`, inlineSize: totalW - leftW, blockSize: topH }}>
          {cols.map((c) => headCell('col', c, xs[c] - leftW, 0, widths[c]))}
          {rowsFrozen.flatMap((r) => cols.map((c) => renderCell(r, c, xs[c] - leftW, r * ROW_H)))}
        </div>
      </div>
      {/* left: row headers + frozen columns for the scrolling rows */}
      <div className="mv__pane is-left" style={{ insetBlockStart: topH, inlineSize: leftW, blockSize: viewH }}>
        <div className="mv__inner" style={{ transform: `translateY(${-scroll.y}px)`, inlineSize: leftW, blockSize: totalH - topH }}>
          {rowsData.map((r) => headCell('row', r, 0, (r - fr - 1) * ROW_H, HEAD_W))}
          {rowsData.flatMap((r) => colsFrozen.map((c) => renderCell(r, c, xs[c], (r - fr - 1) * ROW_H)))}
        </div>
      </div>
      {/* main scrolling body */}
      <div ref={mainRef} className="mv__main" style={{ insetInlineStart: leftW, insetBlockStart: topH }} onScroll={onScroll}>
        <div className="mv__sizer" style={{ inlineSize: totalW - leftW, blockSize: totalH - topH }}>
          {rowsData.flatMap((r) => cols.map((c) => renderCell(r, c, xs[c] - leftW, (r - fr - 1) * ROW_H)))}
        </div>
      </div>
    </div>
  );
}
