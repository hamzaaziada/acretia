import { useEffect, useRef } from 'react';
import { api } from '../../api/client';

/* ---------- citations ---------- */

export interface CitationPreview {
  token: string;
  doc_id: string | null;
  deal_id: string | null;
  doc_name: string;
  page: number | null;
  /** [x0, y0, x1, y1] in 0..1, origin top-left. */
  bbox_norm: number[] | null;
  quote: string;
  context_before?: string;
  context_after?: string;
  url: string | null;
  as_of: string | null;
  xbrl_concept: string | null;
  cell_locator: string | null;
  kind: string | null;
}

const previewCache = new Map<string, Promise<CitationPreview>>();

/** Cached by token: the 0.5 s hover budget (parity 15) is met by fetching on first hover and never again. */
export function getCitationPreview(token: string): Promise<CitationPreview> {
  let p = previewCache.get(token);
  if (!p) {
    p = api.get<CitationPreview>(`/citations/${encodeURIComponent(token)}/preview`);
    previewCache.set(token, p);
    p.catch(() => previewCache.delete(token));
  }
  return p;
}

export function citationHref(c: Pick<CitationPreview, 'deal_id' | 'doc_id' | 'page' | 'token'>): string | null {
  if (!c.deal_id || !c.doc_id) return null;
  const q = new URLSearchParams();
  if (c.page) q.set('page', String(c.page));
  q.set('cite', c.token);
  return `/deals/${encodeURIComponent(c.deal_id)}/docs/${encodeURIComponent(c.doc_id)}?${q.toString()}`;
}

/* ---------- documents ---------- */

export interface DocCitation extends CitationPreview {}

export interface DocInspect {
  doc: { id: string; name: string; deal_id: string; pages: number | null; kind: string | null; lang: string | null; status: string | null };
  citation: CitationPreview | null;
  citations: CitationPreview[];
  file_url: string;
}

export interface DocSearch {
  q: string;
  total: number;
  hits: { page: number; snippet: string; at: number }[];
}

/* ---------- models ---------- */

export type CellClass = 'input' | 'calc' | 'link' | 'label' | 'header';

export interface ModelCell {
  v: number | string | boolean | null;
  f?: string;
  cls: CellClass;
  fmt?: string;
  b?: 1;
  err?: 1;
  bg?: string;
  bt?: 1;
  bb?: 1;
  ind?: number;
  note?: string;
  url?: string;
  citation_token?: string;
  xbrl_concept?: string;
}

export interface ModelSheet {
  name: string;
  rows: number;
  cols: number;
  freeze: { rows: number; cols: number };
  widths: Record<string, number>;
}

export interface Assumption {
  ref: string;
  label: string;
  row_label: string;
  sheet: string;
  section: string | null;
  period: string | null;
  value: number;
  fmt: string | null;
  unit: string;
}

export interface ModelCheck {
  name: string;
  ref: string;
  status: 'pass' | 'fail';
  value: string;
  periods?: number;
  failing?: string[];
}

export interface ModelOutput {
  ref: string;
  label: string;
  value?: number | null;
}

export interface ModelView {
  deal_id: string;
  name: string;
  version: number;
  latest: number;
  editable: boolean;
  sheets: ModelSheet[];
  cells: Record<string, ModelCell>;
  assumptions: Assumption[];
  checks: ModelCheck[];
  outputs: ModelOutput[];
  manifest?: unknown;
}

export interface RecomputeResult {
  changed: Record<string, { v_old: number | string | null; v_new: number | string | null }>;
  checks: ModelCheck[];
  ms: number;
  outputs: { ref: string; value: number | null }[];
}

export interface ExplainNode {
  cell: string;
  label: string;
  formula: string | null;
  value: number | string | null;
  range?: boolean;
  n_cells?: number;
  empty?: boolean;
  precedents?: ExplainNode[];
}

export interface Explain {
  cell: string;
  label: string;
  formula: string | null;
  value: number | string | null;
  empty?: boolean;
  precedents: ExplainNode[];
  dependents: { cell: string; label: string; formula: string | null; value: number | string | null }[];
  n_dependents?: number;
  inputs: { cell: string; label: string; value: number | string | null; source?: string | null; link?: string | null }[];
  citation_token?: string;
  note?: string | null;
}

export interface AuditItem {
  ref: string;
  label: string;
  value?: number | string | null;
  to?: string[];
  formula?: string;
}

export interface AuditSheet {
  sheet: string;
  status: 'pass' | 'warn' | 'fail';
  counts: Record<string, number>;
  n_links: number;
  n_hardcodes: number;
  n_errors: number;
  links: AuditItem[];
  hardcodes: AuditItem[];
  errors: AuditItem[];
}

export interface Audit {
  version: number;
  sheets: AuditSheet[];
  totals: { links: number; hardcodes: number; errors: number };
}

export interface AskResult {
  answer: string;
  cells: string[];
  values: unknown[];
  method: string;
  reconciled: boolean;
  cells_detail: { ref: string; label: string; value: number | string | null; fmt: string | null }[];
}

export const modelPath = (dealId: string, name: string) => `/models/${encodeURIComponent(dealId)}/${encodeURIComponent(name)}`;

export function downloadHref(dealId: string, name: string, version: number): string {
  return `/api/v1/deals/${encodeURIComponent(dealId)}/deliverables/${encodeURIComponent(name)}/versions/${version}/download`;
}

/* ---------- small hooks ---------- */

export function useLatest<T>(value: T) {
  const r = useRef(value);
  r.current = value;
  return r;
}

/** Runs `fn` after `ms` of quiet; the pending call is dropped on unmount. */
export function useDebouncedCallback<A extends unknown[]>(fn: (...a: A) => void, ms: number) {
  const fnRef = useLatest(fn);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return useRef((...a: A) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => fnRef.current(...a), ms);
  }).current;
}
