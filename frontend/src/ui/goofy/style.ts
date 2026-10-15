/**
 * The theme's style layer (`<html data-vb-style="elegant|party|goofy">`, see
 * styles/theme.ts). The playful pieces (googly eyes, jelly presses) run in „party“ (the
 * default, styles/party.css) and „goofy“ (Rummel, styles/goofy.css); the calm look pays
 * nothing for them.
 */
import { useSyncExternalStore } from 'react';
import { isThemeStyle, type ThemeStyle } from '@/styles/theme';

/** The style on <html>, null before the server or applyStyle set one. */
export function currentStyle(): ThemeStyle | null {
  if (typeof document === 'undefined') return null;
  const style = document.documentElement.getAttribute('data-vb-style');
  return isThemeStyle(style) ? style : null;
}

/** party and goofy: the styles with googly eyes and jelly presses */
export function isPlayful(style: ThemeStyle | null = currentStyle()): boolean {
  return style === 'party' || style === 'goofy';
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

/** The current style (follows a theme switch without a reload). */
export function useThemeStyle(): ThemeStyle | null {
  return useSyncExternalStore(subscribe, currentStyle, () => null);
}
