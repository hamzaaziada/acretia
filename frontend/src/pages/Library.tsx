import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { IconSearch, Input, PageHeader, Select, SkeletonRows } from '../ds';
import { useDeals } from '../api/hooks';
import { useI18n } from '../i18n';
import { DeliverablesTable } from '../features/Deliverables';
import { useAllDeliverables } from '../app/lib';

const KINDS = ['xlsx', 'pptx', 'docx', 'pdf', 'grid'];

export default function Library() {
  const { t, fmt } = useI18n();
  const nav = useNavigate();
  const deals = useDeals();
  const all = useAllDeliverables(deals.data);
  const [q, setQ] = useState('');
  const [kind, setKind] = useState('');
  const [deal, setDeal] = useState('');
  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    return (all.data ?? []).filter((d) => (!kind || d.kind === kind) && (!deal || d.deal_id === deal) && (!s || `${d.name} ${d.deal_name}`.toLowerCase().includes(s)));
  }, [all.data, q, kind, deal]);
  const loading = (deals.loading && !deals.data) || (all.loading && !all.data);

  return (
    <div className="acr-page">
      <PageHeader title={t('nav.library')} subtitle={t('lib.subtitle')} />
      <div className="acr-toolbar">
        <Input hideLabel label={t('lib.search')} placeholder={t('lib.search')} startSlot={<IconSearch size={14} />} value={q} onChange={(e) => setQ(e.target.value)} fieldClassName="acr-toolbar__search" />
        <Select
          hideLabel
          label={t('lib.kind')}
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          options={[{ value: '', label: t('lib.allKinds') }, ...KINDS.map((k) => ({ value: k, label: k }))]}
        />
        <Select
          hideLabel
          label={t('lib.deal')}
          value={deal}
          onChange={(e) => setDeal(e.target.value)}
          options={[{ value: '', label: t('lib.allDeals') }, ...(deals.data ?? []).map((d) => ({ value: d.id, label: d.name }))]}
        />
        <span className="acr-faint acr-num">{t('lib.count', { n: fmt.integer(rows.length) })}</span>
      </div>
      {loading ? (
        <SkeletonRows rows={6} label={t('common.loading')} />
      ) : (
        <DeliverablesTable rows={rows} showDeal onChanged={all.reload} emptyAction={{ label: t('home.title'), onClick: () => nav('/') }} />
      )}
    </div>
  );
}
