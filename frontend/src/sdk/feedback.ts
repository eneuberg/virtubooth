/**
 * Small physical feedback for the camera pages. No confetti: the "develop" motion
 * replaces it (UX audit §6A). OWNER: wave 2 "GP".
 */

/** A short vibration where supported (never throws). */
export function vibrate(pattern: number | number[] = 30): void {
  try {
    navigator.vibrate?.(pattern);
  } catch {
    // unsupported or blocked
  }
}

/**
 * The screen flash at capture: a full white frame for ~120 ms, which also lights the
 * face in a dark room. Respects reduced motion (a dimmer, shorter flash).
 */
export function flash(): void {
  // TODO(wave 2, GP): a fixed element with a CSS class (no inline <style>), removed after the animation
}

/**
 * Plays the develop motion (black → image, 700 ms) on a freshly shown print.
 * PhotoTile does this with `isNew`; this is for other elements.
 */
export function develop(el: HTMLElement): void {
  // TODO(wave 2, GP): toggle the animate-develop class (restart via a reflow)
  void el;
}
