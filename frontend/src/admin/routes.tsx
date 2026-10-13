/**
 * Admin routes under base /admin. OWNER: wave 2 "AD". The server already redirects
 * /admin → /admin/live and unauthenticated pages → /admin/login?next=… (303).
 */
import { CircleQuestionMark } from 'lucide-react';
import { Redirect, Route, Router, Switch, useLocation } from 'wouter';
import { LinkButton } from '@/ui/Button';
import { Notice } from '@/ui/Notice';
import { ToastSlot } from '@/ui/Toast';
import { UiProvider } from '@/ui/UiProvider';
import { LivePage, LoginPage, ManagePage, UserPage } from './pages';

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
    <UiProvider navigate={navigate}>
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
      <ToastSlot />
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
