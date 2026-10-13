/**
 * Start (/): the guest pass and help, the party's name, the status slot, the
 * activities as film strips with live lines, "Deine Bilder", and a footer with
 * "Was passiert mit meinen Fotos?" and the party's Instagram account.
 * Phone: one column. Landscape phone: two. Desktop: a 5/7 grid, hero and own photos
 * left, the strips right (docs/overhaul/design/mockups/01-start.html).
 */
import { CircleHelp } from 'lucide-react';
import { useState } from 'react';
import { isApiError } from '@/api/errors';
import { msg } from '@/lib/messages.de';
import { useActivities } from '@/sdk/activities';
import { GuestPass } from '@/sdk/components/GuestPass';
import { StatusSlot } from '@/sdk/components/StatusSlot';
import { Button } from '@/ui/Button';
import { cx } from '@/ui/cx';
import { IconButton } from '@/ui/IconButton';
import { Skeleton } from '@/ui/Skeleton';
import { ToastSlot } from '@/ui/Toast';
import { ActivityCard } from './ActivityCards';
import { HelpSheet, type HelpTopic } from './HelpSheet';
import { InAppHint } from './InAppHint';
import { MyPhotos } from './MyPhotos';

export function Start() {
  const { data, isPending, error, refetch } = useActivities();
  const [help, setHelp] = useState<HelpTopic | 'all' | null>(null);
  const activities = data?.activities ?? [];
  const partyName = data?.partyName ?? '';
  const instagramAccount = data?.instagramAccount ?? '';

  return (
    <main
      data-testid="start"
      className={cx(
        'mx-auto grid max-w-[35rem] content-start gap-7 px-4 pt-[max(0.75rem,env(safe-area-inset-top))] pb-[max(2.5rem,env(safe-area-inset-bottom))]',
        'landscape-phone:max-w-none landscape-phone:grid-cols-2 landscape-phone:gap-x-6 landscape-phone:gap-y-5 landscape-phone:px-[max(1rem,env(safe-area-inset-left))]',
        'lg:max-w-[75rem] lg:grid-cols-[5fr_7fr] lg:gap-x-16 lg:gap-y-8 lg:px-10 lg:pt-8',
      )}
    >
      <header className="flex items-center justify-between gap-3 lg:col-span-2 landscape-phone:col-span-2">
        <GuestPass className="max-w-[calc(100%-3.5rem)]" />
        <IconButton label="Hilfe" icon={CircleHelp} tooltip onPress={() => setHelp('all')} />
      </header>

      <div className="grid content-start gap-4 lg:col-start-1">
        {partyName ? (
          <h1 translate="no" className="text-3xl font-bold break-words">
            {partyName}
          </h1>
        ) : (
          <Skeleton className="h-11 w-3/4" />
        )}
        <StatusSlot />
        <InAppHint />
      </div>

      <nav
        aria-label="Aktivitäten"
        className="grid content-start gap-3 lg:col-start-2 lg:row-span-3 lg:row-start-2 landscape-phone:col-start-2 landscape-phone:row-span-3 landscape-phone:row-start-2"
      >
        {isPending && !error
          ? Array.from({ length: 2 }, (_, i) => (
              <Skeleton key={i} shape="block" className="h-44 rounded-none" />
            ))
          : activities.map((activity) => <ActivityCard key={activity.id} activity={activity} />)}
        {error ? (
          <div className="grid justify-items-start gap-3" data-testid="activities-error">
            <p role="alert">{isApiError(error) ? error.message : msg.generic}</p>
            <Button variant="secondary" size="sm" onPress={() => void refetch()}>
              Erneut laden
            </Button>
          </div>
        ) : !isPending && activities.length === 0 ? (
          <p className="text-ink-muted">Noch ist nichts freigeschaltet. Schau gleich nochmal vorbei.</p>
        ) : null}
      </nav>

      <MyPhotos
        activityTitles={activities.filter((a) => a.uploads).map((a) => a.title)}
        className="lg:col-start-1"
      />

      <footer className="grid content-start justify-items-start gap-2 text-sm lg:col-start-1">
        <button
          type="button"
          onClick={() => setHelp('photos')}
          className="min-h-11 cursor-pointer text-left underline decoration-line-strong underline-offset-4 outline-none hover:decoration-current focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
        >
          Was passiert mit meinen Fotos?
        </button>
        {instagramAccount ? (
          <p className="text-ink-muted">
            Die Gastgeber posten ausgewählte Fotos auf <span translate="no">{instagramAccount}</span>.
          </p>
        ) : null}
      </footer>

      <HelpSheet topic={help} onClose={() => setHelp(null)} instagramAccount={instagramAccount} />
      <ToastSlot />
    </main>
  );
}
