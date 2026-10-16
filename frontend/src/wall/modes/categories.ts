import { MAX_WINNERS, type CategoryWinner, type WallBox, type WallCategory } from '../api/types';

/**
 * The categories the wall may show: not disabled in the live config, without winners
 * that were removed since /categories answered, and with at least one winner left; at
 * most 10 winners each, in the server's order. Each winner keeps its AI comment; an
 * older server's single `verdict` becomes the comment of the winner it names.
 */
export function visibleCategories(
  categories: readonly WallCategory[],
  disabled: readonly string[],
  removed: readonly string[],
): WallCategory[] {
  const off = new Set(disabled);
  const gone = new Set(removed);
  return categories
    .filter((c) => !off.has(c.id))
    .map((c) => {
      let winners = c.winners.map((w) => ({ ...w, comment: w.comment ?? null }));
      const verdict = c.verdict && !(c.verdict.photo_id && gone.has(c.verdict.photo_id)) ? c.verdict : null;
      if (verdict && winners.every((w) => !w.comment)) {
        const at = verdictIndex({ winners, verdict });
        winners = winners.map((w, i) =>
          i === at ? { ...w, comment: { text: verdict.text, emoji: verdict.emoji } } : w,
        );
      }
      return {
        id: c.id,
        emoji: c.emoji,
        title: c.title,
        line: c.line,
        winners: winners.filter((w) => !gone.has(w.photo.id)).slice(0, MAX_WINNERS),
        verdict,
      };
    })
    .filter((c) => c.winners.length > 0);
}

/** The index of the winner a (deprecated) verdict is about: its `photo_id`, else the first. */
export function verdictIndex(category: Pick<WallCategory, 'winners' | 'verdict'>): number {
  const id = category.verdict?.photo_id;
  const at = id ? category.winners.findIndex((w) => w.photo.id === id) : -1;
  return at < 0 ? 0 : at;
}

export type VerdictAlign = 'start' | 'center' | 'end';

/**
 * A comment under photo `index` of `count` (1–3 in a row) may be wider than the photo:
 * under the first it starts at the photo's left edge, under the last it ends at its
 * right edge, else it is centred, so it stays inside the winners' column.
 */
export function verdictAlign(index: number, count: number): VerdictAlign {
  if (count <= 1) return 'center';
  if (index === 0) return 'start';
  return index === count - 1 ? 'end' : 'center';
}

/** Columns of the compact grid (more than 3 winners): 2 rows, TV-safe sizes. */
export function compactColumns(count: number): number {
  return Math.max(2, Math.ceil(count / 2));
}

/** Winner photo ids in catalogue order (the `highlights` algorithm). */
export function highlightIds(categories: readonly WallCategory[]): string[] {
  const ids: string[] = [];
  for (const c of categories) for (const w of c.winners) if (!ids.includes(w.photo.id)) ids.push(w.photo.id);
  return ids;
}

/** The winner's main line and its value chip (older servers: the label alone). */
export function captionOf(w: CategoryWinner): { headline: string; detail: string | null } {
  return { headline: w.headline || w.label, detail: w.headline ? (w.detail ?? null) : null };
}

const pct = (v: number) => Math.round(v * 10_000) / 100;

/** A frame in percent of its cell. */
export interface FrameRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** Below this share of the frame in view, the compact cell draws none (the name stays). */
export const MIN_VISIBLE = 0.4;

/**
 * Where the focus object's box (0..1 of the photo) lies in a cell that shows the photo
 * with `object-fit: cover`, centred: `photoAspect` and `cellAspect` are width / height.
 * The same aspect (the normal row) is the box itself; a cropped cell (the compact grid's
 * 3:4) shifts and scales it, cut at the edges, and drops it when less than MIN_VISIBLE
 * of it is in view. Percent, null: no frame.
 */
export function coverBox(
  box: WallBox | null | undefined,
  photoAspect: number,
  cellAspect: number,
): FrameRect | null {
  if (!box || !(box.w > 0 && box.h > 0)) return null;
  let { x, y, w, h } = box;
  if (photoAspect > cellAspect) {
    // wider than the cell: cropped left and right
    const k = photoAspect / cellAspect;
    x = (1 - k) / 2 + x * k;
    w *= k;
  } else if (photoAspect < cellAspect) {
    const k = cellAspect / photoAspect;
    y = (1 - k) / 2 + y * k;
    h *= k;
  }
  const left = Math.max(0, x);
  const top = Math.max(0, y);
  const right = Math.min(1, x + w);
  const bottom = Math.min(1, y + h);
  if (right <= left || bottom <= top) return null;
  if (((right - left) * (bottom - top)) / (w * h) < MIN_VISIBLE) return null;
  return { left: pct(left), top: pct(top), width: pct(right - left), height: pct(bottom - top) };
}
