/**
 * Small physical feedback for the camera pages. No confetti: the "develop" motion
 * replaces it (UX audit §6A).
 */

function reducedMotion(): boolean {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

/** A short vibration where supported (never throws). */
export function vibrate(pattern: number | number[] = 30): void {
  try {
    navigator.vibrate?.(pattern);
  } catch {
    // unsupported or blocked
  }
}

/**
 * The screen flash at capture: a full white frame that fades out over ~180 ms, which
 * also lights the face in a dark room. With reduced motion it is skipped (a sudden
 * full-screen white is exactly what that preference asks to avoid).
 * A fixed element with classes from app.css, removed after the animation (no <style>).
 */
export function flash(): void {
  if (reducedMotion() || !document.body) return;
  const el = document.createElement('div');
  el.className = 'vb-flash pointer-events-none fixed inset-0 z-(--z-screen) animate-fade-out bg-white';
  el.setAttribute('aria-hidden', 'true');
  const done = () => el.remove();
  el.addEventListener('animationend', done, { once: true });
  setTimeout(done, 600); // animationend never fires in a hidden tab
  document.body.append(el);
}

/**
 * Plays the develop motion (black → image, 700 ms) on a freshly shown print.
 * PhotoTile does this with `isNew`; this is for other elements. Restarts the
 * animation when it ran before.
 */
export function develop(el: HTMLElement): void {
  el.classList.remove('animate-develop');
  void el.offsetWidth; // reflow, so the animation starts over
  el.classList.add('animate-develop');
}
