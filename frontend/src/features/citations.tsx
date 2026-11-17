import { useEffect, useId, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { IconDoc, useToast } from '../ds';
import { api } from '../api/client';
import type { Citation, SourceData } from '../api/types';
import { useI18n } from '../i18n';
import { errorToast } from '../app/lib';

/** In-memory resolve cache: one request per token for the lifetime of the page (item 15). */
const cache = new Map<string, Promise<Citation>>();
export function resolveCitation(token: string): Promise<Citation> {
  let p = cache.get(token);
  if (!p) {
    p = api.get<Citation>(`/citations/${encodeURIComponent(token)}`);
    p.catch(() => cache.delete(token));
    cache.set(token, p);
  }
  return p;
}

export function citationHref(dealId: string, c: { doc_id: string; page: number | null }, token: string): string {
  const q = new URLSearchParams();
  if (c.page != null) q.set('page', String(c.page));
  q.set('cite', token);
  return `/deals/${dealId}/docs/${c.doc_id}?${q.toString()}`;
}

/**
 * A citation chip. Hover or focus opens a preview built from the data already streamed with the source, then
 * refined by the resolved citation. Click opens the document at the page with the span highlighted (item 16).
 */
export function CitationChip({ source, dealId }: { source: SourceData; dealId: string | null }) {
  const { t, fmt } = useI18n();
  const nav = useNavigate();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [resolved, setResolved] = useState<Citation | null>(null);
  const timer = useRef<number | null>(null);
  const id = useId();

  function show() {
    if (timer.current) window.clearTimeout(timer.current);
    setOpen(true);
    resolveCitation(source.citation_token).then(setResolved).catch(() => undefined);
  }
  function hide() {
    timer.current = window.setTimeout(() => setOpen(false), 120);
  }
  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
  }, []);

  async function go() {
    if (!dealId) {
      toast.push({ kind: 'info', title: t('cite.noDeal'), hint: t('cite.noDealHint') });
      return;
    }
    try {
      const c = resolved ?? (source.doc_id ? ({ doc_id: source.doc_id, page: source.page } as Citation) : await resolveCitation(source.citation_token));
      nav(citationHref(dealId, c, source.citation_token));
    } catch (e) {
      toast.push(errorToast(e, t('cite.openFail')));
    }
  }

  const quote = resolved?.quote || source.quote;
  const asOf = resolved?.as_of ?? source.as_of;
  const page = resolved?.page ?? source.page;
  return (
    <span className="acr-cite" onMouseEnter={show} onMouseLeave={hide}>
      <button
        type="button"
        className="acr-cite__chip"
        data-testid="source-chip"
        data-token={source.citation_token}
        aria-describedby={open ? id : undefined}
        onFocus={show}
        onBlur={hide}
        onClick={go}
      >
        <IconDoc size={12} />
        <span className="acr-cite__doc acr-truncate">{source.doc_name}</span>
        {page != null && <span className="acr-cite__page acr-num">{t('cite.page', { n: fmt.integer(page) })}</span>}
      </button>
      {open && (
        <div role="tooltip" id={id} className="acr-cite__pop" data-testid="citation-popover" onMouseEnter={show} onMouseLeave={hide}>
          <div className="acr-cite__pophead">
            <strong className="acr-truncate">{resolved?.doc_name ?? source.doc_name}</strong>
            {page != null && <span className="acr-num acr-faint">{t('cite.page', { n: fmt.integer(page) })}</span>}
          </div>
          {quote && <blockquote className="acr-cite__quote">{quote}</blockquote>}
          <div className="acr-cite__foot acr-faint">
            {asOf ? t('cite.asOf', { date: fmt.date(asOf) }) : t('cite.noAsOf')}
            <span aria-hidden="true"> · </span>
            {t('cite.clickToOpen')}
          </div>
        </div>
      )}
    </span>
  );
}
