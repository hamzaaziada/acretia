import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { api, ApiError, networkError, setCsrfToken } from './client';
import { openStream } from './sse';
import type { StreamState } from './sse';
import { JOB_EVENT_TYPES, TERMINAL_JOB } from './types';
import type {
  ApprovalData,
  Deal,
  DeliverableData,
  Job,
  JobEnvelope,
  JobEvent,
  JobStatus,
  Me,
  Page,
  PlanStep,
  SourceData,
  StepState,
  TimeSaved,
} from './types';

/* ---------- generic resource hook ---------- */

export interface Resource<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

export function toApiError(e: unknown): ApiError {
  return e instanceof ApiError ? e : networkError();
}

export function useResource<T>(fetcher: (signal: AbortSignal) => Promise<T>, deps: ReadonlyArray<unknown>): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const fetchRef = useRef(fetcher);
  fetchRef.current = fetcher;

  useEffect(() => {
    const ctl = new AbortController();
    setLoading(true);
    fetchRef
      .current(ctl.signal)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === 'AbortError') return;
        setError(toApiError(e));
      })
      .finally(() => {
        if (!ctl.signal.aborted) setLoading(false);
      });
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { data, error, loading, reload };
}

export function items<T>(r: Page<T> | T[] | null | undefined): T[] {
  if (!r) return [];
  return Array.isArray(r) ? r : r.items;
}

/* ---------- auth ---------- */

interface AuthValue {
  me: Me | null;
  /** True until the first /auth/me answer arrives. */
  loading: boolean;
  refresh: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  switchOrg: (orgId: string) => Promise<void>;
}

const AuthCtx = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const m = await api.get<Me>('/auth/me');
      setCsrfToken(m.csrf_token);
      setMe(m);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setCsrfToken(null);
        setMe(null);
      } else {
        throw e;
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh().catch(() => setLoading(false));
  }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    const r = await api.post<Partial<Me>>('/auth/login', { email, password });
    if (r.csrf_token) setCsrfToken(r.csrf_token);
    const m = await api.get<Me>('/auth/me');
    setCsrfToken(m.csrf_token);
    setMe(m);
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post('/auth/logout');
    } finally {
      setCsrfToken(null);
      setMe(null);
    }
  }, []);

  const switchOrg = useCallback(
    async (orgId: string) => {
      await api.post('/auth/switch-org', { org_id: orgId });
      await refresh();
    },
    [refresh],
  );

  const value = useMemo(() => ({ me, loading, refresh, login, logout, switchOrg }), [me, loading, refresh, login, logout, switchOrg]);
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useMe(): AuthValue {
  const v = useContext(AuthCtx);
  if (!v) throw new Error('AuthProvider missing');
  return v;
}

/* ---------- deals ---------- */

export function useDeals() {
  return useResource<Deal[]>(async (signal) => items(await api.get<Page<Deal> | Deal[]>('/deals', { query: { limit: 200 }, signal })), []);
}

/* ---------- job stream ---------- */

export interface RunStepState {
  id: string;
  title: string;
  status: StepState;
  detail?: string;
  started_at?: string | null;
  finished_at?: string | null;
  /** Per-step wall seconds as measured by the server (`step` events). */
  seconds?: number;
  cost_usd?: number;
  tokens?: number;
  tool?: string;
  engine?: string;
  error?: string | null;
  hint?: string | null;
}

export interface RunState {
  job: Job | null;
  plan: PlanStep[];
  estimate: { cost_usd: number; seconds: number } | null;
  steps: Record<string, RunStepState>;
  order: string[];
  sources: SourceData[];
  deliverables: DeliverableData[];
  logs: Array<{ level: string; message: string }>;
  approval: ApprovalData | null;
  cost: { tokens: number; cost_usd: number };
  status: JobStatus;
  error: string | null;
  hint: string | null;
  lastSeq: number;
  firstAt: string | null;
  /** The deal the run works in, once known (given at submit, or created by the run; arrives in `deliverable` and final `status` events). */
  dealId: string | null;
  timeSaved: TimeSaved | null;
  wallSeconds: number | null;
}

const EMPTY_RUN: RunState = {
  job: null,
  plan: [],
  estimate: null,
  steps: {},
  order: [],
  sources: [],
  deliverables: [],
  logs: [],
  approval: null,
  cost: { tokens: 0, cost_usd: 0 },
  status: 'queued',
  error: null,
  hint: null,
  lastSeq: 0,
  firstAt: null,
  dealId: null,
  timeSaved: null,
  wallSeconds: null,
};

