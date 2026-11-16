import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Badge, Button, Drawer, EmptyState, IconDiff, IconDownload, IconExternal, IconHistory, IconUndo, Select, SkeletonRows, Table, useToast } from '../ds';
import type { Column } from '../ds';
import { api } from '../api/client';
import { items, useResource } from '../api/hooks';
import type { Deliverable, DeliverableDiff, DeliverableVersion, Page } from '../api/types';
import { useI18n } from '../i18n';
import { deliverableDownload, errorToast, viewerPath } from '../app/lib';

export interface DeliverableRowData extends Deliverable {
  deal_id: string;
  deal_name?: string;
}

export function DeliverablesTable({ rows, showDeal, emptyAction, onChanged }: { rows: DeliverableRowData[]; showDeal?: boolean; emptyAction: { label: string; onClick: () => void }; onChanged?: () => void }) {
  const { t, fmt } = useI18n();
  const [target, setTarget] = useState<DeliverableRowData | null>(null);
  const columns: Column<DeliverableRowData>[] = [
    { key: 'name', header: t('lib.name'), sortValue: (d) => d.name, render: (d) => <span className="acr-strong">{d.name}</span> },
    { key: 'kind', header: t('lib.kind'), sortValue: (d) => d.kind, render: (d) => <Badge>{d.kind}</Badge> },
    ...(showDeal ? [{ key: 'deal', header: t('lib.deal'), sortValue: (d: DeliverableRowData) => d.deal_name ?? '', render: (d: DeliverableRowData) => <Link to={`/deals/${d.deal_id}`}>{d.deal_name ?? d.deal_id}</Link> }] : []),
    { key: 'version', header: t('lib.version'), numeric: true, sortValue: (d) => d.latest_version, render: (d) => `v${fmt.integer(d.latest_version)}` },
    { key: 'updated', header: t('lib.updated'), numeric: true, sortValue: (d) => d.updated_at, render: (d) => fmt.relative(d.updated_at) },
    {
      key: 'actions',
      header: t('common.actions'),
      render: (d) => {
        const v = viewerPath(d.deal_id, d);
        return (
          <span className="acr-rowactions">
            {v && (
              <Link to={v} className="acr-linkbtn" onClick={(e) => e.stopPropagation()}>
                <IconExternal size={13} /> {t('common.open')}
              </Link>
            )}
            <a className="acr-linkbtn" href={deliverableDownload(d.deal_id, d.name, d.latest_version)} download onClick={(e) => e.stopPropagation()}>
              <IconDownload size={13} /> {t('common.download')}
            </a>
            <button type="button" className="acr-linkbtn" onClick={(e) => { e.stopPropagation(); setTarget(d); }}>
              <IconHistory size={13} /> {t('lib.versions')}
            </button>
          </span>
        );
      },
    },
  ];
  return (
    <>
      <Table
        testId="library-table"
        caption={t('nav.library')}
        columns={columns}
        rows={rows}
        rowKey={(d) => `${d.deal_id}/${d.name}`}
        rowProps={(d) => ({ 'data-testid': 'deliverable-row', 'data-id': `${d.deal_id}/${d.name}`, 'data-kind': d.kind })}
        onRowActivate={setTarget}
        initialSort={{ key: 'updated', dir: 'desc' }}
        empty={<EmptyState title={t('lib.empty.title')} body={t('lib.empty.body')} action={emptyAction} />}
      />
      <VersionsDrawer target={target} onClose={() => setTarget(null)} onChanged={onChanged} />
    </>
  );
}

