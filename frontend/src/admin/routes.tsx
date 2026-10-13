/**
 * Admin routes under base /admin. The server already redirects /admin → /admin/live and
 * pages without a session → /admin/login?next=… (303); the app does the same when a
 * request answers 401 later (store/api.ts).
 */
import { CircleQuestionMark } from 'lucide-react';
import { Redirect, Route, Router, Switch, useLocation } from 'wouter';
import { LinkButton } from '@/ui/Button';
import { Notice } from '@/ui/Notice';
import { UiProvider } from '@/ui/UiProvider';
import { LivePage } from './live/LivePage';
import { LoginPage } from './login/LoginPage';
import { ManagePage } from './manage/ManagePage';
import { useDocumentSurface } from './surface';
import { UserPage } from './user/UserPage';

/** Paths the admin app routes itself (React Aria links to anything else load normally). */
const APP_ROUTE = /^\/(?:live|manage|user|login)(?:[/?#]|$)/;

function NotFound() {
  useDocumentSurface('dark');
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
      navigate={(path) => (APP_ROUTE.test(path) ? navigate(path) : location.assign(path))}
      useHref={(href) => (APP_ROUTE.test(href) ? `/admin${href}` : href)}
    >
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
