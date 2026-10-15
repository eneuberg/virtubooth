/**
 * Tiles ask for their analysis summary one by one (one query each, so an event can
 * refresh exactly the photos it names); the requests of one moment go to the server
 * together, at most MAX_BATCH ids per request. A tile that scrolls in later joins the
 * next batch.
 */
import { fetchAnalysisSummaries } from './api';
import type { PhotoAnalysisSummary } from './types';

export const MAX_BATCH = 100;
/** how long the first ask waits for others (one render's worth of tiles) */
const WINDOW_MS = 25;

interface Waiter {
  resolve: (value: PhotoAnalysisSummary | null) => void;
  reject: (err: unknown) => void;
}

const waiting = new Map<string, Waiter[]>();
let timer: ReturnType<typeof setTimeout> | null = null;

async function flush(): Promise<void> {
  timer = null;
  const ids = [...waiting.keys()].slice(0, MAX_BATCH);
  const batch = ids.map((id) => [id, waiting.get(id) ?? []] as const);
  for (const id of ids) waiting.delete(id);
  if (waiting.size > 0) timer = setTimeout(() => void flush(), 0);
  try {
    const items = await fetchAnalysisSummaries(ids);
    const byId = new Map(items.map((s) => [s.photo_id, s]));
    for (const [id, waiters] of batch) for (const w of waiters) w.resolve(byId.get(id) ?? null);
  } catch (err) {
    for (const [, waiters] of batch) for (const w of waiters) w.reject(err);
  }
}

/** One photo's summary, fetched with the others asked for in the same moment; null: unknown photo. */
export function loadSummary(id: string): Promise<PhotoAnalysisSummary | null> {
  return new Promise((resolve, reject) => {
    const list = waiting.get(id);
    if (list) list.push({ resolve, reject });
    else waiting.set(id, [{ resolve, reject }]);
    timer ??= setTimeout(() => void flush(), WINDOW_MS);
  });
}
