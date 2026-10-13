import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { feed, photo } from '../fixtures.test-util';
import { WallApiError } from './client';
import {
  openWallStream,
  STREAM_URL,
  type EventSourceLike,
  type StreamDeps,
  type StreamStatus,
} from './stream';
import type { WallEvent, WallFeed } from './types';

type Listener = (ev: MessageEvent<string>) => void;

class FakeSource implements EventSourceLike {
  readyState = 0;
  closed = false;
  readonly url: string;
  private readonly listeners = new Map<string, Listener[]>();
  constructor(url: string) {
    this.url = url;
  }
  addEventListener(type: string, listener: Listener): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }
  close() {
    this.closed = true;
    this.readyState = 2;
  }
  private emit(type: string, data = '') {
    for (const l of this.listeners.get(type) ?? []) l(new MessageEvent(type, { data }));
  }
  open() {
    this.readyState = 1;
    this.emit('open');
  }
  send(type: string, data: unknown) {
    this.emit(type, JSON.stringify(data));
  }
  /** the browser retries by itself */
  drop() {
    this.readyState = 0;
    this.emit('error');
  }
  /** the browser gave up (an error answer) */
  fail() {
    this.readyState = 2;
    this.emit('error');
  }
}

function deferred<T>() {
  const box: { resolve: (value: T) => void } = { resolve: () => undefined };
  const promise = new Promise<T>((r) => {
    box.resolve = r;
  });
  return { promise, resolve: (value: T) => box.resolve(value) };
}

function setup(opts: { feeds?: (() => Promise<WallFeed>)[]; session?: number[] } = {}) {
  const sources: FakeSource[] = [];
  const feeds = [...(opts.feeds ?? [])];
  const sessions = [...(opts.session ?? [])];
  const got = {
    feeds: [] as WallFeed[],
    events: [] as WallEvent[],
    statuses: [] as StreamStatus[],
    auth: [] as string[],
  };
  const fetchFeed = vi.fn<() => Promise<WallFeed>>(() =>
    (feeds.shift() ?? (() => Promise.resolve(feed([photo(1)]))))(),
  );
  const sessionStatus = vi.fn<() => Promise<number>>(() => Promise.resolve(sessions.shift() ?? 200));
  const deps: StreamDeps = {
    fetchFeed,
    sessionStatus,
    createSource: (url) => {
      const s = new FakeSource(url);
      sources.push(s);
      return s;
    },
  };
  const stream = openWallStream(
    {
      feed: (f) => got.feeds.push(f),
      event: (e) => got.events.push(e),
      status: (s) => got.statuses.push(s),
      auth: (p) => got.auth.push(p),
    },
    deps,
  );
  return { stream, sources, fetchFeed, sessionStatus, got };
}

const flush = () => vi.advanceTimersByTimeAsync(0);

describe('openWallStream', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('loads the feed, then streams after its cursor', async () => {
    const { sources, got } = setup();
    await flush();
    expect(got.feeds).toHaveLength(1);
    expect(sources[0]!.url).toBe(`${STREAM_URL}?since=42`);
    sources[0]!.open();
    sources[0]!.send('photo.add', { photo: photo(2) });
    sources[0]!.send('photo.remove', { ids: ['p1'] });
    expect(got.events.map((e) => e.type)).toEqual(['photo.add', 'photo.remove']);
    expect(got.statuses).toEqual(['connecting', 'live']);
  });

  it('refetches the feed on a reconnect and replays what came in meanwhile', async () => {
    const slow = deferred<WallFeed>();
    const { sources, got, fetchFeed } = setup({
      feeds: [() => Promise.resolve(feed([photo(1)])), () => slow.promise],
    });
    await flush();
    const es = sources[0]!;
    es.open();
    es.drop();
    expect(got.statuses.at(-1)).toBe('offline');
    es.open(); // the browser reconnected
    expect(fetchFeed).toHaveBeenCalledTimes(2);
    es.send('photo.remove', { ids: ['p2'] });
    expect(got.events).toEqual([]); // held back until the snapshot is in
    slow.resolve(feed([photo(1), photo(2)]));
    await flush();
    expect(got.feeds).toHaveLength(2);
    expect(got.events.map((e) => e.type)).toEqual(['photo.remove']);
    expect(sources).toHaveLength(1);
  });

  it('stream.resync refetches the feed', async () => {
    const { sources, got } = setup();
    await flush();
    sources[0]!.open();
    sources[0]!.send('stream.resync', {});
    await flush();
    expect(got.feeds).toHaveLength(2);
    expect(got.events).toEqual([]);
  });

  it('a refused stream with 401 shows the login', async () => {
    const { stream, sources, got } = setup({ session: [401] });
    await flush();
    sources[0]!.fail();
    await flush();
    expect(got.auth).toEqual(['login']);
    expect(sources[0]!.closed).toBe(true);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(sources).toHaveLength(1);
    stream.close();
  });

  it('409 shows the no-password screen', async () => {
    const { sources, got } = setup({ session: [409] });
    await flush();
    sources[0]!.fail();
    await flush();
    expect(got.auth).toEqual(['nopassword']);
  });

  it('a 401 feed asks /session too', async () => {
    const { got, sessionStatus } = setup({
      feeds: [() => Promise.reject(new WallApiError(401, 'wall_login_required', 'x'))],
      session: [409],
    });
    await flush();
    expect(sessionStatus).toHaveBeenCalledTimes(1);
    expect(got.auth).toEqual(['nopassword']);
  });

  it('other failures retry with backoff 2 s, 4 s, 8 s … 30 s', async () => {
    const { sources, fetchFeed } = setup({ session: [200, 200, 200, 200, 200, 200, 200] });
    await flush();
    const delays = [2000, 4000, 8000, 16000, 30000, 30000];
    // oxlint-disable no-await-in-loop -- fake timers advance one retry after the other
    for (const [i, delay] of delays.entries()) {
      sources[i]!.fail();
      await flush();
      await vi.advanceTimersByTimeAsync(delay - 1);
      expect(sources).toHaveLength(i + 1);
      await vi.advanceTimersByTimeAsync(1);
      expect(sources).toHaveLength(i + 2);
    }
    // oxlint-enable no-await-in-loop
    expect(fetchFeed).toHaveBeenCalledTimes(delays.length + 1);
  });

  it('an open stream resets the backoff', async () => {
    const { sources } = setup({ session: [200, 200] });
    await flush();
    sources[0]!.fail();
    await flush();
    await vi.advanceTimersByTimeAsync(2000);
    sources[1]!.open();
    sources[1]!.fail();
    await flush();
    await vi.advanceTimersByTimeAsync(2000);
    expect(sources).toHaveLength(3);
  });

  it('bye closes everything and shows the login', async () => {
    const { sources, got } = setup();
    await flush();
    sources[0]!.open();
    sources[0]!.send('bye', { reason: 'password' });
    expect(sources[0]!.closed).toBe(true);
    expect(got.auth).toEqual(['login']);
    sources[0]!.send('photo.add', { photo: photo(5) });
    expect(got.events).toEqual([]);
  });

  it('close() stops for good', async () => {
    const { stream, sources, got } = setup();
    await flush();
    stream.close();
    expect(sources[0]!.closed).toBe(true);
    sources[0]!.send('photo.add', { photo: photo(5) });
    expect(got.events).toEqual([]);
  });
});
