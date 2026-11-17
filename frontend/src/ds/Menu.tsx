import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { cx } from './util';

/** Button + popover menu. Esc and outside click close it; focus returns to the trigger. */
export function MenuButton({
  trigger,
  label,
  children,
  up,
  testId,
  triggerClassName,
}: {
  trigger: ReactNode;
  label: string;
  children: (close: () => void) => ReactNode;
  up?: boolean;
  testId?: string;
  triggerClassName?: string;
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    function down(e: MouseEvent) {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    }
    function key(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.stopPropagation();
        setOpen(false);
        btn.current?.focus();
      }
    }
    document.addEventListener('mousedown', down);
    document.addEventListener('keydown', key, true);
    return () => {
      document.removeEventListener('mousedown', down);
      document.removeEventListener('keydown', key, true);
    };
  }, [open]);

  return (
    <div className="acr-menu-wrap" ref={wrap}>
      <button
        ref={btn}
        type="button"
        className={cx('acr-menubtn', triggerClassName)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        data-testid={testId}
        onClick={() => setOpen((o) => !o)}
      >
        {trigger}
      </button>
      {open && (
        <div role="menu" aria-label={label} className={cx('acr-menu', up && 'acr-menu--up')}>
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

export function MenuItem({ onSelect, children, testId, pressed }: { onSelect: () => void; children: ReactNode; testId?: string; pressed?: boolean }) {
  return (
    <button type="button" role="menuitem" className="acr-menu__item" data-testid={testId} aria-current={pressed || undefined} onClick={onSelect}>
      {children}
    </button>
  );
}

export function MenuLabel({ children }: { children: ReactNode }) {
  return <div className="acr-menu__label">{children}</div>;
}
export function MenuSep() {
  return <div className="acr-menu__sep" role="separator" />;
}

export function Segmented<T extends string>({ value, options, onChange, label, testId }: { value: T; options: Array<{ value: T; label: string }>; onChange: (v: T) => void; label: string; testId?: string }) {
  return (
    <div className="acr-seg" role="group" aria-label={label} data-testid={testId}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
