import { useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { Badge, Button, Dialog, EmptyState, IconLink, IconPlus, Panel, Segmented, Select, SkeletonRows, Textarea, useToast } from '../ds';
import { api } from '../api/client';
import { items, useMe, useResource } from '../api/hooks';
import type { Page } from '../api/types';
import { errorToast } from '../app/lib';
import { useI18n } from '../i18n';
import { LoadError } from './lib/shared';
import type { DealRef, MemberRef, MemoryEntry } from './lib/types';
import './lib/firm.css';

type Filter = 'all' | 'org' | 'deal';
const SOURCE: Record<string, string> = {
  manual: 'firm.mem.source.manual',
  job: 'firm.mem.source.job',
  document: 'firm.mem.source.document',
  email: 'firm.mem.source.email',
  agent: 'firm.mem.source.agent',
  comment: 'firm.mem.source.comment',
};

interface RawDeal {
  deal_id?: string;
  id?: string;
  name: string;
}

export default function Memory() {
  const { t, fmt } = useI18n();
  const toast = useToast();
  const { me } = useMe();
  const canWrite = me?.role === 'owner' || me?.role === 'member';
  const res = useResource<MemoryEntry[]>(async (signal) => items(await api.get<Page<MemoryEntry>>('/firm/memory', { query: { limit: 200 }, signal })), []);
  const deals = useResource<DealRef[]>(
    async (signal) => items(await api.get<Page<RawDeal> | RawDeal[]>('/deals', { query: { limit: 200 }, signal })).map((d) => ({ deal_id: d.deal_id ?? d.id ?? '', name: d.name })),
    [],
  );
  const members = useResource<MemberRef[]>(async (signal) => items(await api.get<Page<MemberRef> | MemberRef[]>('/org/members', { signal })), []);
  const [filter, setFilter] = useState<Filter>('all');
  const [editing, setEditing] = useState<MemoryEntry | 'new' | null>(null);
  const [removing, setRemoving] = useState<MemoryEntry | null>(null);

  const dealName = useMemo(() => new Map((deals.data ?? []).map((d) => [d.deal_id, d.name])), [deals.data]);
  const who = useMemo(() => new Map((members.data ?? []).map((m) => [m.user_id, m.name || m.email])), [members.data]);
  const mine = me?.user.id;
  const rows = (res.data ?? []).filter((m) => filter === 'all' || m.scope === filter);

  async function remove(m: MemoryEntry) {
    try {
      await api.del(`/firm/memory/${m.id}`);
      setRemoving(null);
      res.reload();
    } catch (e) {
      toast.push(errorToast(e, t('firm.mem.removeFailed')));
    }
  }

  if (res.error) return <LoadError error={res.error} retry={res.reload} />;
  return (
    <div className="acr-firm">
      <p className="acr-firm__intro">{t('firm.mem.intro')}</p>
      <Panel
        title={t('firm.mem.title')}
        flush
        actions={
          <>
            <Segmented
              label={t('firm.mem.filter')}
              value={filter}
              onChange={setFilter}
              options={[
                { value: 'all', label: t('firm.mem.filter.all') },
                { value: 'org', label: t('firm.mem.filter.org') },
                { value: 'deal', label: t('firm.mem.filter.deal') },
              ]}
              testId="memory-filter"
            />
            {canWrite && (
              <Button size="sm" variant="primary" icon={<IconPlus size={13} />} onClick={() => setEditing('new')} data-testid="memory-add">
                {t('firm.mem.add')}
              </Button>
            )}
          </>
        }
      >
        {res.loading && !res.data ? (
          <SkeletonRows rows={4} label={t('common.loading')} />
        ) : rows.length === 0 ? (
          <EmptyState title={t('firm.mem.empty.title')} body={t('firm.mem.empty.body')} action={canWrite ? { label: t('firm.mem.add'), onClick: () => setEditing('new') } : { label: t('common.retry'), onClick: res.reload }} />
        ) : (
          <div data-testid="memory-list" role="list">
            {rows.map((m) => {
              const editable = me?.role === 'owner' || m.created_by === mine;
              return (
                <div key={m.id} className="acr-firm-mem" role="listitem" data-testid="memory-row" data-id={m.id}>
                  <div className="acr-firm-mem__main">
                    <p className="acr-firm-mem__text">{m.text}</p>
                    <div className="acr-firm-mem__meta">
                      <Badge tone={m.scope === 'org' ? 'accent' : 'info'}>{m.scope === 'org' ? t('firm.mem.scope.org') : dealName.get(m.deal_id ?? '') ?? t('firm.mem.scope.deal')}</Badge>
                      <span>
                        {t('firm.mem.sourceLabel')}{' '}
                        {m.source_link ? (
                          <Link to={m.source_link} className="acr-link-btn" data-testid="memory-source">
                            <IconLink size={11} /> {t(SOURCE[m.source_kind] ?? 'firm.mem.source.manual')}
                          </Link>
                        ) : (
                          <span>{t(SOURCE[m.source_kind] ?? 'firm.mem.source.manual')}</span>
                        )}
                      </span>
                      <span>{t('firm.mem.by', { name: who.get(m.created_by ?? '') ?? t('firm.mem.unknown'), when: fmt.date(m.created_at) })}</span>
                      {m.updated_at && m.updated_at !== m.created_at && <span>{t('firm.mem.edited', { when: fmt.relative(m.updated_at) })}</span>}
                    </div>
                  </div>
                  {editable && (
                    <span className="acr-rowactions">
                      <Button size="sm" variant="ghost" onClick={() => setEditing(m)} data-testid="memory-edit">
                        {t('firm.mem.edit')}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setRemoving(m)} data-testid="memory-delete">
                        {t('firm.mem.delete')}
                      </Button>
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Panel>
      <EditDialog
        target={editing}
        deals={deals.data ?? []}
        onClose={() => setEditing(null)}
        onDone={() => {
          setEditing(null);
          res.reload();
        }}
      />
      <Dialog
        open={removing !== null}
        onClose={() => setRemoving(null)}
        title={t('firm.mem.deleteTitle')}
        description={t('firm.mem.deleteBody')}
        closeLabel={t('common.close')}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setRemoving(null)}>
              {t('common.cancel')}
            </Button>
            <Button variant="danger" onClick={() => removing && remove(removing)}>
              {t('firm.mem.delete')}
            </Button>
          </>
        }
      >
        {removing && <p className="acr-firm-mem__text acr-muted">{removing.text}</p>}
      </Dialog>
    </div>
  );
}

function EditDialog({ target, deals, onClose, onDone }: { target: MemoryEntry | 'new' | null; deals: DealRef[]; onClose: () => void; onDone: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const isNew = target === 'new';
  const entry = target && target !== 'new' ? target : null;
  const [text, setText] = useState('');
  const [scope, setScope] = useState<'org' | 'deal'>('org');
  const [dealId, setDealId] = useState('');
  const [busy, setBusy] = useState(false);
  const [seen, setSeen] = useState<unknown>(null);
  if (seen !== target) {
    setSeen(target);
    setText(entry?.text ?? '');
    setScope('org');
    setDealId(deals[0]?.deal_id ?? '');
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      if (entry) await api.patch(`/firm/memory/${entry.id}`, { text: text.trim() });
      else await api.post('/firm/memory', { text: text.trim(), scope, deal_id: scope === 'deal' ? dealId : undefined });
      toast.push({ kind: 'success', title: t(entry ? 'firm.mem.updated' : 'firm.mem.created') });
      onDone();
    } catch (x) {
      toast.push(errorToast(x, t('firm.mem.saveFailed')));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      open={target !== null}
      onClose={onClose}
      title={t(entry ? 'firm.mem.editTitle' : 'firm.mem.add')}
      description={t('firm.mem.dialogDesc')}
      closeLabel={t('common.close')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" type="submit" form="memory-form" loading={busy} disabled={!text.trim() || (isNew && scope === 'deal' && !dealId)} data-testid="memory-save">
            {t('common.save')}
          </Button>
        </>
      }
    >
      <form id="memory-form" className="acr-stack" onSubmit={submit}>
        <Textarea label={t('firm.mem.text')} value={text} onChange={(e) => setText(e.target.value)} rows={4} maxLength={2000} data-autofocus data-testid="memory-text" />
        {isNew && (
          <>
            <Segmented
              label={t('firm.mem.scope')}
              value={scope}
              onChange={setScope}
              options={[
                { value: 'org', label: t('firm.mem.scope.org') },
                { value: 'deal', label: t('firm.mem.scope.deal') },
              ]}
            />
            {scope === 'deal' && <Select label={t('firm.mem.deal')} value={dealId} onChange={(e) => setDealId(e.target.value)} options={deals.map((d) => ({ value: d.deal_id, label: d.name }))} />}
          </>
        )}
      </form>
    </Dialog>
  );
}
