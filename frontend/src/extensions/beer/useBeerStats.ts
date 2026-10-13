/**
 * The beer board count: GET /api/x/beer/stats on start, every 30 s while visible and
 * after each beer. `total` counts visible, non-deleted beers (the board), which is the
 * number a guest sees for their beer: never the photo's seq (architecture.md risk 6).
 */
import { useEffect, useRef, useState } from 'react';
import { api, unwrap } from '@/api/client';
import { subscribeOutboxEvents } from '@/sdk/outbox';

const EVERY_MS = 30_000;
export const BEER_GOAL = 1_000_000;

export function useBeerStats() {
  const [total, setTotal] = useState<number | null>(null);
  const [goal, setGoal] = useState<number>(BEER_GOAL);
  // a poll that started before an upload answered may be stale: ignore it
  const epoch = useRef(0);

  const refresh = async () => {
    const started = epoch.current;
    try {
      const stats = await unwrap(api.GET('/api/x/beer/stats'));
      if (started !== epoch.current) return;
      setTotal(stats.total);
      setGoal(stats.goal);
    } catch {
      // the counter keeps its last value
    }
  };

  /** The board count from an upload answer. */
  const note = (value: number) => {
    epoch.current += 1;
    setTotal(value);
  };

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') void refresh();
    }, EVERY_MS);
    const off = subscribeOutboxEvents((e) => {
      if (e.type === 'sent' && e.item.ext === 'beer' && typeof e.result.total === 'number')
        note(e.result.total);
    });
    return () => {
      clearInterval(timer);
      off();
    };
    // refresh/note only touch state setters and the ref
    // oxlint-disable-next-line react/exhaustive-deps
  }, []);

  return { total, goal, refresh, note };
}
