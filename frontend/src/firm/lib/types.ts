/** Wire types for the firm-setup endpoints (om/api/firm.py). */

export interface DefinitionItem {
  key: string;
  label: string;
  text: string;
  formula_hint: string;
  updated_by: string | null;
  updated_at: string | null;
  outdated_deals: number;
  outdated_deal_ids: string[];
}
export interface DealRef {
  deal_id: string;
  name: string;
}
export interface DefinitionsResp {
  items: DefinitionItem[];
  deals: DealRef[];
  changed?: string[];
  removed?: string[];
}
export interface ApplyResp extends DefinitionsResp {
  applied: Array<{ deal_id: string; keys: string[] }>;
}

export type AssetKind = 'template' | 'sample_deck' | 'sample_model' | 'logo';
export interface AssetStyle {
  palette: Array<{ token: string; hex: string }>;
  fonts: Record<string, string>;
  layouts: string[];
  layout_used: string;
  slide_size_in: Array<number | null>;
  sizes: Record<string, number>;
  evidence: string[];
}
export interface Asset {
  id: string;
  kind: AssetKind;
  name: string;
  size: number;
  created_at: string;
  is_default: boolean;
  file_kind: string;
  created_by: string | null;
  style: AssetStyle | null;
  style_error: string | null;
  style_hint: string | null;
}

export interface ConnectorKind {
  kind: string;
  label: string;
  fields: string[];
  required: string[];
  secret: boolean;
  local: boolean;
}
export interface Connector {
  id: string;
  kind: string;
  kind_label: string;
  name: string;
  config: Record<string, string>;
  secret: string;
  has_secret: boolean;
  status: 'new' | 'ok' | 'configured' | 'error';
  last_sync: string | null;
  item_count: number;
  bytes: number;
  last_error: string;
  permissions: 'firm' | 'mirror';
  created_at: string;
}
export interface ConnectorsResp {
  items: Connector[];
  summary: { total: number; ok: number; errors: number; never_synced: number; items: number; bytes: number; last_sync: string | null };
}
export interface TestResult {
  ok: boolean;
  status: string;
  message: string;
  hint: string;
  live: boolean;
  items: number;
  bytes: number;
  connector: Connector;
}

export interface Mailbox {
  configured: boolean;
  kind: 'imap' | 'maildir';
  host: string;
  port: number;
  username: string;
  secret: string;
  has_secret: boolean;
  folder: string;
  path: string;
  poll_seconds: number;
  allowed_senders: string[];
  send_enabled: boolean;
  status: string;
  last_poll: string | null;
}
export interface MailTest {
  ok: boolean;
  message: string;
  hint: string;
  messages: number | null;
}
export interface MailLogRow {
  id: string;
  sender: string;
  subject: string;
  outcome: 'accepted' | 'rejected' | 'error';
  reason: string;
  job_id: string | null;
  deal_id: string | null;
  attachments: number;
  at: string;
}

export interface MemoryEntry {
  id: string;
  scope: 'org' | 'deal';
  deal_id: string | null;
  text: string;
  source_kind: string;
  source_ref: string;
  source_link: string;
  created_by: string | null;
  created_at: string;
  updated_at: string | null;
  updated_by: string | null;
}

export interface MemberRef {
  user_id: string;
  name: string;
  email: string;
}
