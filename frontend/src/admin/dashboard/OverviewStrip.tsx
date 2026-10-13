import { ChevronRight } from 'lucide-react';
import { Link } from 'react-aria-components';
import { formatNumber } from '@/lib/format';
import { cx } from '@/ui/cx';
import { Skeleton } from '@/ui/Skeleton';
import { useOverview } from './data';
import { freshness, liveStats } from './text';

/**
 * The live overview at a glance (Live screen): six counters in Doto, refreshed every
 * 10 s while visible and on the relevant events. "Alle Zahlen" opens the fuller
 * Übersicht in the manage area.
 */
export function OverviewStrip({ className }: { className?: string }) {
  const { data, isError } = useOverview();
  return (
    <section
      aria-labelledby="vb-overview-title"
      data-testid="overview"
      className={cx('border-b border-line px-4 pt-2.5 pb-2', className)}
    >
      <h2 id="vb-overview-title" className="sr-only">
        Überblick
      </h2>
      {data ? (
        <>
          <dl className="grid grid-cols-3 gap-x-3 gap-y-1.5 md:grid-cols-6">
            {liveStats(data).map((stat) => (
              <div
                key={stat.id}
                className="flex min-w-0 flex-col-reverse"
                data-testid={`overview-${stat.id}`}
              >
                <dt className="truncate text-xs text-ink-muted">{stat.label}</dt>
                <dd className="dots text-dots-sm text-accent-ink">{formatNumber(stat.value)}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-1.5 flex flex-wrap items-center justify-between gap-x-3 text-xs text-ink-muted">
            <span>{freshness(data)}</span>
            <Link
              href="/manage?tab=uebersicht"
              data-testid="overview-more"
              className="inline-flex min-h-11 items-center gap-0.5 font-semibold text-ink no-underline outline-none hover:underline focus-visible:outline-2 focus-visible:outline-focus"
            >
              Alle Zahlen
              <ChevronRight aria-hidden="true" className="size-4" strokeWidth={2.25} />
            </Link>
          </p>
        </>
      ) : isError ? (
        <p className="py-2 text-sm text-ink-muted">Die Zahlen laden gerade nicht. Gleich nochmal.</p>
      ) : (
        <div className="grid grid-cols-3 gap-3 py-1 md:grid-cols-6" aria-hidden="true">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-10" />
          ))}
        </div>
      )}
    </section>
  );
}
