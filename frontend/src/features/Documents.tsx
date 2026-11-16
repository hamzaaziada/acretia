import { useCallback, useRef, useState } from 'react';
import type { DragEvent } from 'react';
import { Link } from 'react-router-dom';
import { Badge, Button, EmptyState, IconAlert, IconCheck, IconUpload, ProgressBar, SkeletonRows, Table, useToast } from '../ds';
import type { Column } from '../ds';
import { api, ApiError, uploadFile } from '../api/client';
import { items, useOrgEvents, useResource } from '../api/hooks';
import type { DocumentRow, Page } from '../api/types';
import { useI18n } from '../i18n';

type UState = 'queued' | 'uploading' | 'done' | 'failed';
interface UploadItem {
  key: number;
  file: File;
  path: string;
  state: UState;
  pct: number;
  error?: string;
  hint?: string;
}

/* Read dropped folders recursively (webkitGetAsEntry). */
interface FsEntry {
  isFile: boolean;
  isDirectory: boolean;
  fullPath: string;
  file?: (cb: (f: File) => void, err: (e: unknown) => void) => void;
  createReader?: () => { readEntries: (cb: (e: FsEntry[]) => void, err: (e: unknown) => void) => void };
}
async function walk(entry: FsEntry, out: Array<{ file: File; path: string }>) {
  if (entry.isFile && entry.file) {
    const f = await new Promise<File>((res, rej) => entry.file!(res, rej));
    out.push({ file: f, path: entry.fullPath.replace(/^\//, '') });
  } else if (entry.isDirectory && entry.createReader) {
    const reader = entry.createReader();
    for (;;) {
      const batch = await new Promise<FsEntry[]>((res, rej) => reader.readEntries(res, rej));
      if (batch.length === 0) break;
      for (const e of batch) await walk(e, out);
    }
  }
}

const CONCURRENCY = 3;

export function DocumentsTab({ dealId }: { dealId: string }) {
  const { t, fmt } = useI18n();
  const toast = useToast();
  const docs = useResource<DocumentRow[]>(async (signal) => items(await api.get<Page<DocumentRow> | DocumentRow[]>(`/deals/${dealId}/documents`, { query: { limit: 200 }, signal })), [dealId]);
  useOrgEvents((e) => {
    if (e.name === 'document') docs.reload();
  });
  const [queue, setQueue] = useState<UploadItem[]>([]);
  const [over, setOver] = useState(false);
  const seq = useRef(0);
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const running = useRef(0);
  const pending = useRef<number[]>([]);
  const queueRef = useRef<UploadItem[]>([]);

  const patch = useCallback((key: number, p: Partial<UploadItem>) => {
    queueRef.current = queueRef.current.map((x) => (x.key === key ? { ...x, ...p } : x));
    setQueue(queueRef.current);
  }, []);

  const pump = useCallback(() => {
    while (running.current < CONCURRENCY && pending.current.length) {
      const key = pending.current.shift() as number;
      const it = queueRef.current.find((x) => x.key === key);
      if (!it) continue;
      running.current += 1;
      patch(key, { state: 'uploading', pct: 0, error: undefined, hint: undefined });
      uploadFile<unknown>(`/deals/${dealId}/documents`, it.file, (pct) => patch(key, { pct }))
        .then(() => patch(key, { state: 'done', pct: 100 }))
        .catch((e: unknown) => {
          const err = e instanceof ApiError ? e : null;
          patch(key, { state: 'failed', error: err?.message || t('docs.upload.failed'), hint: err?.hint ?? t('docs.upload.failedHint') });
          toast.push({ kind: 'error', title: t('docs.upload.failedNamed', { name: it.file.name }), body: err?.message || undefined, hint: err?.hint ?? t('docs.upload.failedHint') });
        })
        .finally(() => {
          running.current -= 1;
          docs.reload();
          pump();
        });
    }
  }, [dealId, patch, t, toast, docs]);

  const enqueue = useCallback(
    (files: Array<{ file: File; path: string }>) => {
      if (files.length === 0) return;
      const added: UploadItem[] = files.map((f) => ({ key: ++seq.current, file: f.file, path: f.path, state: 'queued', pct: 0 }));
      queueRef.current = [...queueRef.current, ...added];
      setQueue(queueRef.current);
      pending.current.push(...added.map((a) => a.key));
      pump();
    },
    [pump],
  );

  async function onDrop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    const out: Array<{ file: File; path: string }> = [];
    const its = Array.from(e.dataTransfer.items ?? []);
    const entries = its.map((i) => (i as DataTransferItem & { webkitGetAsEntry?: () => FsEntry | null }).webkitGetAsEntry?.() ?? null);
    if (entries.some(Boolean)) {
      for (const en of entries) if (en) await walk(en, out);
    } else {
      for (const f of Array.from(e.dataTransfer.files)) out.push({ file: f, path: f.name });
    }
    enqueue(out);
  }

  function retryFailed() {
    const failed = queueRef.current.filter((x) => x.state === 'failed').map((x) => x.key);
    failed.forEach((k) => patch(k, { state: 'queued', pct: 0 }));
    pending.current.push(...failed);
    pump();
  }

  const total = queue.length;
  const finished = queue.filter((x) => x.state === 'done' || x.state === 'failed').length;
  const failed = queue.filter((x) => x.state === 'failed').length;
  const overall = total ? (queue.reduce((n, x) => n + (x.state === 'done' || x.state === 'failed' ? 100 : x.pct), 0) / (total * 100)) * 100 : 0;
  const sorted = [...queue].sort((a, b) => (a.state === 'failed' ? -1 : 0) - (b.state === 'failed' ? -1 : 0));

  const columns: Column<DocumentRow>[] = [
    { key: 'name', header: t('docs.name'), sortValue: (d) => d.name, render: (d) => <span className="acr-strong">{d.name}</span> },
    {
      key: 'status',
      header: t('docs.status'),
      sortValue: (d) => d.status,
      render: (d) => (
        <span className="acr-row">
          <Badge tone={d.status === 'ready' ? 'positive' : d.status === 'failed' ? 'negative' : 'accent'} dot>
            {t(`docs.status.${d.status}`)}
          </Badge>
          {d.status === 'indexing' && d.progress != null && <span className="acr-num acr-faint">{fmt.integer(d.progress)}%</span>}
          {d.status === 'failed' && d.error && <span className="acr-faint acr-truncate">{d.error}</span>}
        </span>
      ),
    },
    { key: 'pages', header: t('docs.pages'), numeric: true, sortValue: (d) => d.pages, render: (d) => (d.pages == null ? '—' : fmt.integer(d.pages)) },
    { key: 'lang', header: t('docs.lang'), sortValue: (d) => d.lang, render: (d) => (d.lang ? d.lang.toUpperCase() : '—') },
    { key: 'kind', header: t('docs.type'), sortValue: (d) => d.kind, render: (d) => d.kind },
    { key: 'size', header: t('docs.size'), numeric: true, sortValue: (d) => d.size, render: (d) => `${fmt.number(d.size / 1024, { maximumFractionDigits: 0 })} KB` },
    {
      key: 'open',
      header: '',
      render: (d) =>
        d.status === 'ready' ? (
          <Link to={`/deals/${dealId}/docs/${d.id}`} className="acr-linkbtn" data-testid="doc-open" onClick={(e) => e.stopPropagation()}>
            {t('common.open')}
          </Link>
        ) : null,
    },
  ];

  return (
    <div className="acr-stack acr-stack--lg">
      <div
        className={`acr-dropzone${over ? ' is-over' : ''}`}
        data-testid="upload-dropzone"
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
      >
        <IconUpload size={22} />
        <div>
          <strong>{t('docs.drop.title')}</strong>
          <div className="acr-muted">{t('docs.drop.body')}</div>
        </div>
        <div className="acr-row">
          <Button variant="primary" onClick={() => fileInput.current?.click()}>
            {t('docs.chooseFiles')}
          </Button>
          <Button variant="secondary" onClick={() => folderInput.current?.click()}>
            {t('docs.chooseFolder')}
          </Button>
        </div>
        <input
          ref={fileInput}
          type="file"
          multiple
          hidden
          data-testid="upload-input"
          aria-label={t('docs.chooseFiles')}
          onChange={(e) => {
            enqueue(Array.from(e.target.files ?? []).map((f) => ({ file: f, path: f.name })));
            e.target.value = '';
          }}
        />
        <input
          ref={folderInput}
          type="file"
          hidden
          aria-label={t('docs.chooseFolder')}
          {...({ webkitdirectory: '', directory: '' } as Record<string, string>)}
          onChange={(e) => {
            enqueue(Array.from(e.target.files ?? []).map((f) => ({ file: f, path: (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name })));
            e.target.value = '';
          }}
        />
      </div>

      {total > 0 && (
        <section className="acr-uploads" aria-label={t('docs.uploads')} data-testid="upload-progress" data-total={total} data-done={finished}>
          <div className="acr-uploads__head">
            <strong className="acr-num">{t('docs.uploads.summary', { done: fmt.integer(finished), total: fmt.integer(total) })}</strong>
            {failed > 0 && (
              <span className="acr-uploads__fail">
                <IconAlert size={14} /> {t('docs.uploads.failed', { n: fmt.integer(failed) })}
                <Button size="sm" variant="secondary" onClick={retryFailed}>
                  {t('docs.uploads.retry')}
                </Button>
              </span>
            )}
          </div>
          <ProgressBar value={overall} label={t('docs.uploads.overall')} tone={failed > 0 ? 'negative' : 'accent'} />
          <ul className="acr-uploads__list">
            {sorted.map((u) => (
              <li key={u.key} className={`acr-uploads__row is-${u.state}`} data-status={u.state}>
                <span className="acr-uploads__name acr-truncate" title={u.path}>
                  {u.path}
                </span>
                <span className="acr-uploads__state">
                  {u.state === 'done' && <IconCheck size={13} />}
                  {u.state === 'failed' ? <span className="acr-uploads__err">{u.error} {u.hint}</span> : t(`docs.upload.${u.state}`)}
                </span>
                <span className="acr-num acr-faint">{u.state === 'uploading' ? `${fmt.integer(u.pct)}%` : ''}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {docs.loading && !docs.data ? (
        <SkeletonRows rows={5} label={t('common.loading')} />
      ) : (
        <Table
          caption={t('deal.tab.documents')}
          columns={columns}
          rows={docs.data ?? []}
          rowKey={(d) => d.id}
          rowProps={(d) => ({ 'data-testid': 'doc-row', 'data-id': d.id, 'data-status': d.status })}
          maxHeight={520}
          empty={<EmptyState title={t('docs.empty.title')} body={t('docs.empty.body')} action={{ label: t('docs.chooseFiles'), onClick: () => fileInput.current?.click() }} secondary={{ label: t('docs.chooseFolder'), onClick: () => folderInput.current?.click() }} />}
        />
      )}
    </div>
  );
}
