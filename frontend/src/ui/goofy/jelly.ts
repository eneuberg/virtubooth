/**
 * Wackelpudding: in the goofy style a pressed button or card is squashed flat
 * (styles/goofy.css, `[data-pressed]`), and when the finger lets go it wobbles back
 * out like jelly: `data-vb-jelly` for one run of the `vb-jelly` keyframes. Only as an
 * answer to the finger, never by itself. Transform only: nothing around it moves.
 */
import { isGoofy, prefersReducedMotion } from './style';

const TARGETS =
  'button[data-variant], a[data-variant], a.vb-activity, .vb-shutter, [data-testid="guest-pass"], .vb-wordmark';

function wobble(event: PointerEvent): void {
  if (!isGoofy() || prefersReducedMotion()) return;
  const target = event.target instanceof Element ? event.target.closest<HTMLElement>(TARGETS) : null;
  if (!target || target.matches(':disabled, [data-disabled]')) return;
  target.removeAttribute('data-vb-jelly');
  // restart the animation when it is pressed again mid-wobble
  void target.offsetWidth;
  target.setAttribute('data-vb-jelly', '');
  const done = (e: AnimationEvent): void => {
    if (e.target !== target) return;
    target.removeAttribute('data-vb-jelly');
    target.removeEventListener('animationend', done);
  };
  target.addEventListener('animationend', done);
}

let installed = false;

/** Once per page (guest app); harmless while the style is elegant. */
export function installJelly(): void {
  if (installed || typeof window === 'undefined') return;
  installed = true;
  window.addEventListener('pointerup', wobble, { passive: true });
}
