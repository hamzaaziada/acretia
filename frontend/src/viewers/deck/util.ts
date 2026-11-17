import { ApiError } from '../../api/client';

export function errText(e: unknown): { title: string; hint?: string } {
  if (e instanceof ApiError) return { title: e.message || e.code, hint: e.hint ?? undefined };
  return { title: String(e) };
}

export function deckApi(dealId: string, name: string): string {
  return `/decks/${dealId}/${encodeURIComponent(name)}`;
}

export function citeUrl(dealId: string, c: { doc_id?: string | null; page?: number | null; token?: string | null }): string {
  const q = new URLSearchParams();
  if (c.page != null) q.set('page', String(c.page));
  if (c.token) q.set('cite', c.token);
  const qs = q.toString();
  return `/deals/${dealId}/docs/${c.doc_id ?? ''}${qs ? `?${qs}` : ''}`;
}
