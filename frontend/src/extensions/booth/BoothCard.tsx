/**
 * The Fotobox's line on Start: sample frames through a few filters (static synthetic
 * images) and the number of filters (GET /api/x/booth/filters, the cache the Fotobox
 * shares: useCatalogue.ts).
 */
import { useQuery } from '@tanstack/react-query';
import { api, unwrap } from '@/api/client';
import { formatNumber } from '@/lib/format';
import type { ExtensionCardProps } from '@/sdk/extension';
import sample1 from './img/sample-1.jpg';
import sample2 from './img/sample-2.jpg';
import sample3 from './img/sample-3.jpg';
import sample4 from './img/sample-4.jpg';
import sample5 from './img/sample-5.jpg';

const SAMPLES = [sample1, sample2, sample3, sample4, sample5];

export default function BoothCard(_props: ExtensionCardProps) {
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
