import { api, ApiError } from '../api/client';
import { items, useMe, useResource } from '../api/hooks';
import type { Resource } from '../api/hooks';
import type { Agent, Deliverable, Job, JobCreate, JobEnvelope, LibraryPage, Page, TimeSaved } from '../api/types';
import type { ToastInput } from '../ds';

export type SourceKey = 'deal' | 'filings' | 'firm' | 'web';
export const SOURCE_KEYS: SourceKey[] = ['deal', 'filings', 'firm', 'web'];
export const SOURCE_INPUT: Record<SourceKey, string> = { deal: 'deal_documents', filings: 'sec_filings', firm: 'firm_library', web: 'web' };

export interface Starter {
  task: string;
  titleKey: string;
  promptKey: string;
  icon: 'model' | 'grid' | 'deck' | 'doc' | 'deal' | 'history';
}

/** `task` is the built-in agent task_id (SPEC section 5). */
export const STARTERS: Starter[] = [
  { task: 'three_statement', titleKey: 'starter.model.title', promptKey: 'starter.model.prompt', icon: 'model' },
  { task: 'comps', titleKey: 'starter.comps.title', promptKey: 'starter.comps.prompt', icon: 'grid' },
  { task: 'profile', titleKey: 'starter.profile.title', promptKey: 'starter.profile.prompt', icon: 'deck' },
  { task: 'ic_memo', titleKey: 'starter.memo.title', promptKey: 'starter.memo.prompt', icon: 'doc' },
  { task: 'vdr_review', titleKey: 'starter.vdr.title', promptKey: 'starter.vdr.prompt', icon: 'deal' },
  { task: 'earnings_update', titleKey: 'starter.earnings.title', promptKey: 'starter.earnings.prompt', icon: 'history' },
];

export function viewerPath(dealId: string | null | undefined, d: { name: string; kind: string; view?: string | null }): string | null {
  if (!dealId) return null;
  const n = encodeURIComponent(d.name);
  const v = d.view ?? (d.kind === 'xlsx' ? 'model' : d.kind === 'pptx' ? 'deck' : d.kind === 'grid' ? 'grid' : null);
  if (v === 'model') return `/deals/${dealId}/models/${n}`;
  if (v === 'deck') return `/deals/${dealId}/decks/${n}`;
  if (v === 'grid') return `/deals/${dealId}/grid`;
  return null;
}

export function deliverableDownload(dealId: string, name: string, version?: number): string {
  const base = `/api/v1/deals/${dealId}/deliverables/${encodeURIComponent(name)}`;
  return `${base}/versions/${version ?? 1}/download`;
}

export function errorToast(e: unknown, title: string): ToastInput {
  if (e instanceof ApiError) return { kind: 'error', title, body: e.message || undefined, hint: e.hint ?? undefined };
  return { kind: 'error', title };
}

/** Owners also get the disabled agents back (`include_disabled=1`) so they can turn them on again. */
export function useAgents(): Resource<Agent[]> {
  const { me } = useMe();
  const owner = me?.role === 'owner';
  return useResource<Agent[]>(
    async (signal) => items(await api.get<Page<Agent> | Agent[]>('/agents', { query: { limit: 200, include_disabled: owner ? 1 : undefined }, signal })),
    [owner],
  );
}

export interface DealDeliverable extends Deliverable {
  deal_id: string;
  deal_name: string;
}

/** Org-wide library: `GET /api/v1/library` (latest version of every deliverable across the deals the caller can see). */
export function useOrgLibrary(limit = 200): Resource<DealDeliverable[]> {
  return useResource<DealDeliverable[]>(async (signal) => {
    const r = await api.get<LibraryPage>('/library', { query: { limit }, signal });
    return r.items.map((x) => ({ ...x, deal_id: x.deal_id, deal_name: x.deal_name }));
  }, [limit]);
}

export async function createJob(body: JobCreate): Promise<Job> {
  return (await api.post<JobEnvelope>('/jobs', body)).job;
}

/** Time saved as one estimate: sums per-task baselines for chains. All numbers are minutes; `null` when no credible baseline exists. */
export interface SavedEstimate {
  saved: number;
  low: number;
  high: number;
  pct: number | null;
  source: string;
}
export function savedEstimate(ts: TimeSaved | null | undefined): SavedEstimate | null {
  if (!ts) return null;
  const parts = ts.per_task && ts.per_task.length > 0 ? ts.per_task : [ts];
  let tA = 0;
  let mid = 0;
  let low = 0;
  let high = 0;
  const sources: string[] = [];
  for (const p of parts) {
    const h = p.t_h_minutes;
    if (!h || p.t_a_minutes == null) return null;
    tA += p.t_a_minutes;
    mid += h.mid;
    low += h.low;
    high += h.high;
    if (!sources.includes(h.source)) sources.push(h.source);
  }
  const pctMid = typeof ts.pct === 'number' ? ts.pct : ts.pct?.mid ?? (mid > 0 ? 1 - tA / mid : null);
  return {
    saved: Math.max(0, mid - tA),
    low: Math.max(0, low - tA),
    high: Math.max(0, high - tA),
    pct: pctMid == null ? null : pctMid > 1 ? pctMid / 100 : pctMid,
    source: sources.join('; '),
  };
}

/* ---- recent prompts (per browser) ---- */
const RECENT_KEY = 'acr.recent-prompts';
export function recentPrompts(): string[] {
  try {
    const v = JSON.parse(window.localStorage.getItem(RECENT_KEY) ?? '[]') as unknown;
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string').slice(0, 8) : [];
  } catch {
    return [];
  }
}
export function rememberPrompt(p: string) {
  try {
    const next = [p, ...recentPrompts().filter((x) => x !== p)].slice(0, 8);
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* not remembered */
  }
}

/* ---- pinned agents (per browser) ---- */
const PIN_KEY = 'acr.pinned-agents';
export function readPins(): string[] {
  try {
    const v = JSON.parse(window.localStorage.getItem(PIN_KEY) ?? '[]') as unknown;
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];
  } catch {
    return [];
  }
}
export function writePins(p: string[]) {
  try {
    window.localStorage.setItem(PIN_KEY, JSON.stringify(p));
  } catch {
    /* not remembered */
  }
}

export function statusTone(s: string): 'neutral' | 'accent' | 'positive' | 'warning' | 'negative' | 'info' {
  switch (s) {
    case 'done':
      return 'positive';
    case 'failed':
      return 'negative';
    case 'cancelled':
      return 'neutral';
    case 'awaiting_approval':
      return 'warning';
    case 'running':
    case 'planning':
      return 'accent';
    default:
      return 'info';
  }
}

export function jobDuration(j: Job): number | null {
  if (j.wall_seconds != null) return j.wall_seconds;
  if (j.started_at && j.finished_at) return (new Date(j.finished_at).getTime() - new Date(j.started_at).getTime()) / 1000;
  return null;
}
