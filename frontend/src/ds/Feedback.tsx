import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { cx } from './util';
import { Button } from './Button';
import { IconAlert, IconCheck, IconInfo, IconX } from './icons';

export type Tone = 'neutral' | 'accent' | 'positive' | 'warning' | 'negative' | 'info';

export function Badge({ tone = 'neutral', children, dot }: { tone?: Tone; children: ReactNode; dot?: boolean }) {
  return (
    <span className={cx('acr-badge', `acr-badge--${tone}`)}>
      {dot && <span className="acr-badge__dot" aria-hidden="true" />}
      {children}
    </span>
  );
}

export function Pill({ children, onRemove, removeLabel }: { children: ReactNode; onRemove?: () => void; removeLabel?: string }) {
  return (
    <span className="acr-pill">
      <span className="acr-pill__text">{children}</span>
      {onRemove && (
        <button type="button" className="acr-pill__x" onClick={onRemove} aria-label={removeLabel}>
          <IconX size={11} />
        </button>
      )}
    </span>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="acr-kbd">{children}</kbd>;
}

export function Skeleton({ width, height = 12, className }: { width?: string | number; height?: number; className?: string }) {
  return <span className={cx('acr-skeleton', className)} style={{ inlineSize: width ?? '100%', blockSize: height }} aria-hidden="true" />;
}

export function SkeletonRows({ rows = 5, label }: { rows?: number; label: string }) {
  return (
    <div className="acr-skeleton-rows" role="status" aria-label={label}>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} height={14} width={`${92 - ((i * 13) % 35)}%`} />
      ))}
    </div>
  );
}

export function ProgressBar({ value, label, tone = 'accent' }: { value: number | null; label: string; tone?: 'accent' | 'positive' | 'negative' }) {
  const pct = value == null ? undefined : Math.max(0, Math.min(100, value));
  return (
    <div
      className={cx('acr-progress', `acr-progress--${tone}`, pct == null && 'is-indeterminate')}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
    >
      <div className="acr-progress__bar" style={pct == null ? undefined : { inlineSize: `${pct}%` }} />
    </div>
  );
}

export interface EmptyAction {
  label: string;
  onClick: () => void;
  icon?: ReactNode;
}

/** An empty state always carries a next action: no dead ends. */
export function EmptyState({ title, body, action, secondary, icon }: { title: string; body?: string; action: EmptyAction; secondary?: EmptyAction; icon?: ReactNode }) {
  return (
    <div className="acr-empty" role="status">
      {icon && <div className="acr-empty__icon">{icon}</div>}
      <h3 className="acr-empty__title">{title}</h3>
      {body && <p className="acr-empty__body">{body}</p>}
      <div className="acr-empty__actions">
        <Button variant="primary" icon={action.icon} onClick={action.onClick}>
          {action.label}
        </Button>
        {secondary && (
          <Button variant="ghost" icon={secondary.icon} onClick={secondary.onClick}>
            {secondary.label}
          </Button>
        )}
      </div>
    </div>
  );
}

export function Avatar({ name, size = 24 }: { name: string; size?: number }) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => Array.from(p)[0])
    .join('')
    .toUpperCase();
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return (
    <span className="acr-avatar" style={{ inlineSize: size, blockSize: size, fontSize: Math.round(size * 0.42), ['--acr-hue' as string]: h }} aria-hidden="true">
      {initials || '?'}
    </span>
  );
}

export function Tooltip({ text, children }: { text: string; children: ReactNode }) {
  const id = useId();
  return (
    <span className="acr-tooltip" aria-describedby={id}>
      {children}
      <span role="tooltip" id={id} className="acr-tooltip__bubble">
        {text}
      </span>
    </span>
  );
}

/* ---------- Toasts ---------- */

export interface ToastInput {
  kind?: 'info' | 'success' | 'error';
  title: string;
  body?: string;
  hint?: string;
  action?: { label: string; onClick: () => void };
  ttl?: number;
}
interface ToastItem extends ToastInput {
  id: number;
}

const ToastCtx = createContext<{ push: (t: ToastInput) => void } | null>(null);

export function useToast() {
  const c = useContext(ToastCtx);
  if (!c) throw new Error('ToastProvider missing');
  return c;
}

export function ToastProvider({ children, dismissLabel }: { children: ReactNode; dismissLabel: string }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const seq = useRef(0);
  const dismiss = useCallback((id: number) => setItems((s) => s.filter((t) => t.id !== id)), []);
  const push = useCallback(
    (t: ToastInput) => {
      const id = ++seq.current;
      setItems((s) => [...s.slice(-3), { ...t, id }]);
    },
    [],
  );
  const value = useMemo(() => ({ push }), [push]);
  return (
    <ToastCtx.Provider value={value}>
      {children}
      <div className="acr-toasts" role="region" aria-live="polite" aria-atomic="false">
        {items.map((t) => (
          <ToastView key={t.id} item={t} onDismiss={() => dismiss(t.id)} dismissLabel={dismissLabel} />
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

function ToastView({ item, onDismiss, dismissLabel }: { item: ToastItem; onDismiss: () => void; dismissLabel: string }) {
  useEffect(() => {
    const h = window.setTimeout(onDismiss, item.ttl ?? (item.kind === 'error' ? 9000 : 5000));
    return () => window.clearTimeout(h);
  }, [item, onDismiss]);
  const kind = item.kind ?? 'info';
  return (
    <div className={cx('acr-toast', `acr-toast--${kind}`)} role={kind === 'error' ? 'alert' : 'status'}>
      <span className="acr-toast__icon">{kind === 'error' ? <IconAlert size={16} /> : kind === 'success' ? <IconCheck size={16} /> : <IconInfo size={16} />}</span>
      <div className="acr-toast__main">
        <div className="acr-toast__title">{item.title}</div>
        {item.body && <div className="acr-toast__body">{item.body}</div>}
        {item.hint && <div className="acr-toast__hint">{item.hint}</div>}
        {item.action && (
          <button type="button" className="acr-toast__action" onClick={() => { item.action?.onClick(); onDismiss(); }}>
            {item.action.label}
          </button>
        )}
      </div>
      <button type="button" className="acr-toast__x" onClick={onDismiss} aria-label={dismissLabel}>
        <IconX size={13} />
      </button>
    </div>
  );
}
