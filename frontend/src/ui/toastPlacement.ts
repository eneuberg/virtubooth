/**
 * Where the toast goes, so it never covers the controls someone needs next.
 *
 * The rule: the toast keeps the place its page gives it (`ToastSlot className`: above
 * the bottom bar, above the camera controls, bottom right on desktop) unless an action
 * area lies under it. Then it moves up to the lowest free slot: just above that area
 * (and above any area it meets on the way), never onto a bar further up. Action areas
 * carry `data-toast-avoid` ({@link toastAvoid}): an open sheet or dialog and its footer,
 * the photo viewer's top bar, panel and buttons, the selection bar, the bottom bar, the
 * camera header, strip, hint and controls.
 *
 * Only the topmost layer counts: while a sheet, dialog or the viewer is open, its areas
 * (the page under the scrim can't be tapped anyway); otherwise the page's. With no free
 * slot, an area that holds other areas may be covered, the ones inside it not: a sheet
 * as tall as the screen keeps its footer free. With none at all, the toast stays put.
 */

/** Marks an element as an action area the toast never covers (spread it on the element). */
export const toastAvoid = { 'data-toast-avoid': '' } as const;

/** space between the toast and the area it clears, px */
export const TOAST_GAP = 8;

export interface Box {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

const contains = (outer: Box, inner: Box) =>
  outer !== inner &&
  outer.top <= inner.top &&
  outer.bottom >= inner.bottom &&
  outer.left <= inner.left &&
  outer.right >= inner.right;

/**
 * How far (px, ≥ 0) the toast must move up from `toast` (its box at the page's place).
 * It takes the lowest free slot: its own place, or just above one of the `areas`, no
 * higher than `minTop`. Free means it overlaps no area; failing that, no area that
 * holds no other area (a sheet may be covered, its footer not). Failing that too, it
 * keeps its place.
 */
export function toastLift(
  toast: Box,
  areas: ReadonlyArray<Box>,
  minTop: number,
  gap: number = TOAST_GAP,
): number {
  const height = toast.bottom - toast.top;
  // an area beside the toast (bottom right on desktop) is no obstacle
  const near = areas.filter((a) => a.left < toast.right && a.right > toast.left && a.bottom > a.top);
  const slots = [toast.top, ...near.map((a) => a.top - gap - height)].filter(
    (top) => top >= minTop && top <= toast.top,
  );
  const leaves = near.filter((a) => !near.some((b) => contains(a, b)));
  for (const obstacles of [near, leaves]) {
    const free = slots.filter((top) => !obstacles.some((a) => a.top < top + height && a.bottom > top));
    // the lowest free slot: the shortest move
    if (free.length > 0) return toast.top - Math.max(...free);
  }
  return 0;
}

/** The y of a computed `translate` ("none", "0px -96px"), px. */
export function translateY(value: string): number {
  const parts = value.trim().split(/\s+/);
  return parts.length > 1 ? Number.parseFloat(parts[1] ?? '0') || 0 : 0;
}

/** Sheets, dialogs and the photo viewer (still open: not sliding out). */
const LAYER = '.vb-scrim:not([data-exiting])';

/**
 * How far running animations (a sheet sliding in) have moved `el` down from where it
 * comes to rest, px. The toast heads for the resting place straight away, alongside the
 * sheet, instead of waiting for the slide to end.
 */
function slideOffset(el: Element): number {
  let offset = 0;
  for (let node: Element | null = el; node; node = node.parentElement) {
    if (typeof node.getAnimations !== 'function') return 0;
    if (!node.getAnimations().some((a) => a.playState === 'running')) continue;
    const style = getComputedStyle(node);
    offset += translateY(style.translate);
    if (style.transform && style.transform !== 'none') {
      offset += new DOMMatrixReadOnly(style.transform).m42;
    }
  }
  return offset;
}

/** The action areas of the topmost layer, as boxes where they (come to) rest on screen. */
export function actionAreas(doc: Document = document): Box[] {
  const layer = [...doc.querySelectorAll(LAYER)].at(-1);
  const boxes: Box[] = [];
  for (const el of doc.querySelectorAll('[data-toast-avoid]')) {
    const inTopLayer = layer ? layer.contains(el) : el.closest('.vb-scrim') === null;
    if (!inTopLayer) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const dy = slideOffset(el);
    boxes.push({ top: r.top - dy, bottom: r.bottom - dy, left: r.left, right: r.right });
  }
  return boxes;
}

/**
 * The lift for the toast region right now. It reads the region's current shift back out
 * of its box, so it is right mid-transition too. The region's `scroll-margin-top` is the
 * highest its top may go (the safe area).
 */
export function measureToastLift(region: HTMLElement): number {
  const style = getComputedStyle(region);
  const shift = translateY(style.translate);
  const r = region.getBoundingClientRect();
  const home = { top: r.top - shift, bottom: r.bottom - shift, left: r.left, right: r.right };
  const minTop = Number.parseFloat(style.scrollMarginTop) || 0;
  return Math.round(toastLift(home, actionAreas(region.ownerDocument), minTop));
}
