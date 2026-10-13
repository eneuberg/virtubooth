import { QueryClient } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AdminEventsOptions } from '@/api/events';
import type { ConnectionStatus } from '@/ui/ConnectionIndicator';
import { noteEventId, onCursor, resetCursor, streamCursor } from './cursor';
import { qk } from './keys';
import { OPEN_AT_LATEST_MS, POLL_MS, REOPEN_MS, startAdminEvents, type StreamDeps } from './stream';

class FakeDoc extends EventTarget {
  visibilityState: DocumentVisibilityState = 'visible';
}

/** a page whose load event has not fired yet */
class LoadingDoc extends FakeDoc {
  readyState: DocumentReadyState = 'interactive';
}

function setup(overrides: Partial<StreamDeps> = {}) {
  const qc = new QueryClient();
  const opened: AdminEventsOptions[] = [];
  const closed: number[] = [];
  const statuses: ConnectionStatus[] = [];
  const doc = new FakeDoc();
  const win = new EventTarget();
  const deps: StreamDeps = {
    open: (options) => {
      const n = opened.push(options);
      return { close: () => closed.push(n) };
    },
    checkSession: vi.fn<() => Promise<boolean>>(() => Promise.resolve(true)),
    onLoggedOut: vi.fn<() => void>(),
    setStatus: (s) => statuses.push(s),
    cursor: streamCursor,
    onCursor,
    isOnline: () => true,
    target: doc,
    win,
    ...overrides,
  };
  const stop = startAdminEvents(qc, deps);
  return { qc, deps, opened, closed, statuses, doc, win, stop };
}

