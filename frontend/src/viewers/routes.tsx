import { Suspense, lazy } from 'react';
import type { ComponentType } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import type { RouteObject } from 'react-router-dom';
import { EmptyState, IconDeal, IconDeck, IconGrid, Skeleton } from '../ds';
import { useT } from '../i18n';
import './shared/viewers.css';

/** folder under src/viewers → route. A folder that does not exist yet renders a fallback with a real way out. */
const VIEWERS = {
  pdf: '/deals/:id/docs/:docId',
  model: '/deals/:id/models/:name',
  grid: '/deals/:id/grid',
  deck: '/deals/:id/decks/:name',
} as const;

type Folder = keyof typeof VIEWERS;

const loaders = import.meta.glob('./*/Page.tsx') as Record<string, () => Promise<{ default: ComponentType }>>;

function Loading() {
  const t = useT();
  return (
    <div className="vw-loading" role="status" aria-label={t('viewers.loading')}>
      <Skeleton width="40%" height={20} />
      <Skeleton height={14} />
      <Skeleton height={14} />
      <Skeleton width="70%" height={14} />
    </div>
  );
}

function Missing({ folder }: { folder: Folder }) {
  const t = useT();
  const nav = useNavigate();
  const { id } = useParams();
  const icon = folder === 'deck' ? <IconDeck size={22} /> : folder === 'grid' ? <IconGrid size={22} /> : <IconDeal size={22} />;
  return (
    <div className="vw-fallback">
      <EmptyState
        icon={icon}
        title={t(`viewers.missing.${folder}.title`)}
        body={t('viewers.missing.body')}
        action={{ label: t('viewers.missing.back'), onClick: () => nav(id ? `/deals/${encodeURIComponent(id)}` : '/') }}
      />
    </div>
  );
}

function route(folder: Folder): RouteObject {
  const load = loaders[`./${folder}/Page.tsx`];
  if (!load) return { path: VIEWERS[folder], element: <Missing folder={folder} /> };
  const Page = lazy(load);
  return {
    path: VIEWERS[folder],
    element: (
      <Suspense fallback={<Loading />}>
        <Page />
      </Suspense>
    ),
  };
}

export const viewerRoutes: RouteObject[] = (Object.keys(VIEWERS) as Folder[]).map(route);
