import { useEffect, useRef, useState } from 'react';
import { pdfjs } from './pdfjs';
import type { PDFDocumentProxy } from './pdfjs';

export interface Highlight {
  token: string;
  bbox: number[];
  /** Bumped to replay the pulse when the same citation is chosen again. */
  nonce: number;
}

interface Props {
  doc: PDFDocumentProxy;
  pageNumber: number;
  scale: number;
  /** Placeholder size in CSS px (from the first page until this page reports its own). */
  width: number;
  height: number;
  highlight?: Highlight | null;
  query?: string;
  /** Rendered pages report their true size so the layout can correct it. */
  onSize?: (page: number, w: number, h: number) => void;
}

const ARABIC = /[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]/;

/** One PDF page: canvas, selectable text layer, optional bbox highlight. Mounted only near the viewport. */
export function PageView({ doc, pageNumber, scale, width, height, highlight, query, onSize }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const textRef = useRef<HTMLDivElement>(null);
  const [rendered, setRendered] = useState(false);
  const onSizeRef = useRef(onSize);
  onSizeRef.current = onSize;
  const [textDone, setTextDone] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let renderTask: { cancel: () => void; promise: Promise<unknown> } | null = null;
    let textLayer: { cancel: () => void } | null = null;
    setRendered(false);

    (async () => {
      const page = await doc.getPage(pageNumber);
      if (cancelled) return;
      const viewport = page.getViewport({ scale });
      const base = page.getViewport({ scale: 1 });
      onSizeRef.current?.(pageNumber, base.width, base.height);
      const canvas = canvasRef.current;
      const textEl = textRef.current;
      if (!canvas || !textEl) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 3);
      canvas.width = Math.floor(viewport.width * dpr);
      canvas.height = Math.floor(viewport.height * dpr);
      canvas.style.inlineSize = `${Math.floor(viewport.width)}px`;
      canvas.style.blockSize = `${Math.floor(viewport.height)}px`;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      renderTask = page.render({ canvasContext: ctx, viewport, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined });
      try {
        await renderTask.promise;
      } catch (e) {
        if ((e as { name?: string }).name === 'RenderingCancelledException') return;
        throw e;
      }
      if (cancelled) return;
      setRendered(true);
      textEl.replaceChildren();
      textEl.style.setProperty('--scale-factor', String(viewport.scale));
      const tl = new pdfjs.TextLayer({ textContentSource: page.streamTextContent(), container: textEl, viewport });
      textLayer = tl;
      try {
        await tl.render();
      } catch {
        return;
      }
      if (cancelled) return;
      for (const s of Array.from(textEl.querySelectorAll('span'))) {
        if (ARABIC.test(s.textContent ?? '')) s.setAttribute('dir', 'rtl');
        else s.setAttribute('dir', 'auto');
      }
      setTextDone((n) => n + 1);
    })().catch(() => undefined);

    return () => {
      cancelled = true;
      renderTask?.cancel();
      textLayer?.cancel();
    };
  }, [doc, pageNumber, scale]);

  // in-document search: mark the text-layer spans that contain the query
  useEffect(() => {
    const el = textRef.current;
    if (!el) return;
    const q = (query ?? '').trim().toLowerCase();
    for (const s of Array.from(el.querySelectorAll('span'))) {
      s.classList.toggle('is-hit', q.length >= 2 && (s.textContent ?? '').toLowerCase().includes(q));
    }
  }, [query, textDone]);

  return (
    <>
      <canvas ref={canvasRef} className="pdfv__canvas" aria-hidden="true" />
      <div ref={textRef} className="textLayer pdfv__text" dir="auto" style={{ inlineSize: width, blockSize: height }} />
      {highlight && (
        <div
          key={`${highlight.token}:${highlight.nonce}`}
          data-testid="bbox-highlight"
          data-page={pageNumber}
          data-token={highlight.token}
          className="pdfv__bbox"
          style={{
            insetInlineStart: `${highlight.bbox[0] * 100}%`,
            insetBlockStart: `${highlight.bbox[1] * 100}%`,
            inlineSize: `${Math.max(0.4, (highlight.bbox[2] - highlight.bbox[0]) * 100)}%`,
            blockSize: `${Math.max(0.4, (highlight.bbox[3] - highlight.bbox[1]) * 100)}%`,
          }}
        />
      )}
      {!rendered && <div className="pdfv__pageskel" aria-hidden="true" />}
    </>
  );
}
