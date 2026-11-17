import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  EmptyState,
  IconChevronDown,
  IconChevronLeft,
  IconChevronRight,
  IconChevronUp,
  IconDoc,
  IconDownload,
  IconExternal,
  IconSearch,
  IconX,
  IconPlus,
  ProgressBar,
  SplitPane,
  IconButton,
  Skeleton,
  isTypingTarget,
} from '../../ds';
import { api } from '../../api/client';
import { useResource } from '../../api/hooks';
import { useI18n } from '../../i18n';
import { CitationPopoverHost } from '../shared/CitationPopover';
import { getCitationPreview } from '../shared/api';
import type { CitationPreview, DocInspect, DocSearch } from '../shared/api';
import { Inspector } from './Inspector';
import { PageView } from './PageView';
import type { Highlight } from './PageView';
import { openPdf } from './pdfjs';
import type { PDFDocumentProxy } from './pdfjs';
import './pdf.css';

const GAP = 14;
const PAD = 18;
const OVERSCAN = 2;
const CSS_UNITS = 96 / 72; // "100%" means what Acrobat means by it
const STEPS = [50, 75, 100, 125, 150, 200, 300];

type Zoom = 'width' | 'page' | number;

function useSize(ref: React.RefObject<HTMLElement>) {
  const [size, setSize] = useState({ w: 800, h: 600 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, [ref]);
  return size;
}

export default function PdfViewerPage() {
  const { id: dealId, docId = '' } = useParams();
  const { t } = useI18n();
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const firstCite = useRef(sp.get('cite'));
  const info = useResource<DocInspect>(
    (signal) => api.get<DocInspect>(`/documents/${encodeURIComponent(docId)}/inspect`, { signal, query: { cite: firstCite.current } }),
    [docId],
  );

  return (
    <div className="pdfv" data-testid="pdf-viewer">
      <CitationPopoverHost />
      {info.loading && !info.data && <PdfSkeleton label={t('viewers.pdf.loading')} />}
      {info.error && (
        <div className="pdfv__center">
          <EmptyState
            icon={<IconDoc size={22} />}
            title={info.error.status === 404 ? t('viewers.pdf.notfound') : t('viewers.pdf.error')}
            body={info.error.hint ?? info.error.message ?? t('viewers.pdf.errorBody')}
            action={{ label: t('viewers.pdf.back'), onClick: () => nav(dealId ? `/deals/${encodeURIComponent(dealId)}` : '/') }}
            secondary={info.error.status === 404 ? undefined : { label: t('viewers.retry'), onClick: info.reload }}
          />
        </div>
      )}
      {info.data && <Viewer info={info.data} sp={sp} setSp={setSp} dealId={dealId} />}
    </div>
  );
}

function PdfSkeleton({ label }: { label: string }) {
  return (
    <div className="pdfv__skel" role="status" aria-label={label}>
      <div className="pdfv__skelpage">
        <Skeleton width="55%" height={18} />
        <Skeleton height={12} />
        <Skeleton height={12} />
        <Skeleton width="80%" height={12} />
        <Skeleton height={120} />
        <Skeleton height={12} />
        <Skeleton width="65%" height={12} />
      </div>
    </div>
  );
}

function Viewer({ info, sp, setSp, dealId }: { info: DocInspect; sp: URLSearchParams; setSp: (p: URLSearchParams, o?: { replace?: boolean }) => void; dealId?: string }) {
  const { t, fmt } = useI18n();
  const scrollRef = useRef<HTMLDivElement>(null);
  const { w: cw, h: ch } = useSize(scrollRef);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(0);
  const [zoom, setZoom] = useState<Zoom>('width');
  const [scrollTop, setScrollTop] = useState(0);
  const [sizes, setSizes] = useState<Record<number, [number, number]>>({});
  const [base, setBase] = useState<[number, number]>([612, 792]);
  const [citeNonce, setCiteNonce] = useState(0);
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<DocSearch | null>(null);
  const [hitIdx, setHitIdx] = useState(0);
  const searchRef = useRef<HTMLInputElement>(null);
  const [pageInput, setPageInput] = useState('1');
  const anchor = useRef<{ page: number; frac: number } | null>(null);

  const total = pdf?.numPages ?? info.doc.pages ?? 0;
  const citeToken = sp.get('cite');
  const [fallbackCite, setFallbackCite] = useState<CitationPreview | null>(null);
  const current = useMemo<CitationPreview | null>(() => {
    if (!citeToken) return null;
    return info.citations.find((c) => c.token === citeToken) ?? (info.citation?.token === citeToken ? info.citation : null) ?? fallbackCite;
  }, [citeToken, info, fallbackCite]);

  useEffect(() => {
    setFallbackCite(null);
    if (!citeToken || info.citations.some((c) => c.token === citeToken) || info.citation?.token === citeToken) return;
    let live = true;
    getCitationPreview(citeToken).then((c) => live && setFallbackCite(c), () => undefined);
    return () => {
      live = false;
    };
  }, [citeToken, info]);

  /* ----- load the pdf ----- */
  useEffect(() => {
    setLoadErr(null);
    setPdf(null);
    const task = openPdf(info.file_url, setProgress);
    let live = true;
    task.promise.then(
      async (d) => {
        if (!live) return;
        const p1 = await d.getPage(1);
        const v = p1.getViewport({ scale: 1 });
        if (!live) return;
        setBase([v.width, v.height]);
        setPdf(d);
      },
      (e: unknown) => live && setLoadErr((e as { message?: string })?.message ?? 'load'),
    );
    return () => {
      live = false;
      void task.destroy();
    };
  }, [info.file_url]);

  /* ----- geometry ----- */
  const fitW = Math.max(0.2, (cw - 2 * PAD - 2) / base[0]);
  const fitP = Math.max(0.2, Math.min(fitW, (ch - 2 * PAD) / base[1]));
  const scale = zoom === 'width' ? fitW : zoom === 'page' ? fitP : (zoom / 100) * CSS_UNITS;
  const pct = Math.round((scale / CSS_UNITS) * 100);
  const pageW = (n: number) => (sizes[n]?.[0] ?? base[0]) * scale;
  const pageH = (n: number) => (sizes[n]?.[1] ?? base[1]) * scale;
  const offsets = useMemo(() => {
    const o: number[] = [];
    let y = PAD;
    for (let n = 1; n <= total; n++) {
      o.push(y);
      y += (sizes[n]?.[1] ?? base[1]) * scale + GAP;
    }
    o.push(y - GAP + PAD);
    return o;
  }, [total, sizes, base, scale]);
  const sheetW = Math.max(cw, Math.max(base[0], ...Object.values(sizes).map((s) => s[0])) * scale + 2 * PAD);

  const pageAt = useCallback(
    (y: number) => {
      let lo = 0;
      let hi = Math.max(0, total - 1);
      while (lo < hi) {
        const mid = (lo + hi + 1) >> 1;
        if (offsets[mid] <= y) lo = mid;
        else hi = mid - 1;
      }
      return lo + 1;
    },
    [offsets, total],
  );
  const first = Math.max(1, pageAt(scrollTop) - OVERSCAN);
  const last = Math.min(total, pageAt(scrollTop + ch) + OVERSCAN);
  const currentPage = total ? pageAt(scrollTop + ch * 0.3) : 1;

  useEffect(() => {
    setPageInput(String(currentPage));
  }, [currentPage]);

  const goPage = useCallback(
    (n: number, yFrac = 0, center = false) => {
      const el = scrollRef.current;
      if (!el || !total) return;
      const p = Math.max(1, Math.min(total, Math.round(n)));
      const top = offsets[p - 1] + yFrac * pageH(p) - (center ? ch * 0.28 : PAD);
      el.scrollTo({ top: Math.max(0, top) });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [offsets, total, ch, scale],
  );

  /* ----- keep position when the scale changes ----- */
  useLayoutEffect(() => {
    const a = anchor.current;
    const el = scrollRef.current;
    if (!a || !el || !total) return;
    anchor.current = null;
    el.scrollTop = Math.max(0, offsets[a.page - 1] + a.frac * pageH(a.page) - PAD);
    setScrollTop(el.scrollTop);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scale]);

  function setZoomKeep(z: Zoom) {
    const el = scrollRef.current;
    if (el && total) {
      const p = pageAt(el.scrollTop + PAD);
      anchor.current = { page: p, frac: Math.max(0, (el.scrollTop + PAD - offsets[p - 1]) / pageH(p)) };
    }
    setZoom(z);
  }
  function step(dir: 1 | -1) {
    const idx = STEPS.findIndex((s) => s > pct + 1);
    const next = dir === 1 ? STEPS[idx === -1 ? STEPS.length - 1 : idx] : [...STEPS].reverse().find((s) => s < pct - 1) ?? STEPS[0];
    setZoomKeep(next);
  }

  /* ----- scroll to the cited span ----- */
  const navKey = `${current?.token ?? ''}:${sp.get('page') ?? ''}:${pdf ? 1 : 0}`;
  const doneKey = useRef('');
  useEffect(() => {
    if (!pdf || !scrollRef.current || doneKey.current === navKey) return;
    const pg = current?.page ?? Number(sp.get('page') ?? 0);
    if (!pg) {
      doneKey.current = navKey;
      return;
    }
    doneKey.current = navKey;
    const b = current?.bbox_norm;
    goPage(pg, b ? b[1] : 0, !!b);
    setCiteNonce((n) => n + 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navKey, pdf, offsets]);

  const highlight: (Highlight & { page: number }) | null = current?.bbox_norm && current.page ? { token: current.token, bbox: current.bbox_norm, nonce: citeNonce, page: current.page } : null;

  /* ----- in-document search (server text index, instant) ----- */
  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setHits(null);
      return;
    }
    const ctl = new AbortController();
    const timer = window.setTimeout(() => {
      api.get<DocSearch>(`/documents/${encodeURIComponent(info.doc.id)}/search`, { query: { q }, signal: ctl.signal }).then(
        (r) => {
          setHits(r);
          setHitIdx(0);
          if (r.hits[0]) goPage(r.hits[0].page);
        },
        () => undefined,
      );
    }, 260);
    return () => {
      window.clearTimeout(timer);
      ctl.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, info.doc.id]);

  function hitStep(d: 1 | -1) {
    if (!hits?.hits.length) return;
    const n = (hitIdx + d + hits.hits.length) % hits.hits.length;
    setHitIdx(n);
    goPage(hits.hits[n].page);
  }

  /* ----- keyboard ----- */
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (isTypingTarget(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === '[') goPage(currentPage - 1);
      else if (e.key === ']') goPage(currentPage + 1);
      else if (e.key === '+' || e.key === '=') step(1);
      else if (e.key === '-') step(-1);
      else if (e.key === '/') {
        e.preventDefault();
        searchRef.current?.focus();
      } else return;
      if (e.key !== '/') e.preventDefault();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  function select(c: CitationPreview) {
    const n = new URLSearchParams(sp);
    n.set('cite', c.token);
    if (c.page) n.set('page', String(c.page));
    setSp(n, { replace: true });
  }

  const sourceUrl = current?.url && /^https?:\/\//i.test(current.url) ? current.url : null;

  const pdfPane = (
    <div className="pdfv__pane">
      <div className="pdfv__toolbar" role="toolbar" aria-label={t('viewers.pdf.toolbar')}>
        <div className="pdfv__group">
          <IconButton aria-label={t('viewers.pdf.prev')} size="sm" onClick={() => goPage(currentPage - 1)} disabled={currentPage <= 1}>
            <IconChevronUp size={15} />
          </IconButton>
          <label className="pdfv__pageinput">
            <span className="acr-sr-only">{t('viewers.pdf.goto')}</span>
            <input
              inputMode="numeric"
              value={pageInput}
              onChange={(e) => setPageInput(e.target.value.replace(/\D/g, ''))}
              onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
                if (e.key === 'Enter' && pageInput) goPage(Number(pageInput));
              }}
              onBlur={() => setPageInput(String(currentPage))}
              className="acr-num"
              data-testid="pdf-page-input"
            />
            <span className="pdfv__of acr-num">/ {fmt.integer(total)}</span>
          </label>
          <IconButton aria-label={t('viewers.pdf.next')} size="sm" onClick={() => goPage(currentPage + 1)} disabled={currentPage >= total}>
            <IconChevronDown size={15} />
          </IconButton>
        </div>
        <div className="pdfv__group">
          <IconButton aria-label={t('viewers.pdf.zoomOut')} size="sm" onClick={() => step(-1)}>
            <span aria-hidden="true" className="pdfv__glyph">
              {'−'}
            </span>
          </IconButton>
          <select
            aria-label={t('viewers.pdf.zoom')}
            className="pdfv__zoom acr-num"
            value={zoom === 'width' || zoom === 'page' ? zoom : String(zoom)}
            onChange={(e) => setZoomKeep(e.target.value === 'width' || e.target.value === 'page' ? e.target.value : Number(e.target.value))}
          >
            <option value="width">{t('viewers.pdf.fitWidth')}</option>
            <option value="page">{t('viewers.pdf.fitPage')}</option>
            {STEPS.map((s) => (
              <option key={s} value={s}>
                {s}%
              </option>
            ))}
          </select>
          <span className="pdfv__pct acr-num" aria-hidden="true">
            {pct}%
          </span>
          <IconButton aria-label={t('viewers.pdf.zoomIn')} size="sm" onClick={() => step(1)}>
            <IconPlus size={14} />
          </IconButton>
        </div>
        <div className="pdfv__search">
          <IconSearch size={14} aria-hidden="true" />
          <input
            ref={searchRef}
            type="search"
            value={query}
            placeholder={t('viewers.pdf.search')}
            aria-label={t('viewers.pdf.search')}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') hitStep(e.shiftKey ? -1 : 1);
              else if (e.key === 'Escape') {
                setQuery('');
                e.currentTarget.blur();
              }
            }}
            dir="auto"
            data-testid="pdf-search"
          />
          {hits && (
            <span className="pdfv__hits acr-num" aria-live="polite">
              {hits.hits.length ? `${fmt.integer(hitIdx + 1)} / ${fmt.integer(hits.hits.length)}` : t('viewers.pdf.nohits')}
            </span>
          )}
          {hits && hits.hits.length > 1 && (
            <>
              <IconButton aria-label={t('viewers.pdf.prevHit')} size="sm" onClick={() => hitStep(-1)}>
                <IconChevronLeft size={13} />
              </IconButton>
              <IconButton aria-label={t('viewers.pdf.nextHit')} size="sm" onClick={() => hitStep(1)}>
                <IconChevronRight size={13} />
              </IconButton>
            </>
          )}
          {query && (
            <IconButton aria-label={t('viewers.pdf.clear')} size="sm" onClick={() => setQuery('')}>
              <IconX size={12} />
            </IconButton>
          )}
        </div>
        <div className="pdfv__group pdfv__group--end">
          <a className="acr-btn acr-btn--ghost acr-btn--sm" href={info.file_url} download={info.doc.name} data-testid="pdf-download">
            <IconDownload size={14} />
            <span className="acr-btn__label">{t('viewers.pdf.download')}</span>
          </a>
          {sourceUrl && (
            <a className="acr-btn acr-btn--ghost acr-btn--sm" href={sourceUrl} target="_blank" rel="noopener noreferrer" data-testid="pdf-open-source">
              <IconExternal size={14} />
              <span className="acr-btn__label">{t('viewers.pdf.openSource')}</span>
            </a>
          )}
        </div>
      </div>

      <div
        ref={scrollRef}
        className="pdfv__scroll"
        dir="ltr"
        tabIndex={0}
        role="document"
        aria-label={info.doc.name}
        onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
      >
        {!pdf && !loadErr && (
          <div className="pdfv__loading" role="status">
            <ProgressBar value={progress == null ? null : progress * 100} label={t('viewers.pdf.loading')} />
            <p>{t('viewers.pdf.loading')}</p>
          </div>
        )}
        {loadErr && (
          <div className="pdfv__center">
            <EmptyState
              icon={<IconDoc size={22} />}
              title={t('viewers.pdf.error')}
              body={t('viewers.pdf.errorBody')}
              action={{ label: t('viewers.pdf.download'), onClick: () => window.open(info.file_url, '_blank', 'noopener,noreferrer') }}
              secondary={dealId ? { label: t('viewers.pdf.back'), onClick: () => window.history.back() } : undefined}
            />
          </div>
        )}
        {pdf && (
          <div className="pdfv__sheet" style={{ blockSize: offsets[total] ?? 0, inlineSize: sheetW }}>
            {Array.from({ length: total }, (_, i) => i + 1).map((n) => {
              const w = pageW(n);
              const h = pageH(n);
              const live = n >= first && n <= last;
              return (
                <div
                  key={n}
                  className="pdfv__page"
                  data-testid="pdf-page"
                  data-page={n}
                  data-rendered={live ? 'true' : 'false'}
                  style={{ insetBlockStart: offsets[n - 1], insetInlineStart: (sheetW - w) / 2, inlineSize: w, blockSize: h }}
                  role="img"
                  aria-label={t('viewers.pdf.pageLabel', { n })}
                >
                  {live ? (
                    <PageView
                      doc={pdf}
                      pageNumber={n}
                      scale={scale}
                      width={w}
                      height={h}
                      highlight={highlight && highlight.page === n ? highlight : null}
                      query={query}
                      onSize={(p, pw, ph) =>
                        setSizes((s) => {
                          const o = s[p];
                          if (o && Math.abs(o[0] - pw) < 0.5 && Math.abs(o[1] - ph) < 0.5) return s;
                          if (!o && Math.abs(base[0] - pw) < 0.5 && Math.abs(base[1] - ph) < 0.5) return s;
                          return { ...s, [p]: [pw, ph] };
                        })
                      }
                    />
                  ) : (
                    <span className="pdfv__pageno acr-num" aria-hidden="true">
                      {n}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );

  return (
    <div className="pdfv__main">
      <nav className="pdfv__crumbs" aria-label={t('viewers.pdf.crumbs')}>
        {dealId && (
          <>
            <Link to={`/deals/${encodeURIComponent(dealId)}`}>{t('viewers.pdf.deal')}</Link>
            <span aria-hidden="true">/</span>
          </>
        )}
        <span className="pdfv__crumbcur" dir="auto">
          {info.doc.name}
        </span>
        {current?.page != null && (
          <span className="pdfv__chip acr-num">
            {t('viewers.pdf.citedOn', { n: fmt.integer(current.page) })}
          </span>
        )}
      </nav>
      <div className="pdfv__split">
        <SplitPane
          start={pdfPane}
          end={<Inspector info={info} current={current} onSelect={select} page={currentPage} onJump={(p) => goPage(p)} />}
          initial={68}
          min={40}
          max={82}
          label={t('viewers.pdf.resize')}
        />
      </div>
    </div>
  );
}