describe('startAdminEvents', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    resetCursor();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('opens at the earliest X-VB-Event-Id of the first answers', () => {
    const { opened, stop } = setup();
    expect(opened).toHaveLength(0);
    noteEventId('abcd1234-7');
    expect(opened).toHaveLength(1);
    expect(opened[0]?.since).toBe('abcd1234-7');
    noteEventId('abcd1234-3'); // an earlier answer arriving later does not reopen
    expect(opened).toHaveLength(1);
    stop();
  });

  it('keeps the earliest cursor; another epoch (restart) replaces it', () => {
    noteEventId('abcd1234-9');
    noteEventId('abcd1234-4');
    expect(streamCursor()).toBe('abcd1234-4');
    noteEventId('ffff0000-2');
    expect(streamCursor()).toBe('ffff0000-2');
  });

  it('waits for the first fetches to settle, and opens anyway after a while', () => {
    const { qc, opened, stop } = setup();
    void qc.prefetchQuery({ queryKey: ['admin', 'slow'], queryFn: () => new Promise(() => undefined) });
    noteEventId('abcd1234-1');
    expect(opened).toHaveLength(0);
    vi.advanceTimersByTime(OPEN_AT_LATEST_MS);
    expect(opened).toHaveLength(1);
    stop();
  });

  it('applies events and resumes from the last event id after a reopen', () => {
    const { qc, opened, stop } = setup();
    noteEventId('abcd1234-1');
    const stopState = { enabled: true, since: null, by: null };
    opened[0]?.onEvent({ type: 'settings.upload_stop', data: { upload_stop: stopState }, id: 'abcd1234-2' });
    expect(qc.getQueryData(qk.uploadStop)).toEqual(stopState);
    opened[0]?.onStatus?.('closed');
    return vi.waitFor(() => {
      vi.advanceTimersByTime(REOPEN_MS);
      expect(opened).toHaveLength(2);
      expect(opened[1]?.since).toBe('abcd1234-2');
      stop();
    });
  });

  it('waits for the page load event before it opens (Firefox: the stream would keep the page loading)', () => {
    const doc = new LoadingDoc();
    const { opened, win, stop } = setup({ target: doc });
    noteEventId('abcd1234-1');
    vi.advanceTimersByTime(OPEN_AT_LATEST_MS * 2);
    expect(opened).toHaveLength(0);
    doc.readyState = 'complete';
    win.dispatchEvent(new Event('load'));
    expect(opened).toHaveLength(1);
    expect(opened[0]?.since).toBe('abcd1234-1');
    stop();
  });

  it('opens nothing once the page is going, even when the first answers come late', () => {
    const { opened, win, stop } = setup();
    win.dispatchEvent(new Event('pagehide'));
    noteEventId('abcd1234-1');
    vi.advanceTimersByTime(OPEN_AT_LATEST_MS * 2);
    expect(opened).toHaveLength(0);
    win.dispatchEvent(Object.assign(new Event('pageshow'), { persisted: true }));
    expect(opened).toHaveLength(1);
    stop();
  });

  it('closes the stream when the page goes (no error, no polling) and reopens from the bfcache', () => {
    const { qc, opened, closed, statuses, win, stop } = setup();
    noteEventId('abcd1234-1');
    opened[0]?.onStatus?.('live');
    opened[0]?.onEvent({ type: 'stream.resync', data: { reason: 'gap' }, id: 'abcd1234-5' });
    const spy = vi.spyOn(qc, 'invalidateQueries');
    win.dispatchEvent(new Event('pagehide'));
    expect(closed).toEqual([1]);
    opened[0]?.onStatus?.('closed'); // what the old handle says while closing
    vi.advanceTimersByTime(POLL_MS * 2 + REOPEN_MS);
    expect(opened).toHaveLength(1);
    expect(statuses.at(-1)).toBe('live');
    spy.mockClear();
    win.dispatchEvent(new Event('pageshow')); // a normal load: nothing to do
    expect(opened).toHaveLength(1);
    win.dispatchEvent(Object.assign(new Event('pageshow'), { persisted: true }));
    expect(opened).toHaveLength(2);
    expect(opened[1]?.since).toBe('abcd1234-5');
    expect(spy).toHaveBeenCalledWith({ queryKey: qk.all, refetchType: 'active' });
    stop();
  });

  it('polls while the stream is down and stops once it is live again', () => {
    const { qc, opened, statuses, stop } = setup();
    noteEventId('abcd1234-1');
    const spy = vi.spyOn(qc, 'invalidateQueries');
    opened[0]?.onStatus?.('live');
    opened[0]?.onStatus?.('reconnecting');
    expect(statuses.at(-1)).toBe('reconnecting');
    vi.advanceTimersByTime(POLL_MS * 2);
    expect(spy).toHaveBeenCalledWith({ queryKey: qk.all, refetchType: 'active' });
    spy.mockClear();
    opened[0]?.onStatus?.('live');
    expect(statuses.at(-1)).toBe('live');
    vi.advanceTimersByTime(POLL_MS * 2);
    expect(spy).not.toHaveBeenCalled();
    stop();
  });

  it('a closed stream checks the session: gone means the login page', async () => {
    const onLoggedOut = vi.fn<() => void>();
    const { opened, stop } = setup({ checkSession: () => Promise.resolve(false), onLoggedOut });
    noteEventId('abcd1234-1');
    opened[0]?.onStatus?.('closed');
    await vi.waitFor(() => expect(onLoggedOut).toHaveBeenCalled());
    vi.advanceTimersByTime(REOPEN_MS);
    expect(opened).toHaveLength(1);
    stop();
  });

  it('says offline when the session check cannot reach the server', async () => {
    const { opened, statuses, stop } = setup({ checkSession: () => Promise.reject(new Error('net')) });
    noteEventId('abcd1234-1');
    opened[0]?.onStatus?.('closed');
    await vi.waitFor(() => expect(statuses.at(-1)).toBe('offline'));
    stop();
  });

  it('back on the tab: a dead stream is reopened and everything shown is refetched', () => {
    const { qc, opened, doc, stop } = setup();
    noteEventId('abcd1234-1');
    opened[0]?.onStatus?.('reconnecting');
    const spy = vi.spyOn(qc, 'invalidateQueries');
    doc.dispatchEvent(new Event('visibilitychange'));
    expect(opened).toHaveLength(2);
    expect(spy).toHaveBeenCalledWith({ queryKey: qk.all, refetchType: 'active' });
    stop();
  });

  it('ignores status reports of a stream it already replaced', () => {
    const { opened, statuses, doc, stop } = setup();
    noteEventId('abcd1234-1');
    opened[0]?.onStatus?.('reconnecting');
    doc.dispatchEvent(new Event('visibilitychange'));
    const before = statuses.length;
    opened[0]?.onStatus?.('closed');
    expect(statuses.length).toBe(before);
    stop();
  });
});
