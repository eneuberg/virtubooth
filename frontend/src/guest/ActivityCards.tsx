/**
 * The activities on Start as film strips: sprocket holes top and bottom, the title,
 * one line of copy and a live line. GET /api/extensions has no numbers, so each
 * known activity reads its own: the Beer Cam its counter (GET /api/x/beer/stats,
 * Doto digits towards the million), the Fotobox its filter catalogue
 * (GET /api/x/booth/filters: sample frames and the count). Other activities show
 * their tagline only. The whole strip is the link (test id `tile-<id>`).
 *
 * TODO(INT): the live line belongs to the extension module (a `card` slot next to
 * `load` in sdk/extension.ts, AC). Kept here until that exists.
 */
import { useQuery } from '@tanstack/react-query';
import { ChevronRight } from 'lucide-react';
import type { ComponentType } from 'react';
import { Link } from 'react-aria-components';
import { api, unwrap } from '@/api/client';
import { formatCount, formatFrame, formatNumber } from '@/lib/format';
import type { Activity } from '@/sdk/activities';
import { cx } from '@/ui/cx';
import { FilmEdge } from '@/ui/FilmEdge';
import { Skeleton } from '@/ui/Skeleton';
import { tidy } from './copy';
import sample1 from './img/sample-1.jpg';
import sample2 from './img/sample-2.jpg';
import sample3 from './img/sample-3.jpg';
import sample4 from './img/sample-4.jpg';
import sample5 from './img/sample-5.jpg';

const SAMPLES = [sample1, sample2, sample3, sample4, sample5];

function BeerLine() {
  const { data } = useQuery({
    queryKey: ['beer', 'stats'],
    queryFn: () => unwrap(api.GET('/api/x/beer/stats')),
    refetchInterval: 30_000,
  });
  if (!data) return <Skeleton shape="counter" />;
  return (
    <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <span className="dots text-dots-md text-accent" data-testid="beer-count">
        {formatFrame(data.total)}
      </span>
      <span className="text-xs text-ink-muted">von {formatCount(data.goal)} Bieren</span>
    </span>
  );
}

function BoothLine() {
  const { data } = useQuery({
    queryKey: ['booth', 'filters'],
    queryFn: () => unwrap(api.GET('/api/x/booth/filters')),
    staleTime: Infinity,
  });
  return (
    <span className="flex items-end gap-1.5">
      {SAMPLES.map((src) => (
        <img
          key={src}
          src={src}
          alt=""
          width={120}
          height={160}
          loading="lazy"
          decoding="async"
          className="h-14 w-10.5 object-cover lg:h-20 lg:w-15"
        />
      ))}
      {data ? (
        <span className="ml-1.5 text-xs text-ink-muted">{formatNumber(data.filters.length)}&nbsp;Filter</span>
      ) : null}
    </span>
  );
}

const LIVE: Record<string, ComponentType> = { beer: BeerLine, booth: BoothLine };

export function ActivityCard({ activity }: { activity: Activity }) {
  const Live = LIVE[activity.id];
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
      {Live ? (
        <span className="block px-4 pt-2 pb-3 lg:px-6 lg:pb-4">
          <Live />
        </span>
      ) : (
        <span className="block h-2" />
      )}
      <FilmEdge holes="bottom" className="bg-transparent" />
    </Link>
  );
}
