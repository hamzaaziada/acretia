import { useNavigate } from 'react-router-dom';
import { EmptyState, IconSearch } from '../ds';
import { useShell } from '../app/shell';
import { useT } from '../i18n';

export default function NotFound() {
  const t = useT();
  const nav = useNavigate();
  const { openPalette } = useShell();
  return (
    <div className="acr-page">
      <h1 className="acr-sr-only">{t('notfound.title')}</h1>
      <EmptyState
        icon={<IconSearch size={22} />}
        title={t('notfound.title')}
        body={t('notfound.body')}
        action={{ label: t('notfound.home'), onClick: () => nav('/') }}
        secondary={{ label: t('notfound.search'), onClick: () => openPalette() }}
      />
    </div>
  );
}
