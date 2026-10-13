/**
 * The wall's live connection: one feed snapshot, then the SSE stream after its cursor.
 *
 * - The browser reconnects a dropped stream by itself (server `retry: 3000`, replay by
 *   Last-Event-ID). Every reconnect and every `stream.resync` refetches /feed; events that
 *   arrive while that request runs are applied again on top of the new snapshot, so a
 *   removal never comes back from a slightly older snapshot.
 * - A stream the browser gave up on (an error answer) asks /session what is wrong:
 *   401 → login screen, 409 → no password set; anything else retries after 2 s, 4 s, …
 *   up to 30 s (feed first, then a new stream).
 * - `bye` (password changed, logged out) closes everything and shows the login screen.
 */
import { API, WallApiError } from './client';
import { EVENT_TYPES, type WallCursor, type WallEvent, type WallEventType, type WallFeed } from './types';

export type StreamStatus = 'connecting' | 'live' | 'offline';
export type AuthProblem = 'login' | 'nopassword';

export interface StreamHandlers {
  /** a complete snapshot: the first one and after every reconnect/resync */
  feed(feed: WallFeed): void;
  /** a live event (never `bye` or `stream.resync`: the stream handles those) */
  event(event: WallEvent): void;
  status(status: StreamStatus): void;
  /** the stream stopped for good: show the login or the no-password screen */
  auth(problem: AuthProblem): void;
}

/** The parts of EventSource the stream uses (tests pass a fake). */
export interface EventSourceLike {
  readonly readyState: number;
  /** 'open', 'error' and the named events */
  addEventListener(type: string, listener: (ev: MessageEvent<string>) => void): void;
  close(): void;
}

export interface StreamDeps {
  fetchFeed(): Promise<WallFeed>;
  sessionStatus(): Promise<number>;
  createSource(url: string): EventSourceLike;
}

export const STREAM_URL = `${API}/stream`;
export const BACKOFF_MIN_MS = 2_000;
export const BACKOFF_MAX_MS = 30_000;
const CLOSED = 2;

export interface WallStream {
  close(): void;
}

function streamUrl(cursor: WallCursor): string {
  return cursor === null || cursor === ''
    ? STREAM_URL
    : `${STREAM_URL}?since=${encodeURIComponent(String(cursor))}`;
}

function parse(type: WallEventType, raw: string): WallEvent | null {
  try {
    const data: unknown = raw ? JSON.parse(raw) : {};
    if (typeof data !== 'object' || data === null) return null;
    // oxlint-disable-next-line typescript/no-unsafe-type-assertion -- the contract types each event
    return { type, data } as WallEvent;
  } catch {
    return null;
  }
}

export function openWallStream(handlers: StreamHandlers, deps: StreamDeps): WallStream {
  let source: EventSourceLike | null = null;
  let stopped = false;
  let backoff = BACKOFF_MIN_MS;
  let retryTimer: ReturnType<typeof setTimeout> | undefined;
  let syncing = false;
  let buffer: WallEvent[] = [];

  function stop(): void {
    stopped = true;
    clearTimeout(retryTimer);
    source?.close();
    source = null;
  }

  function scheduleRetry(): void {
    clearTimeout(retryTimer);
    retryTimer = setTimeout(() => void start(), backoff);
    backoff = Math.min(backoff * 2, BACKOFF_MAX_MS);
  }

  /** Something failed: ask /session whether it is the login, else try again later. */
  async function diagnose(): Promise<void> {
    let status = 0;
    try {
      status = await deps.sessionStatus();
    } catch {
      status = 0;
    }
    if (stopped) return;
    if (status === 401 || status === 409) {
      stop();
      handlers.auth(status === 401 ? 'login' : 'nopassword');
      return;
    }
    handlers.status('offline');
    scheduleRetry();
  }

  async function start(): Promise<void> {
    if (stopped) return;
    let feed: WallFeed;
    try {
      feed = await deps.fetchFeed();
    } catch (err) {
      if (stopped) return;
      if (err instanceof WallApiError && (err.status === 401 || err.status === 409)) {
        await diagnose();
      } else {
        handlers.status('offline');
        scheduleRetry();
      }
      return;
    }
    if (stopped) return;
    handlers.feed(feed);
    connect(feed.cursor);
  }

  async function resync(): Promise<void> {
    if (syncing || stopped) return;
    syncing = true;
    buffer = [];
    try {
      const feed = await deps.fetchFeed();
      if (stopped) return;
      handlers.feed(feed);
      for (const event of buffer) handlers.event(event);
    } catch (err) {
      if (!stopped && err instanceof WallApiError && err.status === 401) await diagnose();
      // otherwise the stream is still there; the next reconnect tries again
    } finally {
      syncing = false;
      buffer = [];
    }
  }

  function connect(cursor: WallCursor): void {
    const es = deps.createSource(streamUrl(cursor));
    source = es;
    let opens = 0;
    es.addEventListener('open', () => {
      if (es !== source) return;
      opens += 1;
      backoff = BACKOFF_MIN_MS;
      handlers.status('live');
      if (opens > 1) void resync();
    });
    es.addEventListener('error', () => {
      if (es !== source) return;
      handlers.status('offline');
      if (es.readyState === CLOSED) {
        es.close();
        source = null;
        void diagnose();
      }
    });
    for (const type of EVENT_TYPES) {
      es.addEventListener(type, (message) => {
        if (es !== source || stopped) return;
        const event = parse(type, message.data);
        if (!event) return;
        if (event.type === 'bye') {
          stop();
          handlers.auth('login');
        } else if (event.type === 'stream.resync') {
          void resync();
        } else if (syncing) {
          buffer.push(event);
        } else {
          handlers.event(event);
        }
      });
    }
  }

  handlers.status('connecting');
  void start();
  return { close: stop };
}

/** The browser's EventSource and the real endpoints. */
export function browserStreamDeps(
  fetchFeed: () => Promise<WallFeed>,
  sessionStatus: () => Promise<number>,
): StreamDeps {
  return {
    fetchFeed,
    sessionStatus,
    createSource: (url) => new EventSource(url, { withCredentials: false }),
  };
}
