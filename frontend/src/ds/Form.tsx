import { forwardRef, useId } from 'react';
import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react';
import { cx } from './util';
import { IconChevronDown } from './icons';

interface FieldProps {
  label: string;
  hint?: string;
  error?: string;
  hideLabel?: boolean;
}

function Field({
  id,
  label,
  hint,
  error,
  hideLabel,
  children,
  className,
}: FieldProps & { id: string; children: ReactNode; className?: string }) {
  return (
    <div className={cx('acr-field', error && 'has-error', className)}>
      <label htmlFor={id} className={cx('acr-label', hideLabel && 'acr-sr-only')}>
        {label}
      </label>
      {children}
      {error ? (
        <div className="acr-field__error" id={`${id}-err`} role="alert">
          {error}
        </div>
      ) : hint ? (
        <div className="acr-field__hint" id={`${id}-hint`}>
          {hint}
        </div>
      ) : null}
    </div>
  );
}

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'>, FieldProps {
  mono?: boolean;
  startSlot?: ReactNode;
  fieldClassName?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, hint, error, hideLabel, mono, startSlot, className, fieldClassName, id: idProp, ...rest },
  ref,
) {
  const auto = useId();
  const id = idProp ?? auto;
  return (
    <Field id={id} label={label} hint={hint} error={error} hideLabel={hideLabel} className={fieldClassName}>
      <div className="acr-inputwrap">
        {startSlot && <span className="acr-inputwrap__slot">{startSlot}</span>}
        <input
          ref={ref}
          id={id}
          className={cx('acr-input', mono && 'acr-mono', startSlot && 'has-slot', className)}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-err` : hint ? `${id}-hint` : undefined}
          {...rest}
        />
      </div>
    </Field>
  );
});

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement>, FieldProps {
  fieldClassName?: string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { label, hint, error, hideLabel, className, fieldClassName, id: idProp, ...rest },
  ref,
) {
  const auto = useId();
  const id = idProp ?? auto;
  return (
    <Field id={id} label={label} hint={hint} error={error} hideLabel={hideLabel} className={fieldClassName}>
      <textarea
        ref={ref}
        id={id}
        className={cx('acr-input acr-textarea', className)}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-err` : hint ? `${id}-hint` : undefined}
        {...rest}
      />
    </Field>
  );
});

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'size'>, FieldProps {
  options: SelectOption[];
  fieldClassName?: string;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { label, hint, error, hideLabel, options, className, fieldClassName, id: idProp, ...rest },
  ref,
) {
  const auto = useId();
  const id = idProp ?? auto;
  return (
    <Field id={id} label={label} hint={hint} error={error} hideLabel={hideLabel} className={fieldClassName}>
      <div className="acr-selectwrap">
        <select
          ref={ref}
          id={id}
          className={cx('acr-input acr-select', className)}
          aria-invalid={error ? true : undefined}
          {...rest}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <IconChevronDown size={14} className="acr-selectwrap__chev" />
      </div>
    </Field>
  );
});

export interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'size'> {
  label: string;
  hint?: string;
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox(
  { label, hint, className, id: idProp, ...rest },
  ref,
) {
  const auto = useId();
  const id = idProp ?? auto;
  return (
    <div className={cx('acr-check', className)}>
      <input ref={ref} id={id} type="checkbox" className="acr-check__box" aria-describedby={hint ? `${id}-hint` : undefined} {...rest} />
      <label htmlFor={id} className="acr-check__label">
        {label}
        {hint && (
          <span className="acr-check__hint" id={`${id}-hint`}>
            {hint}
          </span>
        )}
      </label>
    </div>
  );
});
