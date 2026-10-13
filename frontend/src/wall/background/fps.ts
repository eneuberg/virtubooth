/**
 * Frame limiter for requestAnimationFrame loops: `ready(now)` says whether this frame
 * should draw for a target fps (a 60 Hz display at 30 fps draws every other frame).
 */
export interface FpsLimiter {
  ready(now: number): boolean;
  setFps(fps: number): void;
}

export function createFpsLimiter(fps: number): FpsLimiter {
  let interval = 1000 / fps;
  let last = Number.NEGATIVE_INFINITY;
  return {
    ready(now) {
      const elapsed = now - last;
      // 15 % slack: rAF timestamps jitter around the display's refresh interval
      if (elapsed < interval * 0.85) return false;
      // after a pause (hidden tab, slow frame) start over instead of catching up
      last = elapsed > interval * 2 ? now : last + interval;
      return true;
    },
    setFps(next) {
      interval = 1000 / next;
    },
  };
}
