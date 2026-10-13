/**
 * Keyboard on the camera pages (desktop, Bluetooth remotes). OWNER: wave 2 "AC".
 * Port of the beer.js/booth.js rules:
 * - never with a modifier, never while a dialog or a full-screen state is open, never
 *   while typing;
 * - Space/Enter shoot only when nothing is focused (a focused button gets its own
 *   Space/Enter: React Aria presses it);
 * - Escape leaves the result; ArrowLeft/Right change the filter from the page or the
 *   shutter (the filter strip moves itself).
 */
import { useEffect, useEffectEvent } from 'react';

/** A dialog, sheet or full-screen state is up: page shortcuts must not act behind it. */
export function dialogOpen(doc: Document = document): boolean {
  return !!doc.querySelector('[role="dialog"], [role="alertdialog"], .vb-scrim, .vb-screen');
}

export function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  if (target instanceof HTMLElement && target.isContentEditable) return true;
  return !!target.closest('input, textarea, select');
}

function nothingFocused(doc: Document = document): boolean {
  const active = doc.activeElement;
  return !active || active === doc.body || active === doc.documentElement;
}

export interface CameraKeyHandlers {
  /** Space/Enter with nothing focused */
  shutter?: () => void;
  escape?: () => void;
  /** -1 previous, +1 next */
  arrow?: (step: -1 | 1) => void;
  /** elements whose focus still lets the arrows through (the shutter) */
  arrowTargets?: () => ReadonlyArray<Element | null>;
}

export function useCameraKeys(handlers: CameraKeyHandlers): void {
  const onKey = useEffectEvent((e: KeyboardEvent) => {
    if (e.altKey || e.ctrlKey || e.metaKey || e.defaultPrevented) return;
    if (dialogOpen() || isTyping(e.target)) return;
    if (e.key === 'Escape') {
      if (handlers.escape) {
        e.preventDefault();
        handlers.escape();
      }
      return;
    }
    if (e.key === ' ' || e.key === 'Enter') {
      if (handlers.shutter && nothingFocused()) {
        e.preventDefault();
        handlers.shutter();
      }
      return;
    }
    if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && handlers.arrow) {
      const active = document.activeElement;
      const allowed = nothingFocused() || (handlers.arrowTargets?.() ?? []).some((el) => el && el === active);
      if (!allowed) return;
      e.preventDefault();
      handlers.arrow(e.key === 'ArrowRight' ? 1 : -1);
    }
  });

  useEffect(() => {
    const listener = (e: KeyboardEvent) => onKey(e);
    document.addEventListener('keydown', listener);
    return () => document.removeEventListener('keydown', listener);
  }, []);
}

/** Asks before the tab closes while a photo exists only in memory (not stored, not sent). */
export function useLeaveGuard(atRisk: boolean): void {
  useEffect(() => {
    if (!atRisk) return undefined;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      // older browsers need returnValue set to show the prompt
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [atRisk]);
}
