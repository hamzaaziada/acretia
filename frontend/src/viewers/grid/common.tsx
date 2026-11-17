import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ApiError } from '../../api/client';
import { IconLink } from '../../ds';
import type { Citation } from './types';

export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const h = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(h);
  }, [value, ms]);
  return v;
}

export function errText(e: unknown): { title: string; hint?: string } {
  if (e instanceof ApiError) return { title: e.message || e.code, hint: e.hint ?? undefined };
  return { title: String(e) };
}

/** Where a citation opens: the PDF inspector scrolled to the highlighted span (parity item 16). */
export function citeUrl(dealId: string, c: { doc_id: string | null; page: number | null; token?: string | null }): string {
  const q = new URLSearchParams();
  if (c.page != null) q.set('page', String(c.page));
  if (c.token) q.set('cite', c.token);
  const qs = q.toString();
  return `/deals/${dealId}/docs/${c.doc_id}${qs ? `?${qs}` : ''}`;
}

interface ChipProps {
  dealId: string;
  citation: Pick<Citation, 'token' | 'doc_id' | 'page'>;
  label: string;
  title?: string;
}

/** `[data-cite]` makes the shared hover preview pick it up; the click navigates to the PDF inspector. */
export function SourceChip({ dealId, citation, label, title }: ChipProps) {
  const nav = useNavigate();
  return (
    <button
      type="button"
      className="vw-chip"
      data-testid="source-chip"
      data-cite={citation.token}
      data-token={citation.token}
      title={title}
      onClick={(e) => {
        e.stopPropagation();
        nav(citeUrl(dealId, citation));
      }}
    >
      <IconLink size={11} />
      {label}
    </button>
  );
}
