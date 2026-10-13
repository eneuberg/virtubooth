/**
 * Where the event stream must start. Every `/api/admin/*` answer carries
 * `X-VB-Event-Id: <epoch>-<n>`, the stream position before that request read
 * anything (contracts/api.md §4). The stream opens with the EARLIEST position of
 * the page's first fetches, so whatever happened while they were in flight is
 * replayed, never lost. (Replays are harmless: the cache reducers are idempotent.)
 */

interface Cursor {
  epoch: string;
  n: number;
}

const RE = /^([0-9a-f]+)-(\d+)$/;

let earliest: Cursor | null = null;
const listeners = new Set<() => void>();

export function parseEventId(raw: string | null | undefined): Cursor | null {
  const m = raw ? RE.exec(raw.trim()) : null;
  if (!m?.[1] || m[2] === undefined) return null;
  return { epoch: m[1], n: Number(m[2]) };
}

/** Record the position an answer reports. */
export function noteEventId(raw: string | null | undefined): void {
  const c = parseEventId(raw);
  if (!c) return;
  // another epoch: the server restarted in between, only the new numbers count
  if (earliest && earliest.epoch === c.epoch && earliest.n <= c.n) return;
  earliest = c;
  for (const fn of listeners) fn();
}

/** `<epoch>-<n>` to pass as `?since=`, or null before the first answer. */
export function streamCursor(): string | null {
  return earliest ? `${earliest.epoch}-${earliest.n}` : null;
}

export function onCursor(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Tests only. */
export function resetCursor(): void {
  earliest = null;
}
