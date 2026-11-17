import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { IconDoc, IconExternal, IconGlobe, IconModel } from '../../ds';
import { useI18n } from '../../i18n';
import { citationHref, getCitationPreview } from './api';
import type { CitationPreview } from './api';
import './viewers.css';

/** The element-level contract: any element with `data-cite="<token>"` gets the preview and the click-through. */
const SELECTOR = '[data-cite]';
const OPEN_DELAY_MS = 220;
const CLOSE_DELAY_MS = 140;

/** Click → the source document at the page, with the cited span highlighted (parity 16). */
export function useCitationNavigate() {
  const navigate = useNavigate();
  return useCallback(
    async (token: string): Promise<boolean> => {
      try {
        const c = await getCitationPreview(token);
        const href = citationHref(c);
        if (href) {
          navigate(href);
          return true;
        }
        if (c.url && /^https?:\/\//.test(c.url)) {
          window.open(c.url, '_blank', 'noopener,noreferrer');
          return true;
        }
      } catch {
        /* the popover already says the source could not be loaded */
      }
      return false;
    },
    [navigate],
  );
}

let primary: symbol | null = null;

function Highlighted({ c }: { c: CitationPreview }) {
  return (
    <p className="cite-pop__ctx" dir="auto">
      {c.context_before && <span className="cite-pop__dim">{c.context_before} </span>}
      <mark className="cite-pop__mark">{c.quote}</mark>
      {c.context_after && <span className="cite-pop__dim"> {c.context_after}</span>}
    </p>
  );
}

interface Open {
  token: string;
  el: HTMLElement;
  keyboard: boolean;
}

/**
 * Mount once per page. Hover (or keyboard-focus) any `[data-cite]` element for the source preview; click opens the
 * source. Esc closes. A second mounted host stays passive, so pages and the shell can both include it safely.
 */
