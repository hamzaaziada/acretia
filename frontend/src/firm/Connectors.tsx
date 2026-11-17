import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Badge, Button, Dialog, EmptyState, IconPlus, Input, Panel, Select, SkeletonRows, Stat, Table, useToast } from '../ds';
import type { Column, Tone } from '../ds';
import { api } from '../api/client';
import { useResource } from '../api/hooks';
import { errorToast } from '../app/lib';
import { useI18n } from '../i18n';
import { LoadError, ReadOnlyNote, sizeLabel, useIsOwner } from './lib/shared';
import type { Connector, ConnectorKind, ConnectorsResp, TestResult } from './lib/types';
import './lib/firm.css';

const FIELD_LABEL: Record<string, string> = {
  path: 'firm.conn.field.path',
  endpoint: 'firm.conn.field.endpoint',
  bucket: 'firm.conn.field.bucket',
  prefix: 'firm.conn.field.prefix',
  region: 'firm.conn.field.region',
  access_key_id: 'firm.conn.field.access_key_id',
  drive_id: 'firm.conn.field.drive_id',
  folder: 'firm.conn.field.folder',
  folder_id: 'firm.conn.field.folder_id',
};
const KIND_LABEL: Record<string, string> = {
  local_folder: 'firm.conn.kind.local_folder',
  s3: 'firm.conn.kind.s3',
  sharepoint: 'firm.conn.kind.sharepoint',
  google_drive: 'firm.conn.kind.google_drive',
  vdr_export: 'firm.conn.kind.vdr_export',
  box: 'firm.conn.kind.box',
  dropbox: 'firm.conn.kind.dropbox',
};
const STATUS_LABEL: Record<string, string> = {
  new: 'firm.conn.status.new',
  ok: 'firm.conn.status.ok',
  configured: 'firm.conn.status.configured',
  error: 'firm.conn.status.error',
};
const STATUS_TONE: Record<string, Tone> = { new: 'neutral', ok: 'positive', configured: 'info', error: 'negative' };

