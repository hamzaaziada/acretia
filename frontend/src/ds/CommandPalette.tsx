import { useEffect, useId, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { cx, useFocusTrap } from './util';
import { Kbd } from './Feedback';

export interface PaletteItem {
  id: string;
  label: string;
  hint?: string;
  icon?: ReactNode;
  onSelect: () => void;
  /** Keep the palette open after selecting (e.g. filling the prompt from a suggestion). */
  keepOpen?: boolean;
}
export interface PaletteGroup {
  id: string;
  label: string;
  items: PaletteItem[];
}

export interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  label: string;
  placeholder: string;
  value: string;
  onValueChange: (v: string) => void;
  /** Enter with no highlighted result submits the free-text prompt. */
  onSubmit: (value: string) => void;
  groups: PaletteGroup[];
  /** Slot above the results, e.g. the deal chip. */
  toolbar?: ReactNode;
  hints: { enter: string; navigate: string; close: string };
  emptyLabel: string;
}

export function CommandPalette({ open, onClose, label, placeholder, value, onValueChange, onSubmit, groups, toolbar, hints, emptyLabel }: CommandPaletteProps) {
  const ref = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const listId = useId();
  const [active, setActive] = useState(-1);
  useFocusTrap(open, ref, onClose);

  const flat = useMemo(() => groups.flatMap((g) => g.items), [groups]);
  useEffect(() => setActive(-1), [value, open]);
  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);

  if (!open) return null;

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((a) => Math.min(flat.length - 1, a + 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((a) => Math.max(-1, a - 1));
    } else if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (active >= 0 && flat[active]) {
        flat[active].onSelect();
        if (!flat[active].keepOpen) onClose();
      } else if (value.trim()) {
        onSubmit(value.trim());
      }
    }
  }

  let idx = -1;
  return createPortal(
    <div className="acr-scrim acr-scrim--palette" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={label} className="acr-palette" tabIndex={-1}>
        <textarea
          ref={input}
          data-autofocus
          rows={2}
          className="acr-palette__input"
          placeholder={placeholder}
          aria-label={label}
          role="combobox"
          aria-expanded="true"
          aria-controls={listId}
          aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
          value={value}
          onChange={(e) => onValueChange(e.target.value)}
          onKeyDown={onKey}
        />
        {toolbar && <div className="acr-palette__toolbar">{toolbar}</div>}
        <div className="acr-palette__list" role="listbox" id={listId} aria-label={label}>
          {flat.length === 0 && <div className="acr-palette__empty">{emptyLabel}</div>}
          {groups
            .filter((g) => g.items.length)
            .map((g) => (
              <div key={g.id} role="group" aria-label={g.label}>
                <div className="acr-section-label acr-palette__group">{g.label}</div>
                {g.items.map((it) => {
                  idx += 1;
                  const my = idx;
                  return (
                    <div
                      key={it.id}
                      id={`${listId}-${my}`}
                      role="option"
                      aria-selected={my === active}
                      className={cx('acr-palette__item', my === active && 'is-active')}
                      onMouseEnter={() => setActive(my)}
                      onClick={() => {
                        it.onSelect();
                        if (!it.keepOpen) onClose();
                      }}
                    >
                      {it.icon && <span className="acr-palette__icon">{it.icon}</span>}
                      <span className="acr-palette__label">{it.label}</span>
                      {it.hint && <span className="acr-palette__hint">{it.hint}</span>}
                    </div>
                  );
                })}
              </div>
            ))}
        </div>
        <div className="acr-palette__foot">
          <span>
            <Kbd>↵</Kbd> {hints.enter}
          </span>
          <span>
            <Kbd>↑</Kbd>
            <Kbd>↓</Kbd> {hints.navigate}
          </span>
          <span>
            <Kbd>Esc</Kbd> {hints.close}
          </span>
        </div>
      </div>
    </div>,
    document.body,
  );
}
