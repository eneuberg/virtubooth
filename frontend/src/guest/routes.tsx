/**
 * Guest routes: "/" (Start) and "/x/:ext/*" (an activity, lazy). OWNER: wave 2 "GP".
 */
import { CircleQuestionMark } from 'lucide-react';
import { lazy, Suspense } from 'react';
import { Route, Switch, useLocation, useParams } from 'wouter';
import { getExtension, listExtensions } from '@/extensions/registry';
import { LinkButton } from '@/ui/Button';
import { Notice } from '@/ui/Notice';
import { Spinner } from '@/ui/Spinner';
import { ToastSlot } from '@/ui/Toast';
import { UiProvider } from '@/ui/UiProvider';
import { Start } from './Start';

/** one lazy page per activity, created once at module load (never during render) */
const pages = new Map(
  listExtensions().map((ext) => {
    const Page = lazy(ext.load);
    return [ext.id, (id: string) => <Page id={id} />] as const;
  }),
);

function ActivityRoute() {
  const { ext } = useParams<{ ext: string }>();
  const render = pages.get(ext);
  if (!render || !getExtension(ext)) return <NotFound />;
  return (
    <Suspense
      fallback={
        <div data-surface="dark" className="grid h-dvh place-items-center bg-kamera">
          <Spinner label="Kamera startet…" className="size-8 text-papier" />
        </div>
      }
    >
      {render(ext)}
    </Suspense>
  );
}

function NotFound() {
  return (
    <Notice
      icon={CircleQuestionMark}
      title="Hier ist nichts."
      data-testid="notfound"
      actions={
        <LinkButton href="/" variant="primary" size="lg" block>
          Zum Start
        </LinkButton>
      }
    >
      Diese Seite gibt es nicht.
    </Notice>
  );
}

export function GuestApp() {
  const [, navigate] = useLocation();
  return (
    <UiProvider navigate={navigate}>
      <Switch>
        <Route path="/">
          <Start />
          <ToastSlot />
        </Route>
        <Route path="/x/:ext/*?" component={ActivityRoute} />
        <Route component={NotFound} />
      </Switch>
    </UiProvider>
  );
}
