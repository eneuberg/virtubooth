/**
 * The user page's „Statistik“: online time and visits (the guest page reports every
 * minute while it is visible), the QR code it joined through, photos per activity,
 * hidden and deleted ones, first and last photo, since when the guest is here and
 * when it was last seen.
 *
 * The counts are the server's (`UserDetailOut.stats`). The event stream patches the
 * page's photos in place, not these counts, so a change to the photos refetches the
 * page's data (once, a second later), and the numbers match the photos again.
 */
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, type ReactNode } from 'react';
import { Link } from 'react-aria-components';
import type { AdminExtension, AdminPhoto, UserDetail } from '@/api/types';
import { formatDateTime, formatNumber, formatRelative, formatTime } from '@/lib/format';
import { HOST_CODE } from '../hostGuest/marks';
import { qk } from '../store/keys';
import { onlineText, photoCountsText } from './statsText';

const FOLLOW_MS = 1_000;

const LINK =
  'font-semibold text-ink underline decoration-line-strong underline-offset-3 outline-none hover:decoration-ink focus-visible:outline-2 focus-visible:outline-focus';

/** „Gorilla 2“ (to the code's sheet), „Gorilla 2 (gelöscht)“, or „unbekannt“. */
function CodeValue({ code, host }: { code: UserDetail['user']['code']; host: boolean }) {
  if (host) return <span className="text-ink-muted">{HOST_CODE} beigetreten</span>;
  if (!code) return <span className="text-ink-muted">unbekannt</span>;
  return (
    <>
      <Link href={`/manage?tab=qr&code=${code.id}`} className={LINK} data-testid="user-code-link">
        <span translate="no">{code.name}</span>
      </Link>
      {code.active ? null : <span className="text-ink-muted"> (gelöscht)</span>}
    </>
  );
}

/** Refetch the user page when its photos changed through the event stream. */
function useCountsFollowPhotos(userId: number, photos: ReadonlyArray<AdminPhoto>): void {
  const qc = useQueryClient();
  const loaded = useRef({ userId, photos });
  useEffect(() => {
    const last = loaded.current;
    loaded.current = { userId, photos };
    if (last.userId !== userId || last.photos === photos) return undefined;
    const timer = window.setTimeout(() => {
      void qc.invalidateQueries({ queryKey: qk.user(userId), exact: true });
    }, FOLLOW_MS);
    return () => window.clearTimeout(timer);
  }, [qc, userId, photos]);
}

function Moment({ iso, children }: { iso: string; children: ReactNode }) {
  return (
    <time dateTime={iso} title={formatDateTime(iso)}>
      {children}
    </time>
  );
}

export function UserStats({
  detail,
  extensions,
}: {
  detail: UserDetail;
  extensions: ReadonlyMap<string, AdminExtension>;
}) {
  const { user, stats } = detail;
  useCountsFollowPhotos(user.id, detail.photos);
  const rows: Array<{ label: string; value: ReactNode; testId?: string }> = [
    {
      label: 'Online',
      testId: 'user-online',
      value: (
        <>
          {onlineText(user.online_seconds, user.online_sessions)}
          {user.online_now ? (
            <span
              className="ml-2 inline-flex items-baseline gap-1.5 whitespace-nowrap"
              title="Seite gerade offen"
            >
              <span aria-hidden="true" className="size-2 shrink-0 translate-y-[-1px] rounded-full bg-ok" />
              gerade online
            </span>
          ) : null}
        </>
      ),
    },
    { label: 'QR-Code', testId: 'user-code', value: <CodeValue code={user.code} host={user.is_host} /> },
    {
      label: 'Fotos',
      testId: 'user-photo-counts',
      value: photoCountsText(stats.photos, stats.by_activity, extensions),
    },
  ];
  if (stats.hidden > 0) rows.push({ label: 'Ausgeblendet', value: formatNumber(stats.hidden) });
  if (stats.deleted > 0) rows.push({ label: 'Gelöscht', value: formatNumber(stats.deleted) });
  if (stats.first_photo_at) {
    rows.push({
      label: 'Erstes Foto',
      value: <Moment iso={stats.first_photo_at}>{formatTime(stats.first_photo_at)}</Moment>,
    });
  }
  if (stats.last_photo_at) {
    rows.push({
      label: 'Letztes Foto',
      value: <Moment iso={stats.last_photo_at}>{formatTime(stats.last_photo_at)}</Moment>,
    });
  }
  rows.push(
    { label: 'Dabei seit', value: <Moment iso={user.created_at}>{formatTime(user.created_at)}</Moment> },
    {
      label: 'Zuletzt gesehen',
      value: <Moment iso={user.last_seen_at}>{formatRelative(user.last_seen_at)}</Moment>,
    },
  );

  return (
    <section aria-labelledby="user-stats-title" className="grid gap-3" data-testid="user-stats">
      <h2 id="user-stats-title" className="text-lg font-bold">
        Statistik
      </h2>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-6 gap-y-1.5 text-md sm:grid-cols-[10rem_minmax(0,1fr)]">
        {rows.map((row) => (
          <div key={row.label} className="contents">
            <dt className="text-ink-muted">{row.label}</dt>
            <dd className="min-w-0 break-words tabular" data-testid={row.testId}>
              {row.value}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
