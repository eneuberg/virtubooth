/**
 * Small browser helpers for the admin: clipboard with a fallback, media queries,
 * focusing an element once an overlay has let go of the focus.
 */
import { useSyncExternalStore } from 'react';

/**
 * Copy text. Plain http on a LAN IP has no async clipboard API (not a secure
 * context), so fall back to a hidden textarea and execCommand.
 */
export async function copyText(text: string): Promise<boolean> {
  if (window.isSecureContext && navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // fall through to the old way
    }
  }
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.className = 'fixed -left-[9999px] top-0 opacity-0';
  document.body.append(area);
  area.select();
  let ok = false;
  try {
    // oxlint-disable-next-line typescript/no-deprecated -- the only clipboard API outside secure contexts
    ok = document.execCommand('copy');
  } catch {
    ok = false;
  }
  area.remove();
  return ok;
}

/** Desktop manage (sidebar + inspector) from 64rem. */
export const DESKTOP = '(min-width: 64rem)';

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (notify) => {
      const mql = window.matchMedia(query);
      mql.addEventListener('change', notify);
      return () => mql.removeEventListener('change', notify);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

/**
 * Focus an element after a dialog closed: React Aria hands the focus back to the
 * opener when the overlay unmounts (after its exit animation). When that opener is gone
 * (a deleted photo's tile) or not where the work continues, move it here.
 */
export function focusLater(find: () => HTMLElement | null | undefined, delay = 320): void {
  window.setTimeout(() => {
    const el = find();
    if (el?.isConnected) el.focus();
  }, delay);
}

export function thumbFor(id: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`[data-thumb-for="${CSS.escape(id)}"]`);
}
