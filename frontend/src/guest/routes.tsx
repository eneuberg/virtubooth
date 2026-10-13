/**
 * Guest routes: "/" (Start) and "/x/:ext/*" (an activity, lazy), both behind the
 * session gate. Unknown paths never reach the app: the server answers them with
 * gate.html (404). The client-side NotFound covers an activity this build has no
 * page for.
 */
import { CircleQuestionMark } from 'lucide-react';
import { lazy, Suspense, useEffect, useRef } from 'react';
import { Route, Switch, useLocation, useParams } from 'wouter';
import { getExtension, listExtensions } from '@/extensions/registry';
import { markReady } from '@/lib/boot';
import { msg, t } from '@/lib/messages.de';
import { useActivities } from '@/sdk/activities';
import { canUpload, useSession } from '@/sdk/session';
import { LinkButton } from '@/ui/Button';
import { Notice } from '@/ui/Notice';
import { Spinner } from '@/ui/Spinner';
import { showToast } from '@/ui/Toast';
import { UiProvider } from '@/ui/UiProvider';
import { ErrorBoundary } from './ErrorBoundary';
import { useMyPhotosSync } from './photos';
import { SessionGate } from './SessionGate';
import { Start } from './Start';

/** one lazy page per activity, created once at module load (never during render) */
const pages = new Map(
  listExtensions().map((ext) => {
    const Page = lazy(ext.load);
    return [ext.id, (id: string) => <Page id={id} />] as const;
  }),
);

function NotFound() {
  return (
    <Notice
      icon={CircleQuestionMark}
      title={msg.notFoundTitle}
      data-testid="notfound"
      actions={
        <LinkButton href="/" variant="primary" size="lg" block>
          {t.toStart}
        </LinkButton>
      }
    >
      <p>{msg.notFoundText}</p>
    </Notice>
  );
}

function ActivityRoute() {
  const { ext } = useParams<{ ext: string }>();
  const render = pages.get(ext);
  if (!render || !getExtension(ext)) return <NotFound />;
  return (
    <SessionGate activityId={ext}>
      <Suspense
        fallback={
          <div data-surface="dark" className="grid h-dvh place-items-center bg-kamera">
            <Spinner label="Kamera startet…" className="size-8 text-papier" />
          </div>
        }
      >
        {render(ext)}
      </Suspense>
    </SessionGate>
  );
}

/** "Du kannst wieder hochladen." once a pause or stop ends (on any guest page). */
function useUploadsFreedToast(): void {
  const session = useSession();
  const reason = canUpload(session);
  const blockedBefore = useRef(false);
  const now = !reason.ok && (reason.reason === 'paused' || reason.reason === 'stopped');
  useEffect(() => {
    if (blockedBefore.current && !now && session.status === 'ready') {
      showToast({ tone: 'success', message: msg.uploadsFreeAgain });
    }
    blockedBefore.current = now;
  }, [now, session.status]);
}

/** The party's name in the tab title. */
function useDocumentTitle(): void {
  const { data } = useActivities();
  const name = data?.partyName;
  useEffect(() => {
    if (name) document.title = name;
  }, [name]);
}

function Shell() {
  useUploadsFreedToast();
  useDocumentTitle();
  useMyPhotosSync();
  return (
    <Switch>
      <Route path="/">
        <SessionGate>
          <Start />
        </SessionGate>
      </Route>
      <Route path="/x/:ext/*?" component={ActivityRoute} />
      <Route component={NotFound} />
    </Switch>
  );
}

export function GuestApp() {
  const [, navigate] = useLocation();
  useEffect(() => {
    markReady();
  }, []);
  return (
    <UiProvider navigate={navigate}>
      <ErrorBoundary>
        <Shell />
      </ErrorBoundary>
    </UiProvider>
  );
}