export function CitationPopoverHost({ navigateOnClick = true }: { navigateOnClick?: boolean }) {
  const { t, dir, fmt } = useI18n();
  const me = useRef(Symbol('host')).current;
  const [active, setActive] = useState(false);
  const [open, setOpen] = useState<Open | null>(null);
  const [data, setData] = useState<CitationPreview | null>(null);
  const [failed, setFailed] = useState(false);
  const [pos, setPos] = useState<{ start: number; top: number; above: boolean } | null>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const openTimer = useRef<number | undefined>(undefined);
  const closeTimer = useRef<number | undefined>(undefined);
  const navigateTo = useCitationNavigate();
  const id = useId();

  useEffect(() => {
    if (primary === null) primary = me;
    setActive(primary === me);
    return () => {
      if (primary === me) primary = null;
    };
  }, [me]);

  const close = useCallback(() => {
    window.clearTimeout(openTimer.current);
    window.clearTimeout(closeTimer.current);
    setOpen(null);
  }, []);

  useEffect(() => {
    if (!active) return;
    const find = (t: EventTarget | null) => (t instanceof Element ? (t.closest(SELECTOR) as HTMLElement | null) : null);
    const show = (el: HTMLElement, keyboard: boolean, delay: number) => {
      const token = el.dataset.cite;
      if (!token) return;
      window.clearTimeout(closeTimer.current);
      void getCitationPreview(token).catch(() => undefined); // prefetch while the delay runs
      window.clearTimeout(openTimer.current);
      openTimer.current = window.setTimeout(() => setOpen({ token, el, keyboard }), delay);
    };
    const hide = () => {
      window.clearTimeout(openTimer.current);
      window.clearTimeout(closeTimer.current);
      closeTimer.current = window.setTimeout(() => setOpen(null), CLOSE_DELAY_MS);
    };
    const over = (e: MouseEvent) => {
      const el = find(e.target);
      if (el) show(el, false, OPEN_DELAY_MS);
    };
    const out = (e: MouseEvent) => {
      if (find(e.target) && !(e.relatedTarget instanceof Node && popRef.current?.contains(e.relatedTarget))) hide();
    };
    const focusIn = (e: FocusEvent) => {
      const el = find(e.target);
      if (el) show(el, true, 0);
    };
    const focusOut = (e: FocusEvent) => {
      if (find(e.target)) hide();
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    const click = (e: MouseEvent) => {
      if (!navigateOnClick || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
      const el = find(e.target);
      if (!el || el.dataset.citeNav === 'off') return;
      const token = el.dataset.cite;
      if (!token) return;
      e.preventDefault();
      close();
      void navigateTo(token);
    };
    document.addEventListener('mouseover', over);
    document.addEventListener('mouseout', out);
    document.addEventListener('focusin', focusIn);
    document.addEventListener('focusout', focusOut);
    document.addEventListener('keydown', key);
    document.addEventListener('click', click);
    return () => {
      document.removeEventListener('mouseover', over);
      document.removeEventListener('mouseout', out);
      document.removeEventListener('focusin', focusIn);
      document.removeEventListener('focusout', focusOut);
      document.removeEventListener('keydown', key);
      document.removeEventListener('click', click);
      window.clearTimeout(openTimer.current);
      window.clearTimeout(closeTimer.current);
    };
  }, [active, close, navigateOnClick, navigateTo]);

  useEffect(() => {
    if (!open) return;
    let live = true;
    setData(null);
    setFailed(false);
    getCitationPreview(open.token).then(
      (c) => live && setData(c),
      () => live && setFailed(true),
    );
    open.el.setAttribute('aria-describedby', id);
    const el = open.el;
    return () => {
      live = false;
      el.removeAttribute('aria-describedby');
    };
  }, [open, id]);

  useLayoutEffect(() => {
    if (!open) {
      setPos(null);
      return;
    }
    const pop = popRef.current;
    const r = open.el.getBoundingClientRect();
    const w = pop?.offsetWidth ?? 360;
    const h = pop?.offsetHeight ?? 140;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const rtl = dir === 'rtl';
    // physical x of the popover's left edge, clamped, then expressed as an inline-start offset
    const left = Math.max(8, Math.min(vw - w - 8, rtl ? r.right - w : r.left));
    const above = r.bottom + h + 12 > vh && r.top - h - 12 > 0;
    setPos({ start: rtl ? vw - left - w : left, top: above ? r.top - h - 6 : r.bottom + 6, above });
  }, [open, data, failed, dir]);

  if (!active || !open) return null;
  const c = data;
  return createPortal(
    <div
      ref={popRef}
      id={id}
      role="tooltip"
      data-testid="citation-popover"
      data-token={open.token}
      className="cite-pop"
      style={{ insetInlineStart: pos?.start ?? 0, insetBlockStart: pos?.top ?? 0, opacity: pos ? 1 : 0 }}
      onMouseEnter={() => window.clearTimeout(closeTimer.current)}
      onMouseLeave={() => !open.keyboard && setOpen(null)}
    >
      {!c && !failed && (
        <div className="cite-pop__loading" aria-busy="true">
          <span className="acr-skeleton" style={{ inlineSize: '60%', blockSize: 12 }} />
          <span className="acr-skeleton" style={{ inlineSize: '100%', blockSize: 40 }} />
        </div>
      )}
      {failed && (
        <p className="cite-pop__err" role="alert">
          {t('viewers.cite.failed')}
        </p>
      )}
      {c && (
        <>
          <header className="cite-pop__head">
            <span className="cite-pop__icon" aria-hidden="true">
              {c.xbrl_concept ? <IconModel size={14} /> : c.doc_id ? <IconDoc size={14} /> : <IconGlobe size={14} />}
            </span>
            <span className="cite-pop__name" dir="auto">
              {c.doc_name || c.xbrl_concept || t('viewers.cite.source')}
            </span>
            {c.page != null && <span className="cite-pop__page">{t('viewers.cite.page', { n: fmt.integer(c.page) })}</span>}
          </header>
          {c.quote ? <Highlighted c={c} /> : null}
          <footer className="cite-pop__foot">
            {c.xbrl_concept && <span className="cite-pop__tag acr-mono">{c.xbrl_concept}</span>}
            {c.as_of && <span>{t('viewers.cite.asof', { date: fmt.date(c.as_of) })}</span>}
            <span className="cite-pop__hint">
              {citationHref(c) ? t('viewers.cite.open') : c.url ? t('viewers.cite.openExternal') : ''}
              {!citationHref(c) && c.url ? <IconExternal size={11} /> : null}
            </span>
          </footer>
        </>
      )}
    </div>,
    document.body,
  );
}
