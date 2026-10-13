/**
 * The admin event stream's life cycle (contracts/api.md §4), without React:
 *
 * 1. Wait for the page's first admin answers, open the stream at the earliest
 *    `X-VB-Event-Id` they reported (`?since=`), so nothing in between is lost. And
 *    wait for the page's load event: Firefox counts a request opened before it as
 *    part of the page load, so a stream would keep the page loading for good (the
 *    tab's spinner; a test's `page.goto` waits until it times out).
 * 2. Apply every event to the query cache (applyEvent.ts); `stream.resync` refetches all.
 * 3. The browser reconnects by itself after network errors (`Last-Event-ID` → replay).
 *    While the stream is down, poll: refetch the shown queries every 5 s.
 * 4. A stream the browser gave up on (401, proxy error) is "closed": check the session
 *    (gone → login page), otherwise reopen after 4 s from the last event seen.
 * 5. Back on the tab (`visibilitychange`) or back online: reopen if needed, then resync,
 *    because phones freeze background tabs and the stream may be dead without an error.
 * 6. Leaving the page (`pagehide`): close the stream first, so the browser doesn't log
 *    the request it aborts as an error (Safari: "EventSource cannot load … due to access
 *    control checks"). A page restored from the back/forward cache reopens and resyncs.
 */
import type { QueryClient } from '@tanstack/react-query';
import type { AdminEventsHandle, AdminEventsOptions, StreamStatus } from '@/api/events';
import type { ConnectionStatus } from '@/ui/ConnectionIndicator';
import { applyAdminEvent } from './applyEvent';
import { createInvalidator } from './invalidator';
import { qk } from './keys';

export const POLL_MS = 5000;
export const REOPEN_MS = 4000;
/** open even if the first fetches are still running after this long */
export const OPEN_AT_LATEST_MS = 3000;

export interface StreamDeps {
  open: (options: AdminEventsOptions) => AdminEventsHandle;
  /** true: still logged in; throws when the server can't be reached */
  checkSession: () => Promise<boolean>;
  onLoggedOut: () => void;
  setStatus: (status: ConnectionStatus) => void;
  cursor: () => string | null;
  onCursor: (listener: () => void) => () => void;
  isOnline?: () => boolean;
  target?: Pick<Document, 'addEventListener' | 'removeEventListener' | 'visibilityState'> & {
    readyState?: DocumentReadyState;
  };
  win?: Pick<Window, 'addEventListener' | 'removeEventListener'>;
}

export function startAdminEvents(qc: QueryClient, deps: StreamDeps): () => void {
  const doc = deps.target ?? document;
  const win = deps.win ?? window;
  const online = deps.isOnline ?? (() => navigator.onLine);
  const invalidator = createInvalidator(qc);

  let stopped = false;
  /** between pagehide and a pageshow from the back/forward cache */
  let away = false;
  let generation = 0;
  let handle: AdminEventsHandle | null = null;
  let streamStatus: StreamStatus = 'connecting';
  let wasLive = false;
  let lastId: string | null = null;
  let poll: ReturnType<typeof setInterval> | null = null;
  let reopen: ReturnType<typeof setTimeout> | null = null;

  const resync = () => {
    void qc.invalidateQueries({ queryKey: qk.all, refetchType: 'active' });
  };
  const startPolling = () => {
    poll ??= setInterval(resync, POLL_MS);
  };
  const stopPolling = () => {
    if (poll !== null) clearInterval(poll);
    poll = null;
  };
  const down = (): ConnectionStatus => (online() ? 'reconnecting' : 'offline');

  const recover = async () => {
    try {
      if (!(await deps.checkSession())) {
        deps.onLoggedOut();
        return;
      }
    } catch {
      deps.setStatus('offline');
    }
    if (stopped || reopen !== null) return;
    reopen = setTimeout(() => {
      reopen = null;
      open();
    }, REOPEN_MS);
  };

  const onStatus = (status: StreamStatus) => {
    streamStatus = status;
    switch (status) {
      case 'connecting':
        deps.setStatus(wasLive ? down() : 'connecting');
        return;
      case 'live':
        wasLive = true;
        deps.setStatus('live');
        stopPolling();
        return;
      case 'reconnecting':
        deps.setStatus(down());
        startPolling();
        return;
      case 'closed':
        deps.setStatus(online() ? 'polling' : 'offline');
        startPolling();
        void recover();
        return;
    }
  };

  function open() {
    if (stopped || away) return;
    if (reopen !== null) clearTimeout(reopen);
    reopen = null;
    const gen = ++generation; // the old handle's "closed" no longer counts
    handle?.close();
    handle = deps.open({
      since: lastId ?? deps.cursor(),
      onEvent: (event) => {
        if (gen !== generation) return;
        if (event.id) lastId = event.id;
        applyAdminEvent(event, { qc, invalidate: invalidator.invalidate });
      },
      onStatus: (status) => {
        if (gen === generation) onStatus(status);
      },
    });
  }

  // 1. open once the first answers are in (earliest cursor), or after a while anyway
  const started = Date.now();
  const unsubscribers: Array<() => void> = [];
  const loading = () => doc.readyState !== undefined && doc.readyState !== 'complete';
  const firstOpen = () => {
    if (handle || stopped || away || loading()) return;
    const waitedEnough = Date.now() - started >= OPEN_AT_LATEST_MS;
    if (!waitedEnough && (deps.cursor() === null || qc.isFetching() > 0)) return;
    for (const off of unsubscribers.splice(0)) off();
    clearTimeout(fallback);
    open();
  };
  unsubscribers.push(deps.onCursor(firstOpen), qc.getQueryCache().subscribe(firstOpen));
  if (loading()) {
    win.addEventListener('load', firstOpen);
    unsubscribers.push(() => win.removeEventListener('load', firstOpen));
  }
  const fallback = setTimeout(firstOpen, OPEN_AT_LATEST_MS);
  firstOpen();

  // 5. back on the tab, back online
  const wake = () => {
    if (stopped || away || !handle || doc.visibilityState === 'hidden') return;
    if (streamStatus !== 'live') open();
    resync();
  };
  doc.addEventListener('visibilitychange', wake);
  win.addEventListener('online', wake);

  // 6. leaving the page, and coming back from the back/forward cache
  // nothing opens while away: a first answer or the load event may still arrive after
  // pagehide, and a stream opened then is aborted by the navigation (the same error)
  const leave = () => {
    if (stopped) return;
    away = true;
    generation += 1; // its "closed" means nothing: no session check, no polling
    if (reopen !== null) clearTimeout(reopen);
    reopen = null;
    stopPolling();
    handle?.close();
    handle = null;
  };
  const back = (e: Event) => {
    // PageTransitionEvent.persisted: restored from the back/forward cache
    if (stopped || !away || !('persisted' in e && e.persisted === true)) return;
    away = false;
    open();
    resync();
  };
  win.addEventListener('pagehide', leave);
  win.addEventListener('pageshow', back);

  return () => {
    stopped = true;
    generation += 1;
    for (const off of unsubscribers.splice(0)) off();
    clearTimeout(fallback);
    if (reopen !== null) clearTimeout(reopen);
    stopPolling();
    handle?.close();
    invalidator.dispose();
    doc.removeEventListener('visibilitychange', wake);
    win.removeEventListener('online', wake);
    win.removeEventListener('pagehide', leave);
    win.removeEventListener('pageshow', back);
  };
}
