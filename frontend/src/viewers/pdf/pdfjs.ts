import * as pdfjs from 'pdfjs-dist';
import type { PDFDocumentProxy } from 'pdfjs-dist';
// Bundled by Vite and served from our own origin, so CSP `worker-src 'self' blob:` holds (no CDN, parity security bar).
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import 'pdfjs-dist/web/pdf_viewer.css';

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

export { pdfjs };
export type { PDFDocumentProxy };

export function openPdf(url: string, onProgress?: (frac: number | null) => void) {
  const task = pdfjs.getDocument({
    url,
    withCredentials: true,
    isEvalSupported: false, // no eval: keeps `script-src 'self'` free of unsafe-eval
    enableXfa: false,
  });
  if (onProgress) task.onProgress = (p: { loaded: number; total: number }) => onProgress(p.total ? p.loaded / p.total : null);
  return task;
}
