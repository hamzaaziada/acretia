import type { ReactNode } from 'react';
import { EmptyState, IconLock } from '../../ds';
import { ApiError } from '../../api/client';
import { useMe } from '../../api/hooks';
import { useI18n } from '../../i18n';
import './firm.css';

/** True when the signed-in user may change firm settings. */
export function useIsOwner(): boolean {
  const { me } = useMe();
  return me?.role === 'owner';
}

/** Shown instead of a section when the API refuses the read (viewers) or fails. */
export function LoadError({ error, retry }: { error: ApiError; retry: () => void }) {
  const { t } = useI18n();
  if (error.status === 403)
    return <EmptyState icon={<IconLock size={22} />} title={t('firm.noAccess.title')} body={error.hint ?? t('firm.noAccess.body')} action={{ label: t('common.retry'), onClick: retry }} />;
  return <EmptyState title={t('firm.loadFailed.title')} body={error.hint ?? (error.message || t('firm.loadFailed.body'))} action={{ label: t('common.retry'), onClick: retry }} />;
}

export function ReadOnlyNote({ children }: { children: ReactNode }) {
  return (
    <p className="acr-banner acr-banner--info acr-flushbanner" data-testid="firm-readonly">
      {children}
    </p>
  );
}

/** Bytes as a short human string, numbers formatted for the active locale. */
export function sizeLabel(n: number, fmt: { number: (n: number, o?: Intl.NumberFormatOptions) => string }): string {
  if (n >= 1024 * 1024) return `${fmt.number(n / (1024 * 1024), { maximumFractionDigits: 1 })} MB`;
  if (n >= 1024) return `${fmt.number(n / 1024, { maximumFractionDigits: 0 })} KB`;
  return `${fmt.number(n)} B`;
}

export function slug(s: string): string {
  const out = s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
  return /^[a-z]/.test(out) ? out.slice(0, 48) : out ? `d_${out}`.slice(0, 48) : '';
}
