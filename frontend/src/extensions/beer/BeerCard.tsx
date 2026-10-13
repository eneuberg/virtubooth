/**
 * The Beer Cam's line on Start: the board count in Doto digits towards the million
 * (GET /api/x/beer/stats, every 30 s). Test id `beer-count`.
 */
import { useQuery } from '@tanstack/react-query';
import { api, unwrap } from '@/api/client';
import { formatCount, formatFrame } from '@/lib/format';
import type { ExtensionCardProps } from '@/sdk/extension';
import { Skeleton } from '@/ui/Skeleton';

export default function BeerCard(_props: ExtensionCardProps) {
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
