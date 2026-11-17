import { useCallback, useRef, useState } from 'react';
import type { KeyboardEvent, PointerEvent, ReactNode } from 'react';

export interface SplitPaneProps {
  start: ReactNode;
  end: ReactNode;
  /** Initial share of the start pane, 0-100. */
  initial?: number;
  min?: number;
  max?: number;
  label: string;
}

/** Two panes with a draggable and keyboard-resizable (arrow keys) divider; RTL aware. */
export function SplitPane({ start, end, initial = 50, min = 20, max = 80, label }: SplitPaneProps) {
  const [pct, setPct] = useState(initial);
  const box = useRef<HTMLDivElement>(null);
  const clamp = useCallback((v: number) => Math.max(min, Math.min(max, v)), [min, max]);

  function onPointerDown(e: PointerEvent<HTMLDivElement>) {
    e.currentTarget.setPointerCapture(e.pointerId);
  }
  function onPointerMove(e: PointerEvent<HTMLDivElement>) {
    if (!e.currentTarget.hasPointerCapture(e.pointerId) || !box.current) return;
    const r = box.current.getBoundingClientRect();
    const rtl = document.documentElement.dir === 'rtl';
    const x = rtl ? r.right - e.clientX : e.clientX - r.left;
    setPct(clamp((x / r.width) * 100));
  }
  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    const rtl = document.documentElement.dir === 'rtl';
    const step = e.shiftKey ? 10 : 2;
    if (e.key === 'ArrowLeft') setPct((p) => clamp(p + (rtl ? step : -step)));
    else if (e.key === 'ArrowRight') setPct((p) => clamp(p + (rtl ? -step : step)));
    else if (e.key === 'Home') setPct(min);
    else if (e.key === 'End') setPct(max);
    else return;
    e.preventDefault();
  }

  return (
    <div className="acr-split" ref={box}>
      <div className="acr-split__pane" style={{ flexBasis: `${pct}%` }}>
        {start}
      </div>
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={label}
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuenow={Math.round(pct)}
        tabIndex={0}
        className="acr-split__handle"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onKeyDown={onKey}
      />
      <div className="acr-split__pane acr-split__pane--end">{end}</div>
    </div>
  );
}
