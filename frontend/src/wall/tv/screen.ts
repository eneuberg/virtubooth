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

/**
 * Fullscreen with the `webkit` prefix as a fallback: old TV browsers and Safari before
 * 16.4 only have webkitRequestFullscreen (older still: webkitRequestFullScreen, a capital
 * S, and webkitCancelFullScreen).
 */
interface PrefixedDocument {
  fullscreenEnabled?: boolean;
  fullscreenElement?: Element | null;
  exitFullscreen?: () => Promise<void>;
  webkitFullscreenEnabled?: boolean;
  webkitFullscreenElement?: Element | null;
  webkitCurrentFullScreenElement?: Element | null;
  webkitExitFullscreen?: () => void;
  webkitCancelFullScreen?: () => void;
}

interface PrefixedElement {
  requestFullscreen?: (options?: FullscreenOptions) => Promise<void>;
  webkitRequestFullscreen?: () => void;
  webkitRequestFullScreen?: () => void;
}

/** The events that report a fullscreen change (standard and prefixed). */
export const FULLSCREEN_EVENTS = ['fullscreenchange', 'webkitfullscreenchange'] as const;

export function isFullscreen(doc: Document = document): boolean {
  const d = doc as PrefixedDocument;
  return (
    (d.fullscreenElement ?? d.webkitFullscreenElement ?? d.webkitCurrentFullScreenElement ?? null) != null
  );
}

export async function toggleFullscreen(doc: Document = document): Promise<void> {
  const d = doc as PrefixedDocument;
  const el = doc.documentElement as PrefixedElement;
  try {
    if (isFullscreen(doc)) {
      if (typeof d.exitFullscreen === 'function') await d.exitFullscreen();
      else if (typeof d.webkitExitFullscreen === 'function') d.webkitExitFullscreen();
      else d.webkitCancelFullScreen?.();
    } else if (typeof el.requestFullscreen === 'function') {
      await el.requestFullscreen({ navigationUI: 'hide' });
    } else if (typeof el.webkitRequestFullscreen === 'function') {
      el.webkitRequestFullscreen();
    } else {
      el.webkitRequestFullScreen?.();
    }
  } catch {
    // not allowed (no user gesture, iframe, old TV browser): the button just does nothing
  }
}

export function fullscreenAvailable(doc: Document | undefined = globalThis.document): boolean {
  if (!doc) return false;
  const d = doc as PrefixedDocument;
  // the standard flag decides where it exists (false in a frame without permission)
  if (typeof d.fullscreenEnabled === 'boolean') return d.fullscreenEnabled;
  if (typeof d.webkitFullscreenEnabled === 'boolean') return d.webkitFullscreenEnabled;
  const el = doc.documentElement as PrefixedElement;
  return typeof el.webkitRequestFullscreen === 'function' || typeof el.webkitRequestFullScreen === 'function';
}

/** Soft reload after this long, at the next mode boundary (memory of 8 h+ parties). */
export const SOFT_RELOAD_MS = 6 * 60 * 60 * 1000;

export function softReloadDue(now: number = performance.now()): boolean {
  return now >= SOFT_RELOAD_MS;
}
