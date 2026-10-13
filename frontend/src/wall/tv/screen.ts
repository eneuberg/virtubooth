/**
 * TV behaviour: Screen Wake Lock, fullscreen, idle cursor, the planned soft reload.
 */

/** Wake Lock exists only in secure contexts (https, localhost). */
export function wakeLockSupported(): boolean {
  return typeof navigator !== 'undefined' && 'wakeLock' in navigator && window.isSecureContext;
}

/**
 * Keeps the screen on while the page is visible; the browser drops the lock when the tab
 * is hidden, so it is requested again on every `visibilitychange` to visible.
 */
export function keepScreenOn(): () => void {
  if (!wakeLockSupported()) return () => undefined;
  let sentinel: WakeLockSentinel | null = null;
  let stopped = false;
  const acquire = async (): Promise<void> => {
    if (stopped || document.hidden || (sentinel && !sentinel.released)) return;
    try {
      sentinel = await navigator.wakeLock.request('screen');
    } catch {
      sentinel = null; // refused (battery saver, policy): nothing else to do
    }
  };
  const onVisibility = (): void => void acquire();
  document.addEventListener('visibilitychange', onVisibility);
  void acquire();
  return () => {
    stopped = true;
    document.removeEventListener('visibilitychange', onVisibility);
    void sentinel?.release().catch(() => undefined);
  };
}

export function isFullscreen(): boolean {
  return document.fullscreenElement != null;
}

export async function toggleFullscreen(): Promise<void> {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.documentElement.requestFullscreen({ navigationUI: 'hide' });
  } catch {
    // not allowed (no user gesture, iframe, old TV browser): the button just does nothing
  }
}

export function fullscreenAvailable(): boolean {
  return typeof document !== 'undefined' && document.fullscreenEnabled;
}

/** Soft reload after this long, at the next mode boundary (memory of 8 h+ parties). */
export const SOFT_RELOAD_MS = 6 * 60 * 60 * 1000;

export function softReloadDue(now: number = performance.now()): boolean {
  return now >= SOFT_RELOAD_MS;
}
