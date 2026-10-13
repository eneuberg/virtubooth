/**
 * The session gate around every guest route (/ and /x/…): nothing personal and no
 * camera renders before the session is ready.
 *   loading     a quiet dark page (a spinner only if it takes a moment)
 *   needs_join  the join sheet over the party's name (deep links too: the camera,
 *               and with it the browser's camera prompt, only comes after joining)
 *   banned      "Gesperrt", with what to do and a reload
 *   error       what went wrong (offline / no answer / the server's words), reload
 *   ready       the route
 */
import { useQuery } from '@tanstack/react-query';
import { Ban, CircleAlert, CloudOff, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { fatalCopy, isApiError } from '@/api/errors';
import { msg, t } from '@/lib/messages.de';
import { fetchActivities, ACTIVITIES_KEY } from '@/sdk/activities';
import { useSession, type JoinInfo } from '@/sdk/session';
import { Button } from '@/ui/Button';
import { Notice } from '@/ui/Notice';
import { Spinner } from '@/ui/Spinner';
import { ToastSlot } from '@/ui/Toast';
import { JoinSheet } from './JoinSheet';

function reload(): void {
  location.reload();
}

function ReloadButton() {
  return (
    // the one way forward on this screen: focus it, like the old fatal() did
    <Button variant="primary" size="lg" block onPress={reload} autoFocus data-testid="reload">
      {t.reloadPage}
    </Button>
  );
}

export function BootScreen() {
  return (
    <div className="grid min-h-dvh place-items-center" aria-busy="true">
      <span className="opacity-0 motion-ok:animate-fade-in motion-ok:[animation-delay:600ms]">
        <Spinner label={t.loading} className="size-7 text-ink-muted" />
      </span>
    </div>
  );
}

/** The activity title for "Danach öffnet sich „…“" (from the cached activity list). */
function useDestination(activityId: string | null): string | null {
  const { data } = useQuery({
    queryKey: ACTIVITIES_KEY,
    queryFn: fetchActivities,
    enabled: activityId !== null,
    staleTime: 5 * 60_000,
  });
  if (!activityId) return null;
  return data?.extensions.find((e) => e.id === activityId)?.title ?? null;
}

function JoinScreen({ join, activityId }: { join: JoinInfo; activityId: string | null }) {
  const destination = useDestination(activityId);
  return (
    <div className="mx-auto grid min-h-dvh max-w-[35rem] content-start px-4 pt-[max(4.5rem,env(safe-area-inset-top))] lg:max-w-[75rem] lg:px-10">
      {/* the party's name stays readable behind the sheet: you know where you are */}
      <p translate="no" aria-hidden="true" className="text-3xl font-bold text-ink-muted/60">
        {join.party_name}
      </p>
      <JoinSheet join={join} destination={destination} />
      <ToastSlot />
    </div>
  );
}

export function BannedScreen() {
  return (
    <>
      <Notice
        icon={Ban}
        title={msg.bannedTitle}
        data-testid="banned"
        hint="Wenn die Gastgeber dich wieder freischalten, lade die Seite neu."
        actions={<ReloadButton />}
      >
        <p>{msg.bannedText}</p>
      </Notice>
      <ToastSlot />
    </>
  );
}

function errorIcon(error: unknown): LucideIcon {
  return isApiError(error) && error.code === 'network' ? CloudOff : CircleAlert;
}

export function ErrorScreen({ error }: { error: unknown }) {
  const copy = fatalCopy(error);
  const icon = errorIcon(error);
  return (
    <Notice icon={icon} title={copy.title} data-testid="fatal" actions={<ReloadButton />}>
      <p>{copy.text}</p>
    </Notice>
  );
}

export function SessionGate({
  children,
  activityId = null,
}: {
  children: ReactNode;
  activityId?: string | null;
}) {
  const session = useSession();
  switch (session.status) {
    case 'loading':
      return <BootScreen />;
    case 'needs_join':
      return <JoinScreen join={session.join} activityId={activityId} />;
    case 'banned':
      return <BannedScreen />;
    case 'error':
      return <ErrorScreen error={session.error} />;
    case 'ready':
    default:
      return children;
  }
}
