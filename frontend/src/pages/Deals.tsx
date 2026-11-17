import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Badge, Button, EmptyState, IconDeal, IconPlus, IconSearch, Input, PageHeader, SkeletonRows, Table } from '../ds';
import type { Column } from '../ds';
import { useDeals } from '../api/hooks';
import type { Deal } from '../api/types';
import { useI18n } from '../i18n';
import { NewDealDialog } from '../features/NewDealDialog';

export function dealTone(s: string): 'positive' | 'warning' | 'neutral' {
  return s === 'active' ? 'positive' : s === 'on_hold' ? 'warning' : 'neutral';
}

export default function Deals() {
  const { t, fmt } = useI18n();
  const nav = useNavigate();
  const deals = useDeals();
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    return (deals.data ?? []).filter((d) => !s || `${d.name} ${d.target ?? ''} ${d.sector ?? ''}`.toLowerCase().includes(s));
  }, [deals.data, q]);

  const columns: Column<Deal>[] = [
    { key: 'name', header: t('deal.name'), sortValue: (d) => d.name, render: (d) => <span className="acr-strong">{d.name}</span> },
    { key: 'target', header: t('deal.target'), sortValue: (d) => d.target, render: (d) => d.target ?? '—' },
    { key: 'sector', header: t('deal.sector'), sortValue: (d) => d.sector, render: (d) => d.sector ?? '—' },
    { key: 'status', header: t('deal.status'), sortValue: (d) => d.status, render: (d) => <Badge tone={dealTone(d.status)} dot>{t(`deal.status.${d.status}`)}</Badge> },
    { key: 'docs', header: t('deal.tab.documents'), numeric: true, sortValue: (d) => d.counts?.documents, render: (d) => fmt.integer(d.counts?.documents ?? 0) },
    { key: 'deliv', header: t('nav.library'), numeric: true, sortValue: (d) => d.counts?.deliverables, render: (d) => fmt.integer(d.counts?.deliverables ?? 0) },
    { key: 'updated', header: t('lib.updated'), numeric: true, sortValue: (d) => d.updated_at, render: (d) => (d.updated_at ? fmt.relative(d.updated_at) : '—') },
  ];

  return (
    <div className="acr-page">
      <PageHeader
        title={t('nav.deals')}
        subtitle={t('deals.subtitle')}
        actions={
          <Button variant="primary" icon={<IconPlus size={14} />} data-testid="new-deal" onClick={() => setOpen(true)}>
            {t('deal.new.title')}
          </Button>
        }
      />
      <div className="acr-toolbar">
        <Input hideLabel label={t('deals.search')} placeholder={t('deals.search')} startSlot={<IconSearch size={14} />} value={q} onChange={(e) => setQ(e.target.value)} fieldClassName="acr-toolbar__search" />
        <span className="acr-faint acr-num">{t('deals.count', { n: fmt.integer(rows.length) })}</span>
      </div>
      {deals.loading && !deals.data ? (
        <SkeletonRows rows={6} label={t('common.loading')} />
      ) : deals.error ? (
        <EmptyState title={t('deals.error')} body={deals.error.hint ?? deals.error.message} action={{ label: t('common.retry'), onClick: deals.reload }} />
      ) : (
        <Table
          testId="deals-table"
          caption={t('nav.deals')}
          columns={columns}
          rows={rows}
          rowKey={(d) => d.id}
          rowProps={(d) => ({ 'data-testid': 'deal-row', 'data-id': d.id })}
          onRowActivate={(d) => nav(`/deals/${d.id}`)}
          initialSort={{ key: 'updated', dir: 'desc' }}
          empty={
            q ? (
              <EmptyState icon={<IconSearch size={22} />} title={t('deals.noMatch')} body={t('deals.noMatchBody')} action={{ label: t('common.clear'), onClick: () => setQ('') }} />
            ) : (
              <EmptyState icon={<IconDeal size={22} />} title={t('deals.empty.title')} body={t('deals.empty.body')} action={{ label: t('deal.new.title'), onClick: () => setOpen(true), icon: <IconPlus size={14} /> }} />
            )
          }
        />
      )}
      <NewDealDialog open={open} onClose={() => setOpen(false)} onCreated={(d) => nav(`/deals/${d.id}`)} />
    </div>
  );
}
