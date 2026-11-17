/** Wire types for om/api/decks.py. */

export type Status = 'pass' | 'warn' | 'fail';

export interface Badge {
  rule: string;
  severity: 'critical' | 'major' | 'minor';
  message: string;
  shape?: string | null;
}

export interface Source {
  text: string;
  citation_token: string | null;
  doc_id: string | null;
  page: number | null;
}

export interface Slide {
  n: number;
  title: string;
  png_url: string;
  outline: string[];
  sources: Source[];
  badges: Badge[];
  status: Status;
  accepted: boolean;
  key: string;
}

export interface DeckComment {
  id: string;
  slide: number;
  x: number;
  y: number;
  body: string;
  author_id: string | null;
  status: 'open' | 'applied' | 'job';
  created_at: string;
  version: number;
  applied_in_version: number | null;
  job_id: string | null;
}

export interface VersionInfo {
  version: number;
  created_at: string;
  note: string;
  size: number;
}

export interface Approval {
  job_id: string;
  step_id: string | null;
  kind: 'ghost_deck';
  payload: { titles?: string[]; slides?: { title?: string }[]; [k: string]: unknown };
}

export interface DeckPayload {
  deal_id: string;
  name: string;
  version: number;
  versions: VersionInfo[];
  slides: Slide[];
  validator: { passed: boolean; status: Status; counts: { critical: number; major: number; minor: number }; findings: { rule: string; severity: string; message: string; slide: number }[] };
  comments: DeckComment[];
  renderer: { available: boolean };
  approval: Approval | null;
  download_url: string;
}

export interface CompareSlide {
  n: number;
  status: 'changed' | 'unchanged' | 'added' | 'removed';
  title_a: string | null;
  title_b: string | null;
  text_diff: { removed: string[]; added: string[] };
}

export interface ComparePayload {
  a: number;
  b: number;
  slides: CompareSlide[];
  changed: number[];
  identical: boolean;
  png_a: string;
  png_b: string;
}

export interface ApplyResult {
  version: number | null;
  applied: string[];
  slides_changed: number[];
  jobs: { comment_id: string; job_id?: string; slide?: number; error?: string }[];
}
