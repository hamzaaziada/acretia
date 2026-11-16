import { useRef } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';
import { cx } from './util';

export interface TabItem {
  id: string;
  label: string;
  count?: number;
  disabled?: boolean;
}

export interface TabsProps {
  items: TabItem[];
  value: string;
  onChange: (id: string) => void;
  label: string;
  idPrefix?: string;
  className?: string;
}

export function tabId(prefix: string, id: string) {
  return `${prefix}-tab-${id}`;
}
export function panelId(prefix: string, id: string) {
  return `${prefix}-panel-${id}`;
}

export function Tabs({ items, value, onChange, label, idPrefix = 'tabs', className }: TabsProps) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const enabled = items.filter((i) => !i.disabled);

  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    const rtl = document.documentElement.dir === 'rtl';
    const idx = enabled.findIndex((i) => i.id === value);
    let next = -1;
    if (e.key === 'ArrowRight') next = idx + (rtl ? -1 : 1);
    else if (e.key === 'ArrowLeft') next = idx + (rtl ? 1 : -1);
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = enabled.length - 1;
    else return;
    e.preventDefault();
    const target = enabled[(next + enabled.length) % enabled.length];
    onChange(target.id);
    refs.current[target.id]?.focus();
  }

  return (
    <div role="tablist" aria-label={label} className={cx('acr-tabs', className)} onKeyDown={onKey}>
      {items.map((it) => {
        const selected = it.id === value;
        return (
          <button
            key={it.id}
            ref={(el) => {
              refs.current[it.id] = el;
            }}
            type="button"
            role="tab"
            id={tabId(idPrefix, it.id)}
            aria-selected={selected}
            aria-controls={panelId(idPrefix, it.id)}
            tabIndex={selected ? 0 : -1}
            disabled={it.disabled}
            className={cx('acr-tab', selected && 'is-selected')}
            onClick={() => onChange(it.id)}
          >
            {it.label}
            {it.count != null && <span className="acr-tab__count acr-num">{it.count}</span>}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({ idPrefix = 'tabs', id, children }: { idPrefix?: string; id: string; children: ReactNode }) {
  return (
    <div role="tabpanel" id={panelId(idPrefix, id)} aria-labelledby={tabId(idPrefix, id)} tabIndex={0} className="acr-tabpanel">
      {children}
    </div>
  );
}
