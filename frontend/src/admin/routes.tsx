/**
 * Admin routes under base /admin. The server already redirects /admin → /admin/live and
 * pages without a session → /admin/login?next=… (303); the app does the same when a
 * request answers 401 later (store/api.ts).
 */
import { CircleQuestionMark } from 'lucide-react';
import { lazy, Suspense } from 'react';
import { Redirect, Route, Router, Switch, useLocation } from 'wouter';
import { LinkButton } from '@/ui/Button';
import { Notice } from '@/ui/Notice';
import { Spinner } from '@/ui/Spinner';
import { UiProvider } from '@/ui/UiProvider';
import { guardedNavigate } from './lib/leaveGuard';
import { LivePage } from './live/LivePage';
import { LoginPage } from './login/LoginPage';

// the manage area and the user page load on demand: the party phone needs live only
const ManagePage = lazy(() => import('./manage/ManagePage').then((m) => ({ default: m.ManagePage })));
const UserPage = lazy(() => import('./user/UserPage').then((m) => ({ default: m.UserPage })));

function Loading() {
  return (
    <div className="grid min-h-dvh place-items-center">
      <Spinner label="Lädt…" />
    </div>
  );
}

/** Paths the admin app routes itself (React Aria links to anything else load normally). */
const APP_ROUTE = /^\/(?:live|manage|user|login)(?:[/?#]|$)/;

function NotFound() {
  return (
    <Notice
      icon={CircleQuestionMark}
      title="Hier ist nichts."
      data-testid="notfound"
      actions={
        <LinkButton href="/live" variant="primary" size="lg" block>
          Zur Live-Ansicht
        </LinkButton>
      }
    >
      Diese Admin-Seite gibt es nicht.
    </Notice>
  );
}

function Routes() {
  const [, navigate] = useLocation();
  return (
    <UiProvider
      // a screen with unsaved changes may hold the navigation (lib/leaveGuard.ts)
      navigate={(path) =>
        guardedNavigate(() => (APP_ROUTE.test(path) ? navigate(path) : location.assign(path)))
      }
      useHref={(href) => (APP_ROUTE.test(href) ? `/admin${href}` : href)}
    >
      <Suspense fallback={<Loading />}>
        <Switch>
          <Route path="/">
            <Redirect to="/live" replace />
          </Route>
          <Route path="/login" component={LoginPage} />
          <Route path="/live" component={LivePage} />
          <Route path="/manage" component={ManagePage} />
          <Route path="/user" component={UserPage} />
          <Route component={NotFound} />
        </Switch>
      </Suspense>
    </UiProvider>
  );
}

export function AdminApp() {
  return (
    <Router base="/admin">
      <Routes />
    </Router>
  );
}
