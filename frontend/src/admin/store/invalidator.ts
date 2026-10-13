/**
 * Collects query keys to refetch and flushes them together, at most once per window.
 * A throttle, not a debounce: during a steady stream of events (a busy party) it still
 * flushes every `ms`, instead of waiting for a quiet moment that never comes.
 */
import type { QueryClient, QueryKey } from '@tanstack/react-query';

export interface Invalidator {
  invalidate: (keys: ReadonlyArray<QueryKey>) => void;
  /** refetch everything collected so far, now */
  flush: () => void;
  dispose: () => void;
}

export function createInvalidator(qc: QueryClient, ms = 600): Invalidator {
  const pending = new Map<string, QueryKey>();
  let timer: ReturnType<typeof setTimeout> | null = null;

  const flush = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
    const keys = [...pending.values()];
    pending.clear();
    for (const queryKey of keys) void qc.invalidateQueries({ queryKey });
  };

  return {
    invalidate(keys) {
      for (const key of keys) pending.set(JSON.stringify(key), key);
      if (timer === null && pending.size > 0) timer = setTimeout(flush, ms);
    },
    flush,
    dispose() {
      if (timer !== null) clearTimeout(timer);
      timer = null;
      pending.clear();
    },
  };
}
