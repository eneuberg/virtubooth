import { describe, expect, it } from 'vitest';
import { createFpsLimiter } from './fps';

function frames(hz: number, seconds: number, jitter = 0): number[] {
  const out: number[] = [];
  const step = 1000 / hz;
  for (let i = 0; i < hz * seconds; i++) out.push(i * step + (i % 2 ? jitter : -jitter));
  return out;
}

const drawn = (fps: number, times: number[]) => {
  const limiter = createFpsLimiter(fps);
  return times.filter((t) => limiter.ready(t)).length;
};

describe('fps limiter', () => {
  it('draws every other frame at 30 fps on a 60 Hz display', () => {
    expect(drawn(30, frames(60, 10))).toBe(300);
  });

  it('draws every frame at 60 fps on a 60 Hz display, even with jitter', () => {
    expect(drawn(60, frames(60, 10, 1.2))).toBe(600);
  });

  it('caps a 144 Hz display', () => {
    const n = drawn(30, frames(144, 10));
    expect(n).toBeGreaterThanOrEqual(285);
    expect(n).toBeLessThanOrEqual(305);
    const m = drawn(60, frames(144, 10));
    expect(m).toBeGreaterThanOrEqual(560);
    expect(m).toBeLessThanOrEqual(610);
  });

  it('does not catch up after a pause', () => {
    const limiter = createFpsLimiter(30);
    expect(limiter.ready(0)).toBe(true);
    expect(limiter.ready(5000)).toBe(true);
    expect(limiter.ready(5016)).toBe(false);
    expect(limiter.ready(5033)).toBe(true);
  });

  it('can change the cap', () => {
    const limiter = createFpsLimiter(30);
    limiter.setFps(60);
    expect(frames(60, 2).filter((t) => limiter.ready(t)).length).toBe(120);
  });
});
