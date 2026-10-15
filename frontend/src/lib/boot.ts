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
 *
 * Firefox and Safari report the same for a chunk they abort because the page is
 * leaving (URL bar, a link to another document, history), and a reload then cancels
 * that navigation. So reload only once the server's HTML for this page names another
 * entry script; any other failure goes on to the error boundary ("Seite neu laden").
 */
export function installPreloadRecovery(): void {
  window.addEventListener('beforeunload', () => {
    leavingSince = Date.now();
  });
  // back from the back/forward cache: the page is here again
  window.addEventListener('pageshow', () => {
    leavingSince = null;
  });
  window.addEventListener('vite:preloadError', () => {
    void newBuildDeployed().then((deployed) => {
      if (deployed) reloadOnce();
    });
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

/** When the page last started to leave (`beforeunload`), null while it stays. */
let leavingSince: number | null = null;

/** How long a page that started to leave may take to go (the next server's answer);
 * after that, a navigation that was cancelled or turned into a download left it here. */
export const LEAVE_GRACE_MS = 10_000;

function isLeaving(): boolean {
  return leavingSince !== null && Date.now() - leavingSince < LEAVE_GRACE_MS;
}

/**
 * A lazy chunk's loader (for React's `lazy`) that keeps quiet while the page leaves.
 * Firefox aborts the chunks a page still loads as soon as a navigation to another
 * document starts, well before the next page replaces this one. Rejecting then shows
 * the error boundary ("Etwas ist schiefgelaufen") and logs the error for the moment
 * the page has left. So a chunk that fails while the page is leaving waits for the
 * page to go, and fails as usual only if it is still here after LEAVE_GRACE_MS.
 */
export function quietWhileLeaving<T>(load: () => Promise<T>): () => Promise<T> {
  return () =>
    load().catch((error: unknown) => {
      if (!isLeaving()) throw error;
      return new Promise<T>((_, reject) => {
        setTimeout(() => {
          reject(error instanceof Error ? error : new Error(String(error)));
        }, LEAVE_GRACE_MS);
      });
    });
}

async function newBuildDeployed(): Promise<boolean> {
  const entry = document.querySelector('script[type="module"][src]')?.getAttribute('src');
  if (!entry) return false;
  try {
    // keepalive: the navigation that aborted the chunk does not cut this request
    // short either (WebKit logs that as an error)
    const res = await fetch(location.pathname, { cache: 'no-store', keepalive: true });
    // not ok: a 404 (no access any more) or a proxy error mid-deploy, no new app
    return res.ok && !(await res.text()).includes(entry);
  } catch {
    return false; // offline
  }
}

function reloadOnce(): void {
  let reloaded = false;
  try {
    reloaded = sessionStorage.getItem(RELOAD_KEY) === '1';
    sessionStorage.setItem(RELOAD_KEY, '1');
  } catch {
    // storage blocked: still try one reload
  }
  if (!reloaded) location.reload();
}
