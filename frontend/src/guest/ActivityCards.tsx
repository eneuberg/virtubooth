/**
 * The activities on Start as film strips: sprocket holes top and bottom, the title,
 * one line of copy and a live line. GET /api/extensions has no numbers, so each
 * activity brings its own live line: the `card` slot of its frontend extension module
 * (src/sdk/extension.ts), loaded lazily (the Beer Cam's counter, the Fotobox's sample
 * frames). Activities without one show their tagline only. The whole strip is the link
 * (test id `tile-<id>`).
 */
import { ChevronRight } from 'lucide-react';
import { lazy, Suspense } from 'react';
import { Link } from 'react-aria-components';
import { listExtensions } from '@/extensions/registry';
import type { Activity } from '@/sdk/activities';
import { cx } from '@/ui/cx';
import { FilmEdge } from '@/ui/FilmEdge';
import { Skeleton } from '@/ui/Skeleton';
import { tidy } from './copy';

/** The extensions' live lines: one lazy component each, created once at module load
 * (never during render), like the pages in routes.tsx. */
const cards = new Map(
  listExtensions().flatMap((ext) => {
    if (!ext.card) return [];
    const Card = lazy(ext.card);
    return [[ext.id, (id: string) => <Card id={id} />] as const];
  }),
);

export function ActivityCard({ activity }: { activity: Activity }) {
  const live = cards.get(activity.id);
  const tagline = tidy(activity.tagline);
  return (
    <Link
      href={activity.href}
      data-testid={`tile-${activity.id}`}
      className={cx(
        'group block bg-surface-sunk text-ink no-underline outline-none',
        'transition-[transform] duration-(--duration-press) pressed:scale-[0.99]',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
      )}
    >
      <FilmEdge holes="top" className="bg-transparent" />
      <span className="grid gap-1 px-4 pt-3 pb-1 lg:px-6 lg:pt-4">
        <span className="flex items-center justify-between gap-3">
          <span translate="no" className="text-xl font-bold">
            {activity.title}
          </span>
          <ChevronRight
            aria-hidden="true"
            className="size-6 shrink-0 transition-[transform,color] duration-(--duration-quick) group-hover:translate-x-1 group-hover:text-accent-ink"
            strokeWidth={2}
          />
        </span>
        <span className="text-sm text-ink-muted">{tagline}</span>
      </span>
      {live ? (
        <span className="block px-4 pt-2 pb-3 lg:px-6 lg:pb-4">
          <Suspense fallback={<Skeleton shape="counter" />}>{live(activity.id)}</Suspense>
        </span>
      ) : (
        <span className="block h-2" />
      )}
      <FilmEdge holes="bottom" className="bg-transparent" />
    </Link>
  );
}
