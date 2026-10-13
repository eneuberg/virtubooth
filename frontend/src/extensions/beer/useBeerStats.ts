/**
 * The Beer Cam's numbers: GET /api/x/beer/stats on start, every 30 s while visible and
 * after each beer.
 * - `total`: the board, visible and non-deleted beers: what counts towards the million.
 * - `next`: the number the next beer gets. A beer's number is its photo's seq, the
 *   number "Deine Bilder", the viewer and the saved file show; hidden and deleted beers
 *   keep theirs, so it can run ahead of the board. The guest never sees two numbers
 *   for one beer.
 */
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { api, unwrap } from '@/api/client';
import type { BeerStats } from '@/api/types';
import { subscribeOutboxEvents } from '@/sdk/outbox';
import type { UploadResult } from '@/sdk/upload';

const EVERY_MS = 30_000;
export const BEER_GOAL = 1_000_000;
/** the Start card's query (BeerCard): kept in step with the upload answers */
export const BEER_STATS_KEY = ['beer', 'stats'] as const;

export function useBeerStats() {
  const [total, setTotal] = useState<number | null>(null);
  const [next, setNext] = useState<number | null>(null);
  const [goal, setGoal] = useState<number>(BEER_GOAL);
  const client = useQueryClient();
  // a poll that started before an upload answered may be stale: ignore it
  const epoch = useRef(0);

  const refresh = async () => {
    const started = epoch.current;
    try {
      const stats = await unwrap(api.GET('/api/x/beer/stats'));
      if (started !== epoch.current) return;
      setTotal(stats.total);
      setNext(stats.next_number);
      setGoal(stats.goal);
    } catch {
      // the counter keeps its last value
    }
  };

  /** An upload answer: the board now, and the beer after this one. */
  const note = (result: UploadResult) => {
    epoch.current += 1;
    const { total: board, beer_number: number } = result;
    if (typeof board === 'number') setTotal(board);
    const after = (number ?? result.photo.seq) + 1;
    setNext((current) => Math.max(current ?? 0, after));
    // back on Start, the card shows the board with this beer, not the count from before
    client.setQueryData<BeerStats>(BEER_STATS_KEY, (old) =>
      old ? { ...old, total: board ?? old.total, next_number: Math.max(old.next_number, after) } : old,
    );
  };

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') void refresh();
    }, EVERY_MS);
    const off = subscribeOutboxEvents((e) => {
      if (e.type === 'sent' && e.item.ext === 'beer') note(e.result);
    });
    return () => {
      clearInterval(timer);
      off();
    };
    // refresh/note only touch state setters and the ref
    // oxlint-disable-next-line react/exhaustive-deps
  }, []);

  return { total, next, goal, refresh, note };
}
