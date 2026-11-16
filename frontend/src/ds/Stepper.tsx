import type { ReactNode } from 'react';
import { cx } from './util';
import { IconAlert, IconCheck, IconSpinner } from './icons';

export type StepStatus = 'queued' | 'running' | 'done' | 'failed' | 'skipped';

export interface StepItem {
  id: string;
  title: string;
  status: StepStatus;
  detail?: string;
  meta?: ReactNode;
  statusLabel: string;
  children?: ReactNode;
}

/** Vertical stepper for agent plan steps. */
export function Stepper({ steps, label }: { steps: StepItem[]; label: string }) {
  return (
    <ol className="acr-stepper" aria-label={label}>
      {steps.map((s, i) => (
        <li key={s.id} className={cx('acr-step', `acr-step--${s.status}`)} aria-current={s.status === 'running' ? 'step' : undefined}>
          <span className="acr-step__mark" aria-hidden="true">
            {s.status === 'done' ? <IconCheck size={12} /> : s.status === 'running' ? <IconSpinner size={12} className="acr-spin" /> : s.status === 'failed' ? <IconAlert size={12} /> : s.status === 'skipped' ? <span className="acr-step__dash" /> : <span className="acr-num">{i + 1}</span>}
          </span>
          <div className="acr-step__main">
            <div className="acr-step__row">
              <span className="acr-step__title">{s.title}</span>
              <span className="acr-step__status">{s.statusLabel}</span>
            </div>
            {s.detail && <div className="acr-step__detail">{s.detail}</div>}
            {s.meta && <div className="acr-step__meta acr-num">{s.meta}</div>}
            {s.children}
          </div>
        </li>
      ))}
    </ol>
  );
}
