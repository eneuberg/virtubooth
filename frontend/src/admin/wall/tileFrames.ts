/**
 * The analysis frames on a Live tile: the summary's boxes (normalised to the full
 * photo) mapped onto the tile's crop. The tile shows the thumbnail `object-cover` in
 * a 3:4 frame, so a landscape photo loses its sides and a squarer one a little top and
 * bottom; a frame is moved and scaled with the picture, clipped to what is visible,
 * and dropped when (almost) nothing of it is left. Big frames carry their label, small
 * ones only the outline (tileFrames.test.ts).
 */
import type { BoxKind, PhotoAnalysisSummary } from './types';

/** the tile's photo frame (PhotoTile: aspect-[3/4]) */
export const TILE_ASPECT = 3 / 4;
/** less than this (of the tile's width or height) still visible: no frame */
const MIN_VISIBLE = 0.04;
/** a label from this size on (of the tile): about 48 px wide on a phone's tile, enough
 * for a short name at 10 px (a longer one is cut with an ellipsis) */
const LABEL_MIN_W = 0.26;
const LABEL_MIN_H = 0.08;
/** at most this many frames on one tile (the biggest, so it stays readable) */
export const MAX_TILE_FRAMES = 12;

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Where a picture of `imageAspect` (w/h) lies in a box of `boxAspect` with
 * `object-fit: cover`, in fractions of the box (may reach outside 0..1). */
export function coverRect(imageAspect: number, boxAspect: number): Rect {
  if (!(imageAspect > 0) || !(boxAspect > 0)) return { x: 0, y: 0, w: 1, h: 1 };
  if (imageAspect > boxAspect) {
    // wider: full height, the sides are cut
    const w = imageAspect / boxAspect;
    return { x: (1 - w) / 2, y: 0, w, h: 1 };
  }
  const h = boxAspect / imageAspect;
  return { x: 0, y: (1 - h) / 2, w: 1, h };
}

export interface TileFrame extends Rect {
  kind: BoxKind;
  /** the object's name when the frame is big enough for it */
  label: string | null;
}

/** A box on the photo mapped onto the tile and clipped to it; null when it is (almost) cut away. */
export function mapBox(box: Rect, picture: Rect): Rect | null {
  const left = picture.x + box.x * picture.w;
  const top = picture.y + box.y * picture.h;
  const x0 = Math.max(0, left);
  const y0 = Math.max(0, top);
  const x1 = Math.min(1, left + box.w * picture.w);
  const y1 = Math.min(1, top + box.h * picture.h);
  if (x1 - x0 < MIN_VISIBLE || y1 - y0 < MIN_VISIBLE) return null;
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

/** The summary's frames on a tile showing a photo of `photoAspect` (w/h), biggest first. */
export function tileFrames(
  summary: Pick<PhotoAnalysisSummary, 'objects' | 'boxes'>,
  photoAspect: number,
  tileAspect = TILE_ASPECT,
): TileFrame[] {
  const picture = coverRect(photoAspect, tileAspect);
  const out: TileFrame[] = [];
  for (const o of summary.objects) {
    const r = o.box && mapBox(o.box, picture);
    if (r) out.push({ kind: 'object', ...r, label: o.label_de });
  }
  for (const b of summary.boxes ?? []) {
    const r = mapBox(b, picture);
    if (r) out.push({ kind: b.kind, ...r, label: null });
  }
  const kept = out.toSorted((a, b) => b.w * b.h - a.w * a.h).slice(0, MAX_TILE_FRAMES);
  for (const f of kept) if (f.w < LABEL_MIN_W || f.h < LABEL_MIN_H) f.label = null;
  return kept;
}

const pct = (v: number) => `${(v * 100).toFixed(2)}%`;

/** CSS geometry of a frame in % of the tile. */
export function frameStyle(f: Rect): { left: string; top: string; width: string; height: string } {
  return { left: pct(f.x), top: pct(f.y), width: pct(f.w), height: pct(f.h) };
}
