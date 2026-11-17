import { useId } from 'react';
import type { ReactNode } from 'react';
import { cx } from '../../ds';
import './firm.css';

interface SwitchProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  hint?: ReactNode;
  disabled?: boolean;
  testId?: string;
}

/** Accessible on/off switch (role="switch"); thumb position uses logical offsets so it mirrors in RTL. */
export function Switch({ checked, onChange, label, hint, disabled, testId }: SwitchProps) {
  const id = useId();
  return (
    <div className={cx('acr-firm-switch', disabled && 'is-disabled')}>
      <button
        type="button"
        role="switch"
        id={id}
        aria-checked={checked}
        aria-describedby={hint ? `${id}-hint` : undefined}
        className="acr-firm-switch__track"
        disabled={disabled}
        data-testid={testId}
        onClick={() => onChange(!checked)}
      >
        <span className="acr-firm-switch__thumb" aria-hidden="true" />
      </button>
      <label htmlFor={id} className="acr-firm-switch__label">
        {label}
      </label>
      {hint && (
        <div id={`${id}-hint`} className="acr-firm-switch__hint">
          {hint}
        </div>
      )}
    </div>
  );
}
