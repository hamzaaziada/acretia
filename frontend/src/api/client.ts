import type { ApiErrorBody, Me } from './types';

export const API_BASE = '/api/v1';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly hint: string | null;
  constructor(status: number, code: string, message: string, hint: string | null = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.hint = hint;
  }
}

/**
 * Fallback message and next step when the server sent none (e.g. an unknown-route 404 or a proxy error).
 * The shell registers a translating resolver so that every catch path shows message + hint, in the user's language.
 */
export function networkError(): ApiError {
  const f = filled(0, undefined, undefined);
  return new ApiError(0, 'network_error', f.message, f.hint);
}

export type FallbackResolver = (status: number) => { message: string; hint: string } | null;
let fallback: FallbackResolver = () => null;
export function setFallbackResolver(fn: FallbackResolver) {
  fallback = fn;
}

function filled(status: number, message: string | undefined, hint: string | null | undefined): { message: string; hint: string | null } {
  const fb = !message || !hint ? fallback(status) : null;
  return { message: message || fb?.message || '', hint: hint || fb?.hint || null };
}

/** Public routes (no session, no CSRF token): calling `/auth/me` first would only add a pointless 401. */
const NO_CSRF = new Set(['/auth/login', '/auth/signup', '/auth/invites/accept']);

let csrfToken: string | null = null;
let csrfInflight: Promise<string | null> | null = null;

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

async function ensureCsrf(): Promise<string | null> {
  if (csrfToken) return csrfToken;
  if (!csrfInflight) {
    csrfInflight = fetch(`${API_BASE}/auth/me`, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(async (r) => (r.ok ? ((await r.json()) as Me).csrf_token : null))
      .catch(() => null)
      .finally(() => {
        csrfInflight = null;
      });
  }
  csrfToken = await csrfInflight;
  return csrfToken;
}

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

async function toError(res: Response): Promise<ApiError> {
  let body: Partial<ApiErrorBody> | null = null;
  try {
    body = (await res.json()) as Partial<ApiErrorBody>;
  } catch {
    body = null;
  }
  const e = body?.error;
  const f = filled(res.status, e?.message, e?.hint);
  return new ApiError(res.status, e?.code ?? `http_${res.status}`, f.message, f.hint);
}

export interface RequestOptions {
  query?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
}

function withQuery(path: string, query?: RequestOptions['query']): string {
  if (!query) return `${API_BASE}${path}`;
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== '') sp.set(k, String(v));
  const qs = sp.toString();
  return `${API_BASE}${path}${qs ? `?${qs}` : ''}`;
}

export async function request<T>(method: string, path: string, body?: unknown, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (UNSAFE.has(method) && !NO_CSRF.has(path)) {
    const tok = await ensureCsrf();
    if (tok) headers['X-CSRF-Token'] = tok;
  }
  let res: Response;
  try {
    res = await fetch(withQuery(path, opts.query), {
      method,
      credentials: 'same-origin',
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: opts.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    const f = filled(0, undefined, undefined);
    throw new ApiError(0, 'network_error', f.message, f.hint);
  }
  if (!res.ok) throw await toError(res);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>('GET', path, undefined, opts),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>('POST', path, body ?? {}, opts),
  put: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>('PUT', path, body ?? {}, opts),
  patch: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>('PATCH', path, body ?? {}, opts),
  del: <T>(path: string, opts?: RequestOptions) => request<T>('DELETE', path, undefined, opts),
};

/** Raw-body upload with progress (XHR is the only API that reports upload progress). */
export async function uploadFile<T>(path: string, file: File, onProgress: (pct: number) => void): Promise<T> {
  const tok = await ensureCsrf();
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_BASE}${path}`);
    xhr.withCredentials = true;
    xhr.setRequestHeader('Accept', 'application/json');
    xhr.setRequestHeader('X-Filename', encodeURIComponent(file.name));
    xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
    if (tok) xhr.setRequestHeader('X-CSRF-Token', tok);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress((e.loaded / e.total) * 100);
    };
    xhr.onerror = () => {
      const f = filled(0, undefined, undefined);
      reject(new ApiError(0, 'network_error', f.message, f.hint));
    };
    xhr.onload = () => {
      let parsed: unknown = null;
      try {
        parsed = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        parsed = null;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress(100);
        resolve(parsed as T);
      } else {
        const e = (parsed as Partial<ApiErrorBody> | null)?.error;
        const f = filled(xhr.status, e?.message, e?.hint);
        reject(new ApiError(xhr.status, e?.code ?? `http_${xhr.status}`, f.message, f.hint));
      }
    };
    xhr.send(file);
  });
}

export function downloadUrl(path: string): string {
  return `${API_BASE}${path}`;
}
