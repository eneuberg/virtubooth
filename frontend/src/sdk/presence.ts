/**
 * The page's heartbeat (POST /api/here): tells the server the guest page is open, for
 * the hosts' "Aktiv jetzt" and the online time per guest (docs/ARCHITECTURE.md,
 * "Presence and online time"). No UI; main.tsx starts it once.
 *
 * - `{visible: true}` at start when the page is visible, then every BEAT_MS while
 *   `document.visibilityState === 'visible'`, and at once when the page becomes
 *   visible again: never sooner than MIN_GAP_MS after the last one (it waits the rest).
 * - `{visible: false}` once when the page is hidden (`visibilitychange`) or left
 *   (`pagehide`), as a keepalive fetch that outlives the page. A fetch sends the
 *   Origin header the server's CSRF check wants; a string body has a Content-Length.
 * - A 404 `scan_qr` (no party access) stops it for good; every other failure is
 *   silent (debugLog), the next beat simply tries again.
 */
import { api } from '@/api/client';
import { debugLog } from './debug';

export const BEAT_MS = 60_000;
export const MIN_GAP_MS = 15_000;
const HERE_PATH = '/api/here';

let running = false;
let timer: ReturnType<typeof setTimeout> | null = null;
let lastBeat = Number.NEGATIVE_INFINITY;
/** the server was last told "visible" (so leaving tells it once) */
let shown = false;

function visible(): boolean {
  return document.visibilityState === 'visible';
}

function cancel(): void {
  if (timer !== null) clearTimeout(timer);
  timer = null;
}

function schedule(delay: number): void {
  cancel();
  timer = setTimeout(() => {
    timer = null;
    void beat();
  }, delay);
}

async function beat(): Promise<void> {
  if (!running || !visible()) return;
  lastBeat = Date.now();
  shown = true;
  schedule(BEAT_MS);
  try {
    const { error, response } = await api.POST(HERE_PATH, { body: { visible: true } });
    if (response.status === 404 && error?.error === 'scan_qr') {
      debugLog('here: no party access, stopped');
      stopPresence();
    } else if (!response.ok) {
      debugLog('here failed', response.status);
    }
  } catch (err) {
    debugLog('here failed', String(err));
  }
}

function leave(): void {
  cancel();
  if (!running || !shown) return;
  shown = false;
  try {
    globalThis
      .fetch(HERE_PATH, {
        method: 'POST',
        keepalive: true,
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: '{"visible":false}',
      })
      .catch((err: unknown) => {
        debugLog('here (hidden) failed', String(err));
      });
  } catch (err) {
    // keepalive refused (too much in flight): the server closes the visit by itself
    debugLog('here (hidden) failed', String(err));
  }
}

function onVisibilityChange(): void {
  if (!visible()) {
    leave();
    return;
  }
  const wait = lastBeat + MIN_GAP_MS - Date.now();
  if (wait > 0) schedule(wait);
  else void beat();
}

function onPageShow(event: PageTransitionEvent): void {
  // back from the back/forward cache: the page was left (pagehide), it is here again
  if (event.persisted) onVisibilityChange();
}

/** Starts the heartbeat (once per page). */
export function startPresence(): void {
  if (running || typeof document === 'undefined') return;
  running = true;
  document.addEventListener('visibilitychange', onVisibilityChange);
  window.addEventListener('pagehide', leave);
  window.addEventListener('pageshow', onPageShow);
  if (visible()) void beat();
}

/** Stops it for good (no party access; tests). */
export function stopPresence(): void {
  running = false;
  shown = false;
  lastBeat = Number.NEGATIVE_INFINITY;
  cancel();
  document.removeEventListener('visibilitychange', onVisibilityChange);
  window.removeEventListener('pagehide', leave);
  window.removeEventListener('pageshow', onPageShow);
}
