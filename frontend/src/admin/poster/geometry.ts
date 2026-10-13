/**
 * The QR field in the editor (pure, shared with the tests). The field is a rectangle
 * relative to the displayed page (0..1, origin top left) that is square in PDF points:
 * on a w × h page, `rect.w * width === rect.h * height`. The server checks the same
 * (services/posters.py): on the page, at least 3 % per side, square within 2 %.
 */
import type { RelRect } from '@/print/types';

export type { RelRect };

/** A page in PDF points, rotation applied (as pdf.js reports it). */
export interface PageSize {
  width: number;
  height: number;
}

/** the server's smallest side, per page dimension */
export const MIN_REL = 0.03;
/** a new field: this share of the page's shorter side */
export const DEFAULT_SHARE = 0.4;
/** arrow keys: 1 %, with Shift 5 % */
export const STEP = 0.01;
export const BIG_STEP = 0.05;

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

/** Smallest side in points: 3 % of both page dimensions (a hair more, for rounding). */
export function minSide(size: PageSize): number {
  return MIN_REL * 1.001 * Math.max(size.width, size.height);
}

function fromSide(x: number, y: number, side: number, size: PageSize): RelRect {
  return { x, y, w: side / size.width, h: side / size.height };
}

/** A centred square of 40 % of the shorter side. */
export function defaultRect(size: PageSize): RelRect {
  const side = DEFAULT_SHARE * Math.min(size.width, size.height);
  return fromSide((size.width - side) / 2 / size.width, (size.height - side) / 2 / size.height, side, size);
}

/** Square (by its width), between the smallest side and the page, and on the page. */
export function clampRect(rect: RelRect, size: PageSize): RelRect {
  const side = clamp(rect.w * size.width, minSide(size), Math.min(size.width, size.height));
  const w = side / size.width;
  const h = side / size.height;
  return { x: clamp(rect.x, 0, 1 - w), y: clamp(rect.y, 0, 1 - h), w, h };
}

/** Move by dx, dy (relative to the page), stopping at the edges. */
export function moveRect(rect: RelRect, dx: number, dy: number, size: PageSize): RelRect {
  return clampRect({ ...rect, x: rect.x + dx, y: rect.y + dy }, size);
}

/**
 * The corner handle (bottom right): the top-left corner stays, the square grows with the
 * drag along the diagonal (dx, dy relative to the page), up to the page's edges.
 */
export function resizeFromCorner(rect: RelRect, dx: number, dy: number, size: PageSize): RelRect {
  const side = rect.w * size.width + (dx * size.width + dy * size.height) / 2;
  const room = Math.min((1 - rect.x) * size.width, (1 - rect.y) * size.height);
  const min = minSide(size);
  return clampRect(fromSide(rect.x, rect.y, clamp(side, min, Math.max(min, room)), size), size);
}

/** Grow or shrink by `delta` of the page width, around the centre (+ and − keys). */
export function resizeAroundCentre(rect: RelRect, delta: number, size: PageSize): RelRect {
  const side = clamp((rect.w + delta) * size.width, minSide(size), Math.min(size.width, size.height));
  const cx = (rect.x + rect.w / 2) * size.width;
  const cy = (rect.y + rect.h / 2) * size.height;
  return clampRect(fromSide((cx - side / 2) / size.width, (cy - side / 2) / size.height, side, size), size);
}

/**
 * The keyboard: arrows move 1 % (Shift: 5 %), + and − resize 1 %. Null for other keys.
 * `key` is KeyboardEvent.key ("+" is "=" unshifted on US keyboards).
 */
export function keyStep(key: string, shift: boolean, rect: RelRect, size: PageSize): RelRect | null {
  const step = shift ? BIG_STEP : STEP;
  switch (key) {
    case 'ArrowLeft':
      return moveRect(rect, -step, 0, size);
    case 'ArrowRight':
      return moveRect(rect, step, 0, size);
    case 'ArrowUp':
      return moveRect(rect, 0, -step, size);
    case 'ArrowDown':
      return moveRect(rect, 0, step, size);
    case '+':
    case '=':
      return resizeAroundCentre(rect, STEP, size);
    case '-':
    case '_':
      return resizeAroundCentre(rect, -STEP, size);
    default:
      return null;
  }
}

export function sameRect(a: RelRect | null | undefined, b: RelRect | null | undefined, eps = 1e-6): boolean {
  if (!a || !b) return a === b;
  return (
    Math.abs(a.x - b.x) <= eps &&
    Math.abs(a.y - b.y) <= eps &&
    Math.abs(a.w - b.w) <= eps &&
    Math.abs(a.h - b.h) <= eps
  );
}

const percent = (value: number) => `${Math.round(value * 100)} %`;

/** For the live region: "QR-Feld: links 12 %, oben 40 %, Größe 30 %" (size: share of the width). */
export function describeRect(rect: RelRect): string {
  return `QR-Feld: links ${percent(rect.x)}, oben ${percent(rect.y)}, Größe ${percent(rect.w)}`;
}