function VersionsDrawer({ target, onClose, onChanged }: { target: DeliverableRowData | null; onClose: () => void; onChanged?: () => void }) {
  const { t, fmt } = useI18n();
  const toast = useToast();
  const base = target ? `/deals/${target.deal_id}/deliverables/${encodeURIComponent(target.name)}` : '';
  const res = useResource<DeliverableVersion[]>(async (signal) => (target ? items(await api.get<Page<DeliverableVersion> | DeliverableVersion[]>(`${base}/versions`, { signal })) : []), [base]);
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  const [diff, setDiff] = useState<DeliverableDiff | null>(null);
  const [busy, setBusy] = useState(false);
  const versions = [...(res.data ?? [])].sort((x, y) => y.version - x.version);

  useEffect(() => {
    setDiff(null);
    if (versions.length >= 2) {
      setB(String(versions[0].version));
      setA(String(versions[1].version));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [res.data]);

  async function showDiff() {
    setBusy(true);
    try {
      setDiff(await api.get<DeliverableDiff>(`${base}/diff`, { query: { a, b } }));
    } catch (e) {
      toast.push(errorToast(e, t('lib.diffFailed')));
    } finally {
      setBusy(false);
    }
  }
  async function act(kind: 'undo' | 'restore', version?: number) {
    setBusy(true);
    try {
      await api.post(`${base}/${kind}`, kind === 'restore' ? { version } : {});
      toast.push({ kind: 'success', title: t(kind === 'undo' ? 'lib.undone' : 'lib.restored') });
      res.reload();
      onChanged?.();
    } catch (e) {
      toast.push(errorToast(e, t(kind === 'undo' ? 'lib.undoFailed' : 'lib.restoreFailed')));
    } finally {
      setBusy(false);
    }
  }

  const opts = versions.map((v) => ({ value: String(v.version), label: `v${v.version}` }));
  return (
    <Drawer
      testId="versions-drawer"
      open={target !== null}
      onClose={onClose}
      size="lg"
      title={target ? t('lib.versionsOf', { name: target.name }) : ''}
      closeLabel={t('common.close')}
      footer={
        <Button variant="secondary" icon={<IconUndo size={14} />} loading={busy} disabled={versions.length < 2} data-testid="undo-button" onClick={() => act('undo')}>
          {t('lib.undo')}
        </Button>
      }
    >
      {res.loading && !res.data ? (
        <SkeletonRows rows={4} label={t('common.loading')} />
      ) : (
        <>
          <ul className="acr-versions">
            {versions.map((v, i) => (
              <li key={v.version} className="acr-versions__row" data-testid="version-row" data-id={String(v.version)}>
                <span className="acr-versions__v acr-num">v{fmt.integer(v.version)}</span>
                <span className="acr-versions__main">
                  <span>{v.note || (i === 0 ? t('lib.current') : t('lib.earlier'))}</span>
                  <span className="acr-faint acr-num">
                    {fmt.dateTime(v.created_at)}
                    {v.size != null ? ` · ${fmt.number(v.size / 1024, { maximumFractionDigits: 0 })} KB` : ''}
                  </span>
                </span>
                {i === 0 && <Badge tone="accent">{t('lib.current')}</Badge>}
                <a className="acr-linkbtn" data-testid="version-download" href={deliverableDownload(target?.deal_id ?? '', target?.name ?? '', v.version)} download>
                  <IconDownload size={13} /> {t('common.download')}
                </a>
                {i !== 0 && (
                  <Button size="sm" variant="secondary" data-testid="restore-button" disabled={busy} onClick={() => act('restore', v.version)}>
                    {t('lib.restore')}
                  </Button>
                )}
              </li>
            ))}
          </ul>
          {versions.length >= 2 && (
            <section className="acr-diff" aria-label={t('lib.compare')}>
              <div className="acr-section-label">{t('lib.compare')}</div>
              <div className="acr-row acr-diff__pick">
                <Select label={t('lib.from')} options={opts} value={a} onChange={(e) => setA(e.target.value)} />
                <Select label={t('lib.to')} options={opts} value={b} onChange={(e) => setB(e.target.value)} />
                <Button variant="secondary" icon={<IconDiff size={14} />} loading={busy} data-testid="version-diff" disabled={a === b} onClick={showDiff}>
                  {t('lib.showDiff')}
                </Button>
              </div>
              {diff && (
                <div className="acr-diff__view" data-testid="diff-view">
                  {diff.summary && <p className="acr-muted">{diff.summary}</p>}
                  {(diff.changes ?? []).length === 0 && (diff.lines ?? []).length === 0 && <p className="acr-muted">{t('lib.noChanges')}</p>}
                  {(diff.changes ?? []).length > 0 && (
                    <table className="acr-table acr-diff__table">
                      <thead>
                        <tr>
                          <th scope="col">{t('lib.diff.where')}</th>
                          <th scope="col">{t('lib.diff.before')}</th>
                          <th scope="col">{t('lib.diff.after')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(diff.changes ?? []).map((c, i) => (
                          <tr key={i} className={`acr-diff__${c.kind ?? 'changed'}`}>
                            <td className="acr-mono">{c.path}</td>
                            <td className="acr-num">{c.before == null ? '—' : String(c.before)}</td>
                            <td className="acr-num">{c.after == null ? '—' : String(c.after)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  {(diff.lines ?? []).length > 0 && (
                    <pre className="acr-diff__lines">
                      {(diff.lines ?? []).map((l, i) => (
                        <div key={i} className={l.startsWith('+') ? 'is-add' : l.startsWith('-') ? 'is-del' : undefined}>
                          {l}
                        </div>
                      ))}
                    </pre>
                  )}
                </div>
              )}
            </section>
          )}
        </>
      )}
    </Drawer>
  );
}
