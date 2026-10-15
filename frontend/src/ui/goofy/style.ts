/**
 * The theme's style layer (`<html data-vb-style="elegant|goofy">`, see styles/theme.ts).
 * The goofy pieces (googly eyes, jelly presses) only run while it says "goofy", so the
 * calm look pays nothing for them.
 */
import { useSyncExternalStore } from 'react';

export function isGoofy(): boolean {
  return (
    typeof document !== 'undefined' && document.documentElement.getAttribute('data-vb-style') === 'goofy'
  );
}

export function prefersReducedMotion(): boolean {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function subscribe(onChange: () => void): () => void {
  if (typeof MutationObserver !== 'function') return () => undefined;
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-vb-style'] });
  return () => observer.disconnect();
}

/** True while the goofy layer is on (follows a theme switch without a reload). */
export function useGoofy(): boolean {
  return useSyncExternalStore(subscribe, isGoofy, () => false);
}
