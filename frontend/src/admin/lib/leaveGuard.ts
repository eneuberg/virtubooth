/**
 * Holding an in-app navigation while a screen has unsaved changes (leaveGuard.test.ts).
 *
 * The admin router's `navigate` (routes.tsx) runs every client-side link through
 * {@link guardedNavigate}. A screen with a draft sets a guard: it gets the navigation
 * as `proceed`, asks (its own dialog) and calls `proceed` when the host says go. Full
 * page loads (reload, closing the tab, links outside the app) are the browser's
 * `beforeunload` question instead: {@link useLeaveGuard} sets both.
 */
import { useEffect, useRef } from 'react';

/** true: the guard holds the navigation (and may call `proceed` later) */
export type LeaveGuard = (proceed: () => void) => boolean;

let current: LeaveGuard | null = null;

/** Sets the guard; the returned function removes it (only if it is still this one). */
export function setLeaveGuard(guard: LeaveGuard): () => void {
  current = guard;
  return () => {
    if (current === guard) current = null;
  };
}

/** Runs `go` now, unless a guard holds it. */
export function guardedNavigate(go: () => void): void {
  if (current?.(go)) return;
  go();
}

/**
 * While `active`: in-app navigations go to `onHold(proceed)` instead of happening, and
 * leaving the page asks the browser's own question.
 */
export function useLeaveGuard(active: boolean, onHold: (proceed: () => void) => void): void {
  const hold = useRef(onHold);
  useEffect(() => {
    hold.current = onHold;
  });
  useEffect(() => {
    if (!active) return undefined;
    const remove = setLeaveGuard((proceed) => {
      hold.current(proceed);
      return true;
    });
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // older browsers want a returnValue to show the question
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => {
      remove();
      window.removeEventListener('beforeunload', onBeforeUnload);
    };
  }, [active]);
}
