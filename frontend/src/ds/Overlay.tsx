import { useId, useRef } from 'react';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { cx, useFocusTrap } from './util';
import { IconButton } from './Button';
import { IconX } from './icons';

interface OverlayProps {
  open: boolean;
  onClose: () => void;
  title: string;
  closeLabel: string;
  children: ReactNode;
  footer?: ReactNode;
  size?: 'sm' | 'md' | 'lg';
  description?: string;
}

/** Modal dialog: focus-trapped, Esc closes, focus returns to the trigger. */
export function Dialog({ open, onClose, title, closeLabel, children, footer, size = 'md', description }: OverlayProps) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descId = useId();
  useFocusTrap(open, ref, onClose);
  if (!open) return null;
  return createPortal(
    <div className="acr-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
        className={cx('acr-dialog', `acr-dialog--${size}`)}
      >
        <header className="acr-dialog__head">
          <h2 id={titleId} className="acr-dialog__title">
            {title}
          </h2>
          <IconButton aria-label={closeLabel} size="sm" onClick={onClose}>
            <IconX size={15} />
          </IconButton>
        </header>
        {description && (
          <p id={descId} className="acr-dialog__desc">
            {description}
          </p>
        )}
        <div className="acr-dialog__body">{children}</div>
        {footer && <footer className="acr-dialog__foot">{footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}

/** Side drawer that slides in from the inline end (right in LTR, left in RTL). */
export function Drawer({ open, onClose, title, closeLabel, children, footer, size = 'md' }: OverlayProps) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useFocusTrap(open, ref, onClose);
  if (!open) return null;
  return createPortal(
    <div className="acr-scrim acr-scrim--drawer" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} className={cx('acr-drawer', `acr-drawer--${size}`)}>
        <header className="acr-dialog__head">
          <h2 id={titleId} className="acr-dialog__title">
            {title}
          </h2>
          <IconButton aria-label={closeLabel} size="sm" onClick={onClose}>
            <IconX size={15} />
          </IconButton>
        </header>
        <div className="acr-drawer__body">{children}</div>
        {footer && <footer className="acr-dialog__foot">{footer}</footer>}
      </aside>
    </div>,
    document.body,
  );
}
