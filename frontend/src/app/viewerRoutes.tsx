import { Link, Route, useLocation, useNavigate, useParams } from 'react-router-dom';
import { EmptyState, IconDoc, IconModel, IconDeck, IconGrid, PageHeader } from '../ds';
import { useT } from '../i18n';

/**
 * Placeholder owner of the viewer routes. The viewers packet replaces this file and registers the real
 * PDF inspector, model view, deck view and grid. Until then each route explains itself and offers a next step.
 */
function ViewerPending({ kind }: { kind: 'doc' | 'model' | 'deck' | 'grid' }) {
  const t = useT();
  const nav = useNavigate();
  const loc = useLocation();
  const { id, docId, name } = useParams();
  const icon = kind === 'doc' ? <IconDoc size={22} /> : kind === 'model' ? <IconModel size={22} /> : kind === 'deck' ? <IconDeck size={22} /> : <IconGrid size={22} />;
  const target = docId ?? name ?? '';
  const tab = kind === 'doc' ? 'documents' : kind === 'model' ? 'models' : kind === 'deck' ? 'decks' : 'grid';
  return (
    <div className="acr-page" data-testid={`viewer-${kind}-pending`}>
      <PageHeader
        title={t(`viewer.${kind}.title`)}
        subtitle={target ? decodeURIComponent(target) : undefined}
        breadcrumb={
          <nav aria-label={t('common.breadcrumbs')} data-testid="breadcrumbs" className="acr-crumbs">
            <Link to="/deals">{t('nav.deals')}</Link>
            <span aria-hidden="true">/</span>
            <Link to={`/deals/${id}`}>{id}</Link>
          </nav>
        }
      />
      <EmptyState
        icon={icon}
        title={t('viewer.pending.title')}
        body={t('viewer.pending.body', { path: loc.pathname + loc.search })}
        action={{ label: t('viewer.pending.back'), onClick: () => nav(`/deals/${id}?tab=${tab}`) }}
        secondary={{ label: t('viewer.pending.reload'), onClick: () => window.location.reload() }}
      />
    </div>
  );
}

export function viewerRoutes() {
  return [
    <Route key="doc" path="/deals/:id/docs/:docId" element={<ViewerPending kind="doc" />} />,
    <Route key="model" path="/deals/:id/models/:name" element={<ViewerPending kind="model" />} />,
    <Route key="deck" path="/deals/:id/decks/:name" element={<ViewerPending kind="deck" />} />,
    <Route key="grid" path="/deals/:id/grid" element={<ViewerPending kind="grid" />} />,
  ];
}
