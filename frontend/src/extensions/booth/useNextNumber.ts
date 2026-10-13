/**
 * The number on the Fotobox film edge before a shot: GET /api/x/booth/stats
 * (`next_number`) on start, every 30 s while the tab is visible, and again after each
 * sent photo. An upload answer (`booth_number`) can be newer than the last poll, so the
 * edge shows whichever is further along. Like the Beer Cam's counter, it is a hint:
 * another guest may take the number first, and the print then shows the real one.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { api, unwrap } from '@/api/client';
import { subscribeOutboxEvents } from '@/sdk/outbox';

const STATS_KEY = ['booth', 'stats'] as const;
const EVERY_MS = 30_000;

/** `lastNumber`: the number of this visit's last uploaded photo (null before one). */
export function useNextNumber(lastNumber: number | null): number | null {
  const client = useQueryClient();
  const { data } = useQuery({
    queryKey: STATS_KEY,
    queryFn: () => unwrap(api.GET('/api/x/booth/stats')),
    refetchInterval: EVERY_MS,
    select: (stats) => stats.next_number,
  });

  useEffect(
    () =>
      subscribeOutboxEvents((e) => {
        if (e.type === 'sent' && e.item.ext === 'booth')
          void client.invalidateQueries({ queryKey: STATS_KEY });
      }),
    [client],
  );

  const afterLast = lastNumber === null ? null : lastNumber + 1;
  if (data === undefined) return afterLast;
  return afterLast === null ? data : Math.max(data, afterLast);
}