type RunAction = { kind: 'job'; job: Job } | { kind: 'event'; ev: JobEvent } | { kind: 'clear-approval' } | { kind: 'reset' };

export function foldRun(state: RunState, action: RunAction): RunState {
  switch (action.kind) {
    case 'reset':
      return EMPTY_RUN;
    case 'clear-approval':
      return { ...state, approval: null };
    case 'job': {
      const j = action.job;
      return {
        ...state,
        job: j,
        status: state.lastSeq > 0 ? state.status : j.status,
        cost: state.lastSeq > 0 ? state.cost : { tokens: j.tokens, cost_usd: j.cost_usd },
        error: state.error ?? j.error,
        hint: state.hint ?? j.hint ?? null,
        dealId: j.deal_id ?? state.dealId,
        timeSaved: j.time_saved ?? state.timeSaved,
        wallSeconds: j.wall_seconds ?? state.wallSeconds,
      };
    }
    case 'event': {
      const ev = action.ev;
      if (ev.seq !== undefined && ev.seq <= state.lastSeq) return state;
      const base: RunState = {
        ...state,
        lastSeq: ev.seq ?? state.lastSeq,
        firstAt: state.firstAt ?? ev.at ?? null,
      };
      switch (ev.type) {
        case 'plan': {
          const steps = { ...base.steps };
          const order = ev.data.steps.map((s) => s.id);
          for (const s of ev.data.steps) {
            steps[s.id] = { ...(steps[s.id] ?? { status: 'queued' as StepState }), id: s.id, title: s.title, tool: s.tool, engine: s.engine, status: steps[s.id]?.status ?? 'queued' };
          }
          return { ...base, plan: ev.data.steps, estimate: ev.data.estimate ?? null, steps, order };
        }
        case 'step': {
          const prev = base.steps[ev.data.id];
          const merged: RunStepState = {
            id: ev.data.id,
            title: ev.data.title ?? prev?.title ?? ev.data.id,
            status: ev.data.status,
            detail: ev.data.detail ?? prev?.detail,
            started_at: ev.data.started_at ?? prev?.started_at,
            finished_at: ev.data.finished_at ?? prev?.finished_at,
            seconds: ev.data.seconds ?? prev?.seconds,
            cost_usd: ev.data.cost_usd ?? prev?.cost_usd,
            tokens: ev.data.tokens ?? prev?.tokens,
            tool: prev?.tool,
            engine: ev.data.engine ?? prev?.engine,
            error: ev.data.error ?? prev?.error,
            hint: ev.data.hint ?? prev?.hint,
          };
          const order = base.order.includes(ev.data.id) ? base.order : [...base.order, ev.data.id];
          return { ...base, steps: { ...base.steps, [ev.data.id]: merged }, order };
        }
        case 'source':
          return base.sources.some((s) => s.citation_token === ev.data.citation_token) ? base : { ...base, sources: [...base.sources, ev.data] };
        case 'log':
          return { ...base, logs: [...base.logs.slice(-199), ev.data] };
        case 'approval':
          return { ...base, approval: ev.data, status: 'awaiting_approval' };
        case 'deliverable':
          return base.deliverables.some((d) => d.name === ev.data.name && d.version === ev.data.version)
            ? base
            : { ...base, deliverables: [...base.deliverables, ev.data], dealId: base.dealId ?? ev.data.deal_id };
        case 'cost':
          return { ...base, cost: ev.data };
        case 'status':
          return {
            ...base,
            status: ev.data.status,
            error: ev.data.error ?? base.error,
            hint: ev.data.hint ?? base.hint,
            dealId: ev.data.deal_id ?? base.dealId,
            timeSaved: ev.data.time_saved ?? base.timeSaved,
            wallSeconds: ev.data.wall_seconds ?? base.wallSeconds,
            approval: ev.data.status === 'awaiting_approval' ? base.approval : null,
          };
      }
    }
  }
  return state;
}

function toEvent(type: string, data: unknown, id: string): JobEvent | null {
  if (!(JOB_EVENT_TYPES as string[]).includes(type) || typeof data !== 'object' || data === null) return null;
  const seq = Number(id);
  return { type, data, seq: Number.isFinite(seq) && id !== '' ? seq : undefined } as JobEvent;
}

export interface UseJob {
  state: RunState;
  connection: StreamState;
  elapsed: number;
  loading: boolean;
  error: ApiError | null;
  reload: () => void;
  reconnect: () => void;
  dispatchLocal: (a: { kind: 'clear-approval' }) => void;
}