export default function Connectors() {
  const { t, fmt } = useI18n();
  const toast = useToast();
  const owner = useIsOwner();
  const res = useResource<ConnectorsResp>((signal) => api.get<ConnectorsResp>('/firm/connectors', { signal }), []);
  const kinds = useResource<ConnectorKind[]>(async (signal) => (await api.get<{ items: ConnectorKind[] }>('/firm/connectors/kinds', { signal })).items, []);
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<Connector | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, TestResult>>({});

  async function test(c: Connector) {
    setTesting(c.id);
    try {
      const r = await api.post<TestResult>(`/firm/connectors/${c.id}/test`);
      setResults((x) => ({ ...x, [c.id]: r }));
      res.reload();
    } catch (e) {
      toast.push(errorToast(e, t('firm.conn.testFailed')));
    } finally {
      setTesting(null);
    }
  }
  async function remove(c: Connector) {
    try {
      await api.del(`/firm/connectors/${c.id}`);
      setRemoving(null);
      res.reload();
    } catch (e) {
      toast.push(errorToast(e, t('firm.conn.removeFailed')));
    }
  }

  if (res.error) return <LoadError error={res.error} retry={res.reload} />;
  if (!res.data) return <SkeletonRows rows={4} label={t('common.loading')} />;
  const sum = res.data.summary;
  const cols: Column<Connector>[] = [
    {
      key: 'name',
      header: t('firm.conn.name'),
      sortValue: (c) => c.name,
      render: (c) => (
        <span className="acr-strong">
          {c.name}
          {c.has_secret && (
            <div className="acr-firm__meta acr-firm-secret" aria-label={t('firm.conn.tokenSaved')}>
              {t('firm.conn.token')} {c.secret}
            </div>
          )}
          {results[c.id] && !results[c.id].ok && <div className="acr-firm-conn-err">{[results[c.id].message, results[c.id].hint].filter(Boolean).join(' ')}</div>}
          {!results[c.id] && c.status === 'error' && c.last_error && <div className="acr-firm-conn-err">{c.last_error}</div>}
        </span>
      ),
    },
    { key: 'kind', header: t('firm.conn.kind'), sortValue: (c) => c.kind, render: (c) => (KIND_LABEL[c.kind] ? t(KIND_LABEL[c.kind]) : c.kind_label) },
    { key: 'status', header: t('firm.conn.statusCol'), sortValue: (c) => c.status, render: (c) => <Badge tone={STATUS_TONE[c.status] ?? 'neutral'} dot>{t(STATUS_LABEL[c.status] ?? 'firm.conn.status.new')}</Badge> },
    { key: 'items', header: t('firm.conn.items'), numeric: true, sortValue: (c) => c.item_count, render: (c) => (c.item_count ? fmt.integer(c.item_count) : '—') },
    { key: 'bytes', header: t('firm.conn.size'), numeric: true, sortValue: (c) => c.bytes, render: (c) => (c.bytes ? sizeLabel(c.bytes, fmt) : '—') },
    { key: 'sync', header: t('firm.conn.lastSync'), numeric: true, sortValue: (c) => c.last_sync, render: (c) => (c.last_sync ? fmt.relative(c.last_sync) : t('firm.conn.never')) },
    { key: 'perm', header: t('firm.conn.permissions'), sortValue: (c) => c.permissions, render: (c) => <Badge tone={c.permissions === 'mirror' ? 'info' : 'neutral'}>{t(c.permissions === 'mirror' ? 'firm.conn.perm.mirrorShort' : 'firm.conn.perm.firmShort')}</Badge> },
    {
      key: 'actions',
      header: '',
      render: (c) =>
        owner ? (
          <span className="acr-rowactions">
            <Button size="sm" variant="secondary" loading={testing === c.id} onClick={() => test(c)} data-testid="connector-test">
              {t('firm.conn.test')}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setRemoving(c)}>
              {t('firm.conn.remove')}
            </Button>
          </span>
        ) : null,
    },
  ];
  return (
    <div className="acr-firm">
      <p className="acr-firm__intro">{t('firm.conn.intro')}</p>
      <div className="acr-firm-stats" data-testid="sources-dashboard">
        <Stat label={t('firm.conn.stat.sources')} value={fmt.integer(sum.total)} />
        <Stat label={t('firm.conn.stat.healthy')} value={fmt.integer(sum.ok)} hint={sum.errors > 0 ? t('firm.conn.stat.errors', { n: fmt.integer(sum.errors) }) : undefined} />
        <Stat label={t('firm.conn.stat.items')} value={fmt.integer(sum.items)} hint={sum.bytes ? sizeLabel(sum.bytes, fmt) : undefined} />
        <Stat label={t('firm.conn.stat.lastSync')} value={sum.last_sync ? fmt.relative(sum.last_sync) : '—'} hint={sum.never_synced > 0 ? t('firm.conn.stat.never', { n: fmt.integer(sum.never_synced) }) : undefined} />
      </div>
      <Panel
        title={t('firm.conn.title')}
        flush
        actions={
          owner ? (
            <Button size="sm" variant="primary" icon={<IconPlus size={13} />} onClick={() => setAdding(true)} data-testid="connector-add">
              {t('firm.conn.add')}
            </Button>
          ) : undefined
        }
      >
        {!owner && <ReadOnlyNote>{t('firm.ownerOnly')}</ReadOnlyNote>}
        <Table
          testId="connectors-table"
          caption={t('firm.conn.title')}
          columns={cols}
          rows={res.data.items}
          rowKey={(c) => c.id}
          rowProps={(c) => ({ 'data-id': c.id, 'data-testid': 'connector-row' })}
          empty={<EmptyState title={t('firm.conn.empty.title')} body={t('firm.conn.empty.body')} action={owner ? { label: t('firm.conn.add'), onClick: () => setAdding(true) } : { label: t('common.retry'), onClick: res.reload }} />}
        />
      </Panel>
      <AddDialog
        open={adding}
        kinds={kinds.data ?? []}
        onClose={() => setAdding(false)}
        onDone={() => {
          setAdding(false);
          res.reload();
        }}
      />
      <Dialog
        open={removing !== null}
        onClose={() => setRemoving(null)}
        title={t('firm.conn.removeTitle')}
        description={removing ? t('firm.conn.removeBody', { name: removing.name }) : ''}
        closeLabel={t('common.close')}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setRemoving(null)}>
              {t('common.cancel')}
            </Button>
            <Button variant="danger" onClick={() => removing && remove(removing)}>
              {t('firm.conn.remove')}
            </Button>
          </>
        }
      >
        <p className="acr-muted">{t('firm.conn.removeNote')}</p>
      </Dialog>
    </div>
  );
}

