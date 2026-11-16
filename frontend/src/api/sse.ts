import { API_BASE } from './client';

export type StreamState = 'connecting' | 'open' | 'retrying' | 'closed';

export interface StreamHandlers {
  /** Named SSE events, keyed by event name. Data is parsed JSON; `id` is the SSE event id (job event seq). */
  events: Record<string, (data: unknown, id: string) => void>;
  /** Unnamed `message` events (some servers put the type inside the JSON). */
  message?: (data: unknown, id: string) => void;
  onState?: (state: StreamState) => void;
}

function parse(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

/**
 * EventSource wrapper. The browser reconnects by itself and resends Last-Event-ID, so this only
 * reports state and parses payloads. Returns a close function.
 */
export function openStream(path: string, handlers: StreamHandlers): () => void {
  const es = new EventSource(`${API_BASE}${path}`, { withCredentials: true });
  handlers.onState?.('connecting');
  es.onopen = () => handlers.onState?.('open');
  es.onerror = () => handlers.onState?.(es.readyState === EventSource.CLOSED ? 'closed' : 'retrying');
  for (const [name, fn] of Object.entries(handlers.events)) {
    es.addEventListener(name, (e) => {
      const m = e as MessageEvent<string>;
      fn(parse(m.data), m.lastEventId);
    });
  }
  if (handlers.message) {
    const fn = handlers.message;
    es.onmessage = (e) => fn(parse(e.data), e.lastEventId);
  }
  return () => {
    es.close();
    handlers.onState?.('closed');
  };
}