export function useJob(jobId: string | undefined): UseJob {
  const [state, dispatch] = useReducer(foldRun, EMPTY_RUN);
  const [connection, setConnection] = useState<StreamState>('connecting');
  const [now, setNow] = useState(() => Date.now());
  const [epoch, setEpoch] = useState(0);
  // `GET /jobs/{id}` answers `{ job }` (SPEC section 4); the hook hands out the bare job.
  const job = useResource<Job | null>(async (signal) => (jobId ? (await api.get<JobEnvelope>(`/jobs/${jobId}`, { signal })).job : null), [jobId]);

  useEffect(() => {
    dispatch({ kind: 'reset' });
  }, [jobId]);

  useEffect(() => {
    if (job.data) dispatch({ kind: 'job', job: job.data });
  }, [job.data]);

  useEffect(() => {
    if (!jobId) return;
    let close: () => void = () => undefined;
    const feed = (type: string) => (data: unknown, id: string) => {
      const ev = toEvent(type, data, id);
      if (!ev) return;
      dispatch({ kind: 'event', ev });
      if (ev.type === 'status' && TERMINAL_JOB.includes(ev.data.status)) {
        close();
        setConnection('closed');
        job.reload();
      }
    };
    const events: Record<string, (d: unknown, id: string) => void> = {};
    for (const t of JOB_EVENT_TYPES) events[t] = feed(t);
    close = openStream(`/jobs/${jobId}/events`, {
      events,
      message: (data, id) => {
        if (typeof data === 'object' && data !== null && 'type' in data && 'data' in data) {
          const env = data as { type: string; data: unknown };
          feed(env.type)(env.data, id);
        }
      },
      onState: setConnection,
    });
    return () => close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, epoch]);

  const active = !TERMINAL_JOB.includes(state.status);
  useEffect(() => {
    if (!active) return;
    const h = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(h);
  }, [active]);

  const startIso = state.job?.started_at ?? state.firstAt ?? state.job?.created_at ?? null;
  const endIso = state.job?.finished_at ?? null;
  const start = startIso ? new Date(startIso).getTime() : null;
  const end = !active && endIso ? new Date(endIso).getTime() : now;
  const elapsed = start ? Math.max(0, (end - start) / 1000) : 0;

  const reconnect = useCallback(() => setEpoch((n) => n + 1), []);
  const dispatchLocal = useCallback((a: { kind: 'clear-approval' }) => dispatch(a), []);
  return { state, connection, elapsed, loading: job.loading, error: job.error, reload: job.reload, reconnect, dispatchLocal };
}

/* ---------- org-wide events (notifications + job status) ---------- */

type OrgListener = (ev: { name: string; data: unknown }) => void;
const OrgEventsCtx = createContext<{ subscribe: (fn: OrgListener) => () => void; unread: number; setUnread: (n: number) => void } | null>(null);

export function OrgEventsProvider({ children }: { children: ReactNode }) {
  const listeners = useRef(new Set<OrgListener>());
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    let alive = true;
    api
      .get<Page<{ id: string }> | Array<{ id: string }>>('/notifications', { query: { unread: 1, limit: 200 } })
      .then((r) => alive && setUnread(items(r).length))
      .catch(() => undefined);
    const emit = (name: string) => (data: unknown) => {
      if (name === 'notification') setUnread((n) => n + 1);
      listeners.current.forEach((fn) => fn({ name, data }));
    };
    const close = openStream('/events', {
      events: { notification: emit('notification'), job: emit('job'), status: emit('job'), document: emit('document') },
      message: (data) => emit('message')(data),
    });
    return () => {
      alive = false;
      close();
    };
  }, []);

  const subscribe = useCallback((fn: OrgListener) => {
    listeners.current.add(fn);
    return () => {
      listeners.current.delete(fn);
    };
  }, []);
  const value = useMemo(() => ({ subscribe, unread, setUnread }), [subscribe, unread]);
  return <OrgEventsCtx.Provider value={value}>{children}</OrgEventsCtx.Provider>;
}

export function useOrgEvents(listener?: OrgListener) {
  const ctx = useContext(OrgEventsCtx);
  if (!ctx) throw new Error('OrgEventsProvider missing');
  const ref = useRef(listener);
  ref.current = listener;
  const { subscribe } = ctx;
  useEffect(() => subscribe((e) => ref.current?.(e)), [subscribe]);
  return { unread: ctx.unread, setUnread: ctx.setUnread };
}
