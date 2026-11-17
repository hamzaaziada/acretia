/** Wire types mirroring docs/product/SPEC.md sections 3, 4 and 5. No `any`. */

export type Role = 'owner' | 'member' | 'viewer';
export const ROLE_RANK: Record<Role, number> = { viewer: 0, member: 1, owner: 2 };

export interface User {
  id: string;
  email: string;
  name: string;
  locale: string;
}

export interface Org {
  id: string;
  name: string;
  slug: string;
  locale?: string;
}

export interface OrgMembership {
  id: string;
  name: string;
  slug?: string;
  role?: Role;
}

export interface Me {
  user: User;
  org: Org;
  role: Role;
  orgs: OrgMembership[];
  csrf_token: string;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface ApiErrorBody {
  error: { code: string; message: string; hint?: string | null };
}

export interface Member {
  user_id: string;
  email: string;
  name: string;
  role: Role;
  created_at?: string;
  disabled?: boolean;
}

export type DealStatus = 'active' | 'on_hold' | 'closed' | 'archived' | string;

export interface DealCounts {
  documents?: number;
  deliverables?: number;
  jobs?: number;
}

export interface Deal {
  /** The server names the deal id `deal_id`; `normalizeDeal` mirrors it into `id` so routes never get `undefined`. */
  id: string;
  deal_id?: string;
  name: string;
  target?: string | null;
  sector?: string | null;
  status: DealStatus;
  created_by?: string | null;
  updated_at?: string | null;
  created_at?: string | null;
  counts?: DealCounts;
}

export interface DealInput {
  name: string;
  target?: string;
  sector?: string;
}

export type DocumentStatus = 'queued' | 'indexing' | 'ready' | 'failed';

export interface DocumentRow {
  id: string;
  deal_id: string;
  name: string;
  kind: string;
  sha256?: string;
  size: number;
  pages: number | null;
  status: DocumentStatus;
  progress: number | null;
  lang: string | null;
  created_at: string;
  error?: string | null;
}

export type DeliverableKind = 'xlsx' | 'pptx' | 'docx' | 'pdf' | 'grid' | 'other' | string;

export interface Deliverable {
  name: string;
  kind: DeliverableKind;
  latest_version: number;
  versions?: number;
  updated_at: string;
  deal_id?: string;
  /** Which viewer opens it: model (xlsx), deck (pptx), or none. */
  view?: 'model' | 'deck' | 'grid' | null;
}

export interface DeliverableVersion {
  version: number;
  sha256?: string;
  size?: number;
  created_at: string;
  created_by?: string | null;
  job_id?: string | null;
  note?: string | null;
  current?: boolean;
}

export interface DiffChange {
  path?: string;
  kind?: 'added' | 'removed' | 'changed' | string;
  before?: string | number | null;
  after?: string | number | null;
}

export interface DeliverableDiff {
  a: number;
  b: number;
  summary?: string;
  changes?: DiffChange[];
  lines?: string[];
}

export type JobStatus = 'queued' | 'planning' | 'running' | 'awaiting_approval' | 'done' | 'failed' | 'cancelled';
export const TERMINAL_JOB: JobStatus[] = ['done', 'failed', 'cancelled'];
export type JobSource = 'app' | 'email' | 'schedule' | 'api';
export type StepState = 'queued' | 'running' | 'done' | 'failed' | 'skipped';

export interface PlanStep {
  id: string;
  title: string;
  tool?: string;
  engine?: string;
  task?: string;
}

/** One step as `GET /jobs/{id}` reports it (checkpointed in steps_json). */
export interface JobStep {
  id: string;
  task?: string;
  title: string;
  engine?: string;
  status: 'pending' | StepState;
  detail?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  seconds?: number | null;
  tokens?: number | null;
  cost_usd?: number | null;
  error?: string | null;
  hint?: string | null;
}

export interface Job {
  id: string;
  deal_id: string | null;
  user_id?: string | null;
  agent_id: string | null;
  agent_name?: string | null;
  /** Resolved name of the deal (set once the run has created or been given one). */
  deal_name?: string | null;
  kind: string;
  prompt: string;
  status: JobStatus;
  tokens: number;
  cost_usd: number;
  started_at: string | null;
  finished_at: string | null;
  created_at?: string | null;
  error: string | null;
  source: JobSource;
  time_saved?: TimeSaved | null;
  /** Wall-clock seconds, when the server reports it. */
  wall_seconds?: number | null;
  hint?: string | null;
  resume_from?: number;
  /** Detail view only (`GET /jobs/{id}` and the POST responses). */
  plan?: { steps: PlanStep[]; estimate?: { cost_usd: number; seconds: number } } | null;
  steps?: JobStep[];
  deliverables?: Array<{ deal_id: string; name: string; version: number; kind: DeliverableKind }>;
  pending_approval?: { step_id: string; kind: string } | null;
  feedback?: { up: number; down: number };
}

/** Every job response is wrapped: `{ job }` (SPEC section 4). */
export interface JobEnvelope {
  job: Job;
}

/** Estimate (D-032). Never human-validated until `status` says so. */
export interface TimeSaved {
  /** Single-task runs. */
  task_id?: string;
  /** Multi-task runs (chains): one `TimeSaved` per task. */
  task_ids?: string[];
  per_task?: TimeSaved[];
  basis?: string;
  t_h_minutes?: { low: number; mid: number; high: number; source: string; confidence?: string } | null;
  t_a_minutes?: number | null;
  /** Fraction of the human baseline saved, at the low / mid / high baseline. */
  pct?: { low: number; mid: number; high: number } | number | null;
  status?: string;
  baseline?: string;
  error?: string;
}

export interface Citation {
  doc_id: string;
  page: number | null;
  bbox_norm?: number[] | null;
  quote: string;
  as_of?: string | null;
  url?: string | null;
  doc_name: string;
}

export interface ActivityRow {
  id?: string;
  /** Server rows: `{at, type, title, status, ref, actor}`. */
  type?: string;
  title?: string;
  status?: string;
  ref?: string;
  at: string;
  actor?: string | null;
  action?: string;
  target?: string | null;
  summary?: string | null;
}

export interface DealDetail extends Deal {
  activity?: ActivityRow[];
  instructions?: string | null;
  definitions?: Record<string, string> | null;
}

export interface JobCreate {
  prompt: string;
  deal_id?: string | null;
  agent_id?: string | null;
  inputs?: Record<string, string | number | boolean>;
}

/* ---- Job events (SPEC section 5): discriminated by `type` ---- */

export interface EventBase {
  seq?: number;
  at?: string;
}
export interface PlanEvent extends EventBase {
  type: 'plan';
  data: { steps: PlanStep[]; estimate?: { cost_usd: number; seconds: number; tokens?: number }; method?: string; tasks?: Array<{ task_id: string }> };
}
export interface StepEvent extends EventBase {
  type: 'step';
  data: {
    id: string;
    status: Exclude<StepState, 'queued'>;
    title?: string;
    detail?: string;
    started_at?: string | null;
    finished_at?: string | null;
    cost_usd?: number;
    tokens?: number;
    seconds?: number;
    engine?: string;
    error?: string | null;
    hint?: string | null;
    notes?: unknown;
  };
}
export interface SourceData {
  citation_token: string;
  doc_name: string;
  page: number | null;
  quote: string;
  url?: string | null;
  as_of?: string | null;
  doc_id?: string | null;
  kind?: string | null;
  xbrl_concept?: string | null;
}
export interface SourceEvent extends EventBase {
  type: 'source';
  data: SourceData;
}
export interface LogEvent extends EventBase {
  type: 'log';
  data: { level: 'debug' | 'info' | 'warning' | 'error'; message: string };
}
export interface ApprovalPayload {
  /** ghost_deck: slide titles to approve or edit. */
  titles?: Array<{ id: string; title: string; archetype_hint?: string }>;
  /** sources (step source_review): sources the run proposes to read. */
  sources?: Array<{ id: string; label: string; kind?: string; detail?: string; available?: boolean; task?: string }>;
  note?: string;
  slides?: Array<{ title: string; bullets?: string[] }>;
  /** assumptions: key/value rows. */
  assumptions?: Array<{ key: string; label?: string; value: string | number }>;
  [extra: string]: unknown;
}
export interface ApprovalData {
  step_id: string;
  /** `sources` is the pre-run source review (step_id `source_review`). */
  kind: 'ghost_deck' | 'assumptions' | 'sources';
  payload: ApprovalPayload;
}
export interface ApprovalEvent extends EventBase {
  type: 'approval';
  data: ApprovalData;
}
export interface DeliverableData {
  deal_id: string;
  name: string;
  version: number;
  kind: DeliverableKind;
  url: string;
  sha256?: string;
  size?: number;
  /** Deck validator summary (pptx). */
  badges?: { ok: boolean; critical: number; major: number; minor: number };
}
export interface DeliverableEvent extends EventBase {
  type: 'deliverable';
  data: DeliverableData;
}
export interface CostEvent extends EventBase {
  type: 'cost';
  data: { tokens: number; cost_usd: number };
}
export interface StatusEvent extends EventBase {
  type: 'status';
  data: {
    status: JobStatus;
    error?: string | null;
    hint?: string | null;
    step_id?: string;
    deal_id?: string | null;
    wall_seconds?: number;
    time_saved?: TimeSaved | null;
    failed_steps?: string[];
  };
}

export type JobEvent = PlanEvent | StepEvent | SourceEvent | LogEvent | ApprovalEvent | DeliverableEvent | CostEvent | StatusEvent;
export type JobEventType = JobEvent['type'];
export const JOB_EVENT_TYPES: JobEventType[] = ['plan', 'step', 'source', 'log', 'approval', 'deliverable', 'cost', 'status'];

/** `GET /api/v1/library` row: latest version of one deliverable across the org's deals. */
export interface LibraryRow {
  deal_id: string;
  deal_name: string;
  name: string;
  kind: DeliverableKind;
  latest_version: number;
  versions: number;
  size?: number;
  sha256?: string;
  note?: string | null;
  updated_at: string;
}
export interface LibraryPage extends Page<LibraryRow> {
  kinds?: string[];
}

export interface Notification {
  id: string;
  kind: string;
  title: string;
  body: string;
  link: string | null;
  created_at: string;
  read_at: string | null;
}

export interface Agent {
  id: string;
  name: string;
  description: string;
  kind: string;
  steps?: PlanStep[];
  prompt_template?: string;
  shared?: boolean;
  builtin?: boolean;
  created_at?: string;
  tags?: string[];
  /** Stable task id of a built-in agent (SPEC section 5). */
  task_id?: string;
  /** Admins can disable an agent org-wide (item 58). Absent means enabled. */
  enabled?: boolean;
  pinned?: boolean;
  prompt?: string;
  prompts?: string[];
  created_by?: string | null;
  owner_name?: string | null;
}

export interface AuditRow {
  seq: number;
  user_id: string | null;
  user_email?: string | null;
  action: string;
  target: string;
  detail?: Record<string, string | number | boolean | null> | null;
  ip?: string | null;
  at: string;
  hash?: string;
}

export interface Healthz {
  ok: boolean;
  version: string;
  llm_mode: string;
  engines: Record<string, boolean>;
}

/** Org-wide SSE (`GET /events`). */
export interface OrgEventNotification {
  kind: 'notification';
  notification: Notification;
}
export interface OrgEventJob {
  kind: 'job';
  job_id: string;
  status: JobStatus;
}
export type OrgEvent = OrgEventNotification | OrgEventJob;
