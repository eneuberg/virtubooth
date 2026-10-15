/**
 * The activities on Start as cards: the title, one line of copy and a live line, on
 * the theme's raised surface with a soft light edge (the old film strips' sprocket rows
 * are gone from here; the film edge stays the upload progress). GET /api/extensions has no numbers, so each
 * activity brings its own live line: the `card` slot of its frontend extension module
 * (src/sdk/extension.ts), loaded lazily (the Beer Cam's counter, the Fotobox's sample
 * frames). Activities without one show their tagline only. The whole strip is the link
 * (test id `tile-<id>`).
 */
import { ChevronRight } from 'lucide-react';
import { lazy, Suspense } from 'react';
import { Link } from 'react-aria-components';
import { listExtensions } from '@/extensions/registry';
import { quietWhileLeaving } from '@/lib/boot';
import type { Activity } from '@/sdk/activities';
import { cx } from '@/ui/cx';
import { Skeleton } from '@/ui/Skeleton';
import { tidy } from './copy';

/** The extensions' live lines: one lazy component each, created once at module load
 * (never during render), like the pages in routes.tsx. */
const cards = new Map(
  listExtensions().flatMap((ext) => {
    if (!ext.card) return [];
    const Card = lazy(quietWhileLeaving(ext.card));
    return [[ext.id, (id: string) => <Card id={id} />] as const];
  }),
);

const emojis = new Map(listExtensions().flatMap((ext) => (ext.emoji ? [[ext.id, ext.emoji] as const] : [])));

export function ActivityCard({ activity }: { activity: Activity }) {
  const live = cards.get(activity.id);
  const emoji = emojis.get(activity.id) ?? '✨';
  const tagline = tidy(activity.tagline);
  return (
    <Link
      href={activity.href}
      data-testid={`tile-${activity.id}`}
      className={cx(
        'vb-activity group relative block overflow-hidden rounded-card bg-surface-raised text-ink no-underline outline-none',
        'transition-[transform,background-color] duration-(--duration-quick) ease-out hover:bg-surface-hover pressed:scale-[0.985]',
        'focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-focus',
      )}
    >
      <span className="grid gap-1 px-5 pt-4 pb-1 lg:px-6 lg:pt-5">
        <span className="flex items-center justify-between gap-3">
          <span className="flex min-w-0 items-center gap-3">
            <span aria-hidden="true" className="vb-activity-emoji">
              {emoji}
            </span>
            <span translate="no" className="text-2xl font-bold">
              {activity.title}
            </span>
          </span>
          <span
            aria-hidden="true"
            className="grid size-9 shrink-0 place-items-center rounded-full bg-accent-tint text-accent-ink transition-transform duration-(--duration-quick) ease-out group-hover:translate-x-0.5"
          >
            <ChevronRight className="size-5" strokeWidth={2} />
          </span>
        </span>
        <span className="text-sm text-ink-muted">{tagline}</span>
      </span>
      {live ? (
        <span className="block px-5 pt-3 pb-5 lg:px-6 lg:pb-6">
          <Suspense fallback={<Skeleton shape="counter" />}>{live(activity.id)}</Suspense>
        </span>
      ) : (
        <span className="block h-4" />
      )}
    </Link>
  );
}
