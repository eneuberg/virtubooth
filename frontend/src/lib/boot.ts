/**
 * App start helpers shared by the guest and admin entries.
 */

const RELOAD_KEY = 'vb_chunk_reload';

/** Tells public/boot-check.js that the app started. Call once the root rendered. */
export function markReady(): void {
  window.__vbReady = true;
}

/**
 * After a deploy, an open tab may ask for a lazy chunk that no longer exists.
 * Vite reports that as `vite:preloadError`; reload once (guarded per tab) to get
 * the new HTML instead of showing a broken page.
 */
export function installPreloadRecovery(): void {
  window.addEventListener('vite:preloadError', (event) => {
    let reloaded = false;
    try {
      reloaded = sessionStorage.getItem(RELOAD_KEY) === '1';
      sessionStorage.setItem(RELOAD_KEY, '1');
    } catch {
      // storage blocked: still try one reload
    }
    if (reloaded) return;
    event.preventDefault();
    location.reload();
  });
  // a page that stayed up a while may reload again for the next deploy; a page that
  // fails right after the reload must not loop
  setTimeout(() => {
    try {
      sessionStorage.removeItem(RELOAD_KEY);
    } catch {
      // ignore
    }
  }, 30_000);
}
