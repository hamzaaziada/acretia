/** Wire types for om/api/grid.py. */

export type CellState = 'queued' | 'running' | 'done' | 'skipped' | 'failed';
export type ColType = 'text' | 'number' | 'date' | 'yes-no' | 'list' | 'percent' | 'currency' | 'boolean';
export type Tone = 'positive' | 'warning' | 'negative' | 'info' | 'accent';
export type Op = 'eq' | 'ne' | 'contains' | 'not_contains' | 'gt' | 'gte' | 'lt' | 'lte' | 'empty' | 'not_empty' | 'yes' | 'no';

export const OPS: Op[] = ['eq', 'ne', 'contains', 'not_contains', 'gt', 'gte', 'lt', 'lte', 'empty', 'not_empty', 'yes', 'no'];
export const NO_VALUE_OPS: Op[] = ['empty', 'not_empty', 'yes', 'no'];
export const TONES: Tone[] = ['positive', 'warning', 'negative', 'info', 'accent'];
export const COL_TYPES: ColType[] = ['text', 'number', 'date', 'yes-no', 'list'];

export interface Citation {
  token: string;
  doc_id: string;
  page: number | null;
  bbox_norm: number[] | null;
  quote: string;
}

export interface Cell {
  row: string;
  col: string;
  state: CellState;
  value: string;
  citations: Citation[];
  reason?: string | null;
  confidence?: string | null;
  error?: string | null;
  engine?: string | null;
  fmt?: { tone: Tone; rule?: string } | null;
}

export type RuleNode =
  | { op: 'and' | 'or'; children: RuleNode[] }
  | { op: Op; col?: string; value?: string | number };

export interface FormatRule {
  id?: string;
  tone: Tone;
  when: RuleNode;
}

export interface RunCondition {
  col: string;
  op: Op;
  value?: string;
}

export interface Column {
  id: string;
  position: number;
  name: string;
  prompt: string;
  type: ColType;
  depends_on: { cols: string[]; inputs: string[] };
  run_condition: RunCondition | null;
  model: string;
  format_rules: FormatRule[];
}

export interface Row {
  id: string;
  doc_id: string;
  position: number;
  name: string;
  folder: string;
}

export interface ModelInfo {
  id: string;
  label: string;
  available: boolean;
}

export interface GridPayload {
  grid: { id: string; deal_id: string; name: string; created_at: string; source_grid_id?: string | null } | null;
  columns: Column[];
  rows: Row[];
  cells: Cell[];
  inputs: Record<string, string>;
  pending: number;
  models: ModelInfo[];
  types: ColType[];
  seq?: number;
  hint?: string;
}

export interface Estimate {
  cells: number;
  est_cost_usd: number;
  est_seconds: number;
  engine: string;
}

export interface WorkflowNode {
  id: string;
  kind: 'column' | 'input';
  label: string;
  level?: number;
  type?: string;
  value?: string;
}
export interface WorkflowEdge {
  from: string;
  to: string;
  kind: 'reference' | 'condition' | 'input';
}

export interface ChatRow {
  row_id: string;
  name: string;
  folder: string;
  score: number;
  excerpt: string;
  citations: Citation[];
  columns: { column: string; value: string }[];
}
export interface ChatReply {
  answer: string;
  rows: ChatRow[];
  matched: number;
  total: number;
  seconds: number;
}

export interface Finding {
  id: string;
  type: string;
  severity: string;
  title: string;
  detail: string;
  doc_id: string | null;
  doc_name: string | null;
  page: number | null;
  quote: string;
  bbox_norm: number[] | null;
  citation_token: string | null;
}
export interface RisksPayload {
  summary: { by_type: Record<string, number>; by_severity: Record<string, number>; documents: number };
  findings: Finding[];
}

export interface DocInfo {
  id: string;
  name: string;
  full_name: string;
  folder: string;
}
export interface DocsPayload {
  documents: DocInfo[];
  folders: { name: string; count: number }[];
}

export interface TableInfo {
  n: number;
  page: number;
  n_rows: number;
  n_cols: number;
  csv_url: string;
}

export interface SplitColumn {
  name: string;
  prompt: string;
  type: ColType;
}
