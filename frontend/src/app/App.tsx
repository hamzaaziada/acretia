import { Suspense, lazy } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { Skeleton, SkeletonRows } from '../ds';
import { useMe } from '../api/hooks';
import { useI18n } from '../i18n';
import { Shell } from './shell';
import { viewerRoutes } from './viewerRoutes';

const Login = lazy(() => import('../pages/Login'));
const AcceptInvite = lazy(() => import('../pages/AcceptInvite'));
const Home = lazy(() => import('../pages/Home'));
const Run = lazy(() => import('../pages/Run'));
const Deals = lazy(() => import('../pages/Deals'));
const Deal = lazy(() => import('../pages/Deal'));
const Library = lazy(() => import('../pages/Library'));
const Agents = lazy(() => import('../pages/Agents'));
const Notifications = lazy(() => import('../pages/Notifications'));
const Settings = lazy(() => import('../pages/Settings'));
const NotFound = lazy(() => import('../pages/NotFound'));

function PageFallback() {
  const { t } = useI18n();
  return (
    <div className="acr-page" aria-busy="true">
      <Skeleton width={220} height={22} />
      <div className="acr-page__gap" />
      <SkeletonRows rows={6} label={t('common.loading')} />
    </div>
  );
}

function RequireAuth() {
  const { me, loading } = useMe();
  const loc = useLocation();
  const { t } = useI18n();
  if (loading)
    return (
      <div className="acr-boot" role="status" aria-label={t('common.loading')}>
        <div className="acr-boot__side" />
        <div className="acr-boot__main">
          <Skeleton width={260} height={22} />
          <div className="acr-page__gap" />
          <SkeletonRows rows={5} label={t('common.loading')} />
        </div>
      </div>
    );
  if (!me) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  return <Shell />;
}

export function App() {
  return (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/invite" element={<AcceptInvite />} />
        <Route element={<RequireAuth />}>
          <Route path="/" element={<Home />} />
          <Route path="/runs/:jobId" element={<Run />} />
          <Route path="/deals" element={<Deals />} />
          <Route path="/deals/:id" element={<Deal />} />
          {viewerRoutes()}
          <Route path="/library" element={<Library />} />
          <Route path="/agents" element={<Agents />} />
          <Route path="/notifications" element={<Notifications />} />
          <Route path="/settings" element={<Navigate to="/settings/preferences" replace />} />
          <Route path="/settings/:section" element={<Settings />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
