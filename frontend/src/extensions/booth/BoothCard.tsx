/**
 * The Fotobox's line on Start: sample frames through a few filters (static synthetic
 * images) and the number of filters the host has on (GET /api/x/booth/filters, the cache
 * the Fotobox shares: useCatalogue.ts).
 */
import { useQuery } from '@tanstack/react-query';
import { formatNumber } from '@/lib/format';
import type { ExtensionCardProps } from '@/sdk/extension';
import sample1 from './img/sample-1.jpg';
import sample2 from './img/sample-2.jpg';
import sample3 from './img/sample-3.jpg';
import sample4 from './img/sample-4.jpg';
import sample5 from './img/sample-5.jpg';
import { CATALOGUE_REFRESH_MS, fetchFilters, FILTERS_KEY } from './useCatalogue';

const SAMPLES = [sample1, sample2, sample3, sample4, sample5];

export default function BoothCard(_props: ExtensionCardProps) {
  const { data } = useQuery({
    queryKey: FILTERS_KEY,
    queryFn: fetchFilters,
    staleTime: CATALOGUE_REFRESH_MS,
    refetchInterval: CATALOGUE_REFRESH_MS,
  });
  return (
    // the samples shrink (3:4 kept) before the count is cut off on a 320 px phone
    <span className="flex min-w-0 items-end gap-1.5">
      {SAMPLES.map((src) => (
        <img
          key={src}
          src={src}
          alt=""
          width={120}
          height={160}
          loading="lazy"
          decoding="async"
          className="aspect-[3/4] h-auto w-10.5 min-w-0 shrink object-cover lg:w-15"
        />
      ))}
      {data ? (
        <span className="ml-1.5 shrink-0 text-xs text-ink-muted">
          {formatNumber(data.filters.length)}&nbsp;Filter
        </span>
      ) : null}
    </span>
  );
}
