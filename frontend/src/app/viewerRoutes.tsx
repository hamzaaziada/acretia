import { Route } from 'react-router-dom';
import { viewerRoutes as viewerRouteObjects } from '../viewers/routes';

/** The shell mounts the viewer routes (PDF inspector, model view, and the grid/deck viewers when present). */
export function viewerRoutes() {
  return viewerRouteObjects.map((r) => <Route key={r.path} path={r.path} element={r.element} />);
}
