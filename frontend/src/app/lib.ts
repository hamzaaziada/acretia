import { useMemo } from 'react';
import { api, ApiError } from '../api/client';
import { items, useResource } from '../api/hooks';
import type { Resource } from '../api/hooks';
import type { Agent, Deal, Deliverable, Job, JobCreate, Page } from '../api/types';
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

export function viewerPath(dealId: string, d: { name: string; kind: string; view?: string | null }): string | null {
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

export function useAgents(): Resource<Agent[]> {
  return useResource<Agent[]>(async (signal) => items(await api.get<Page<Agent> | Agent[]>('/agents', { query: { limit: 200 }, signal })), []);
}

export interface DealDeliverable extends Deliverable {
  deal_id: string;
  deal_name: string;
}

/** The Library has no org-wide endpoint in the contract, so it is assembled from each deal. */
export function useAllDeliverables(deals: Deal[] | null): Resource<DealDeliverable[]> {
  const key = useMemo(() => (deals ?? []).map((d) => d.id).join(','), [deals]);
  return useResource<DealDeliverable[]>(
    async (signal) => {
      const list = deals ?? [];
      const out = await Promise.all(
        list.map(async (d) => {
          try {
            const r = await api.get<Page<Deliverable> | Deliverable[]>(`/deals/${d.id}/deliverables`, { signal });
            return items(r).map((x) => ({ ...x, deal_id: d.id, deal_name: d.name }));
          } catch (e) {
            if (e instanceof DOMException && e.name === 'AbortError') throw e;
            return [];
          }
        }),
      );
      return out.flat().sort((a, b) => (b.updated_at ?? '').localeCompare(a.updated_at ?? ''));
    },
    [key],
  );
}

export async function createJob(body: JobCreate): Promise<Job> {
  const r = await api.post<{ job: Job } | Job>('/jobs', body);
  return 'job' in r ? r.job : r;
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