function AddDialog({ open, kinds, onClose, onDone }: { open: boolean; kinds: ConnectorKind[]; onClose: () => void; onDone: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const [kind, setKind] = useState('');
  const [name, setName] = useState('');
  const [cfg, setCfg] = useState<Record<string, string>>({});
  const [secret, setSecret] = useState('');
  const [perm, setPerm] = useState<'firm' | 'mirror'>('firm');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; hint: string | null } | null>(null);
  const spec = kinds.find((k) => k.kind === kind);

  useEffect(() => {
    if (open && !kind && kinds.length) setKind(kinds[0].kind);
  }, [open, kind, kinds]);
  useEffect(() => {
    setCfg({});
    setSecret('');
    setError(null);
  }, [kind]);

  function close() {
    onClose();
    setKind('');
    setName('');
    setPerm('firm');
    setBusy(false);
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!spec) return;
    setBusy(true);
    setError(null);
    try {
      await api.post('/firm/connectors', { kind, name: name.trim() || undefined, config: cfg, secret: spec.secret ? secret : undefined, permissions: perm });
      toast.push({ kind: 'success', title: t('firm.conn.added') });
      close();
      onDone();
    } catch (x) {
      const m = errorToast(x, t('firm.conn.addFailed'));
      setError({ message: m.body ?? m.title, hint: m.hint ?? null });
    } finally {
      setBusy(false);
    }
  }
  const ready = !!spec && spec.required.every((f) => (cfg[f] ?? '').trim()) && (!spec.secret || secret.trim().length > 0);
  return (
    <Dialog
      open={open}
      onClose={close}
      title={t('firm.conn.add')}
      description={t('firm.conn.addDesc')}
      closeLabel={t('common.close')}
      testId="connector-dialog"
      footer={
        <>
          <Button variant="ghost" onClick={close}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" type="submit" form="connector-form" loading={busy} disabled={!ready} data-testid="connector-save">
            {t('common.save')}
          </Button>
        </>
      }
    >
      <form id="connector-form" className="acr-stack" onSubmit={submit}>
        <Select label={t('firm.conn.kind')} value={kind} onChange={(e) => setKind(e.target.value)} options={kinds.map((k) => ({ value: k.kind, label: KIND_LABEL[k.kind] ? t(KIND_LABEL[k.kind]) : k.label }))} data-testid="connector-kind" />
        <Input label={t('firm.conn.name')} value={name} onChange={(e) => setName(e.target.value)} placeholder={spec ? t(KIND_LABEL[spec.kind] ?? 'firm.conn.kind.local_folder') : ''} maxLength={120} />
        {spec?.fields.map((f) => (
          <Input
            key={`${kind}-${f}`}
            label={FIELD_LABEL[f] ? t(FIELD_LABEL[f]) : f}
            value={cfg[f] ?? ''}
            onChange={(e) => setCfg((c) => ({ ...c, [f]: e.target.value }))}
            required={spec.required.includes(f)}
            mono
            dir="ltr"
            autoComplete="off"
            data-testid={`connector-field-${f}`}
          />
        ))}
        {spec?.secret && (
          <Input
            label={t('firm.conn.secret')}
            hint={t('firm.conn.secretHint')}
            type="password"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            autoComplete="new-password"
            dir="ltr"
            required
            data-testid="connector-secret"
          />
        )}
        <Select
          label={t('firm.conn.permissions')}
          hint={perm === 'mirror' ? t('firm.conn.perm.mirrorHint') : t('firm.conn.perm.firmHint')}
          value={perm}
          onChange={(e) => setPerm(e.target.value as 'firm' | 'mirror')}
          options={[
            { value: 'firm', label: t('firm.conn.perm.firm') },
            { value: 'mirror', label: t('firm.conn.perm.mirror') },
          ]}
        />
        {error && (
          <div className="acr-formerror" role="alert">
            <strong>{error.message}</strong>
            {error.hint && <span>{error.hint}</span>}
          </div>
        )}
      </form>
    </Dialog>
  );
}
