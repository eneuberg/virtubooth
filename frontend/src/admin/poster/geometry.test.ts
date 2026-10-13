import { describe, expect, it } from 'vitest';
import {
  clampRect,
  defaultRect,
  describeRect,
  keyStep,
  minSide,
  moveRect,
  resizeAroundCentre,
  resizeFromCorner,
  sameRect,
  type PageSize,
  type RelRect,
} from './geometry';

const A4: PageSize = { width: 595.28, height: 841.89 };
const LANDSCAPE: PageSize = { width: 842, height: 595 };

/** What the server checks (services/posters.py layout_ok). */
function serverAccepts(rect: RelRect, size: PageSize): boolean {
  const eps = 1e-6;
  const w = rect.w * size.width;
  const h = rect.h * size.height;
  return (
    rect.x >= 0 &&
    rect.y >= 0 &&
    rect.w >= 0.03 &&
    rect.h >= 0.03 &&
    rect.x + rect.w <= 1 + eps &&
    rect.y + rect.h <= 1 + eps &&
    Math.abs(w - h) <= 0.02 * Math.max(w, h)
  );
}

const side = (rect: RelRect, size: PageSize) => rect.w * size.width;

describe('the QR field', () => {
  it('starts as a centred square of 40 % of the shorter side', () => {
    for (const size of [A4, LANDSCAPE]) {
      const rect = defaultRect(size);
      expect(side(rect, size)).toBeCloseTo(0.4 * Math.min(size.width, size.height), 6);
      expect(rect.h * size.height).toBeCloseTo(side(rect, size), 6);
      expect(rect.x + rect.w / 2).toBeCloseTo(0.5, 9);
      expect(rect.y + rect.h / 2).toBeCloseTo(0.5, 9);
      expect(serverAccepts(rect, size)).toBe(true);
    }
  });

  it('moves and stops at the page edges', () => {
    const start = defaultRect(A4);
    const moved = moveRect(start, 0.1, -0.05, A4);
    expect(moved.x).toBeCloseTo(start.x + 0.1, 9);
    expect(moved.y).toBeCloseTo(start.y - 0.05, 9);
    const corner = moveRect(start, 5, 5, A4);
    expect(corner.x + corner.w).toBeCloseTo(1, 9);
    expect(corner.y + corner.h).toBeCloseTo(1, 9);
    const origin = moveRect(start, -5, -5, A4);
    expect(origin).toMatchObject({ x: 0, y: 0 });
    for (const r of [moved, corner, origin]) expect(serverAccepts(r, A4)).toBe(true);
  });

  it('resizes from the corner, square in points, within the page', () => {
    const start = defaultRect(A4);
    // drag 10 % of the width right and 10 % of the height down: grows by the average
    const grown = resizeFromCorner(start, 0.1, 0.1, A4);
    expect(grown.x).toBe(start.x);
    expect(grown.y).toBe(start.y);
    expect(side(grown, A4)).toBeCloseTo(side(start, A4) + (0.1 * A4.width + 0.1 * A4.height) / 2, 6);
    expect(serverAccepts(grown, A4)).toBe(true);
    // far out: stops at the nearer edge (the right one on a portrait page)
    const huge = resizeFromCorner(start, 3, 3, A4);
    expect(huge.x + huge.w).toBeCloseTo(1, 9);
    expect(serverAccepts(huge, A4)).toBe(true);
    // far in: the minimum, 3 % of both sides
    const tiny = resizeFromCorner(start, -3, -3, A4);
    expect(side(tiny, A4)).toBeCloseTo(minSide(A4), 9);
    expect(tiny.w).toBeGreaterThanOrEqual(0.03);
    expect(tiny.h).toBeGreaterThanOrEqual(0.03);
    expect(serverAccepts(tiny, A4)).toBe(true);
  });

  it('fits a square on non-square pages (never wider than the shorter side)', () => {
    for (const size of [A4, LANDSCAPE, { width: 300, height: 2000 }]) {
      const all = clampRect({ x: -1, y: -1, w: 5, h: 5 }, size);
      expect(side(all, size)).toBeCloseTo(Math.min(size.width, size.height), 6);
      expect(serverAccepts(all, size)).toBe(true);
      // a slightly non-square field (another device, 2 % tolerance) becomes square
      const fixed = clampRect({ x: 0.2, y: 0.2, w: 0.3, h: 0.3 }, size);
      expect(fixed.h * size.height).toBeCloseTo(fixed.w * size.width, 6);
    }
  });

  it('follows the keyboard: arrows 1 % (Shift 5 %), plus and minus 1 %', () => {
    const start = defaultRect(A4);
    expect(keyStep('ArrowRight', false, start, A4)?.x).toBeCloseTo(start.x + 0.01, 9);
    expect(keyStep('ArrowLeft', true, start, A4)?.x).toBeCloseTo(start.x - 0.05, 9);
    expect(keyStep('ArrowDown', false, start, A4)?.y).toBeCloseTo(start.y + 0.01, 9);
    expect(keyStep('ArrowUp', true, start, A4)?.y).toBeCloseTo(start.y - 0.05, 9);
    const bigger = keyStep('+', false, start, A4);
    expect(bigger?.w).toBeCloseTo(start.w + 0.01, 9);
    // around the centre
    expect((bigger?.x ?? 0) + (bigger?.w ?? 0) / 2).toBeCloseTo(start.x + start.w / 2, 9);
    expect(keyStep('=', false, start, A4)?.w).toBeCloseTo(start.w + 0.01, 9);
    expect(keyStep('-', true, start, A4)?.w).toBeCloseTo(start.w - 0.01, 9);
    expect(keyStep('a', false, start, A4)).toBeNull();
    expect(keyStep('Enter', false, start, A4)).toBeNull();
  });

  it('keeps the minimum and the page when resizing by keys', () => {
    let rect = defaultRect(A4);
    for (let i = 0; i < 100; i++) rect = resizeAroundCentre(rect, -0.01, A4);
    expect(side(rect, A4)).toBeCloseTo(minSide(A4), 9);
    for (let i = 0; i < 200; i++) rect = resizeAroundCentre(rect, 0.01, A4);
    expect(side(rect, A4)).toBeCloseTo(A4.width, 6);
    expect(serverAccepts(rect, A4)).toBe(true);
  });

  it('compares and describes', () => {
    const rect = { x: 0.123, y: 0.4, w: 0.3, h: 0.21 };
    expect(sameRect(rect, { ...rect, x: 0.123 + 1e-9 })).toBe(true);
    expect(sameRect(rect, { ...rect, x: 0.13 })).toBe(false);
    expect(sameRect(rect, null)).toBe(false);
    expect(sameRect(null, null)).toBe(true);
    expect(describeRect(rect).replace(/\s/g, ' ')).toBe('QR-Feld: links 12 %, oben 40 %, Größe 30 %');
  });
});
