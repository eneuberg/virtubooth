/**
 * Photo slides built with DOM calls (no HTML strings), and which image size a screen needs.
 */
import { formatRelative } from '@/lib/format';
import type { WallPhoto } from '../api/types';

/** `l` (stored full size) on 4K screens, `m` (1280 px) otherwise. */
export function spotlightUrl(photo: WallPhoto): string {
  const px = Math.max(window.screen?.width ?? 0, window.innerWidth) * (window.devicePixelRatio || 1);
  return px >= 2560 ? photo.urls.l : photo.urls.m;
}

export function aspectOf(photo: { width: number; height: number }): number {
  const a = photo.width / photo.height;
  return Number.isFinite(a) && a > 0 ? Math.min(3, Math.max(0.33, a)) : 0.75;
}

/** Size of a photo card that fits the box. */
export function fitBox(aspect: number, maxW: number, maxH: number): { w: number; h: number } {
  let w = maxW;
  let h = w / aspect;
  if (h > maxH) {
    h = maxH;
    w = h * aspect;
  }
  return { w: Math.round(w), h: Math.round(h) };
}

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export interface Box {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

export interface SlideOptions {
  /** client clock minus server clock */
  skewMs: number;
  /** the corner overlay's box (viewport coordinates), null without one */
  corner?: Box | null;
}

/** Share of the stage a photo card may take at most. */
const MAX_W = 0.74;
const MAX_H = 0.84;
/** room around the card for the caption that hangs out of it (and a tilt), in vmin */
const CLEAR_VMIN = 4.5;

/**
 * The card size for a photo: as large as fits the stage, centred, and clear of the
 * corner overlay. A corner beside the card limits its width (the card stays centred,
 * so both sides shrink), one above or below it limits its height; whichever leaves the
 * larger card wins. The caption hangs out of the card's bottom left corner by less than
 * CLEAR_VMIN, so it never reaches the corner either.
 */
export function slideSize(
  aspect: number,
  stage: Box,
  corner: Box | null,
  vmin: number,
): { w: number; h: number } {
  const width = stage.right - stage.left;
  const height = stage.bottom - stage.top;
  const free = fitBox(aspect, width * MAX_W, height * MAX_H);
  if (!corner || corner.right <= corner.left || corner.bottom <= corner.top) return free;
  const cx = (stage.left + stage.right) / 2;
  const cy = (stage.top + stage.bottom) / 2;
  const clear = CLEAR_VMIN * vmin;
  const overlaps = (size: { w: number; h: number }): boolean =>
    cx - size.w / 2 - clear < corner.right &&
    cx + size.w / 2 + clear > corner.left &&
    cy - size.h / 2 - clear < corner.bottom &&
    cy + size.h / 2 + clear > corner.top;
  if (!overlaps(free)) return free;
  // beside: half the width up to the corner's near edge
  const halfW = corner.left >= cx ? corner.left - cx : corner.right <= cx ? cx - corner.right : 0;
  // above or below: half the height up to the corner's near edge
  const halfH = corner.top >= cy ? corner.top - cy : corner.bottom <= cy ? cy - corner.bottom : 0;
  const options = [
    fitBox(aspect, Math.min(width * MAX_W, 2 * (halfW - clear) - 2), height * MAX_H),
    fitBox(aspect, width * MAX_W, Math.min(height * MAX_H, 2 * (halfH - clear) - 2)),
  ].filter((o) => o.w > 0 && o.h > 0 && !overlaps(o));
  if (options.length === 0) return free;
  return options.reduce((a, b) => (b.w * b.h > a.w * a.h ? b : a));
}

function vminOf(): number {
  return Math.min(window.innerWidth, window.innerHeight) / 100;
}

function sizeFor(stage: HTMLElement, aspect: number, corner: Box | null | undefined) {
  const rect = stage.getBoundingClientRect();
  const box =
    rect.width > 0 && rect.height > 0
      ? rect
      : { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight };
  return slideSize(aspect, box, corner ?? null, vminOf());
}

/** The caption's age line („vor 3 Min.“) at `now` (client clock). */
export function ageText(takenAt: string, now: number, skewMs: number): string {
  return formatRelative(takenAt, now - skewMs);
}

/**
 *  div.wall-slide > figure.wall-frame (sized) > div.wall-card > [div.wall-pic > img, figcaption.wall-caption]
 */
export function buildSlide(stage: HTMLElement, photo: WallPhoto, img: HTMLImageElement, opts: SlideOptions) {
  const slide = el('div', 'wall-slide');
  slide.dataset['photo'] = photo.id;
  slide.dataset['takenAt'] = photo.taken_at;
  const aspect = aspectOf(photo);
  slide.dataset['aspect'] = String(aspect);
  const frame = el('figure', 'wall-frame');
  const size = sizeFor(stage, aspect, opts.corner);
  frame.style.width = `${size.w}px`;
  frame.style.height = `${size.h}px`;
  const card = el('div', 'wall-card');
  const pic = el('div', 'wall-pic');
  img.className = 'wall-photo';
  img.alt = `Foto von ${photo.author}`;
  pic.append(img);
  const caption = el('figcaption', 'wall-caption');
  caption.append(el('span', 'wall-caption-by', `von ${photo.author}`));
  if (photo.instagram) caption.append(el('span', 'wall-caption-ig', `@${photo.instagram.replace(/^@/, '')}`));
  caption.append(el('span', 'wall-caption-ago', ageText(photo.taken_at, Date.now(), opts.skewMs)));
  card.append(pic, caption);
  frame.append(card);
  slide.append(frame);
  return slide;
}

/** Fit the stage's slides again (the stage or the corner changed size). */
export function relayoutSlides(stage: HTMLElement, corner: Box | null): void {
  for (const slide of stage.querySelectorAll<HTMLElement>('.wall-slide')) {
    const frame = slide.querySelector<HTMLElement>('.wall-frame');
    const aspect = Number(slide.dataset['aspect']);
    if (!frame || !(aspect > 0)) continue;
    const size = sizeFor(stage, aspect, corner);
    const w = `${size.w}px`;
    const h = `${size.h}px`;
    if (frame.style.width !== w) frame.style.width = w;
    if (frame.style.height !== h) frame.style.height = h;
  }
}

/** Bring every caption's age („vor 3 Min.“) up to date. */
export function refreshAges(stage: HTMLElement, skewMs: number, now: number = Date.now()): void {
  for (const slide of stage.querySelectorAll<HTMLElement>('.wall-slide')) {
    const takenAt = slide.dataset['takenAt'];
    const ago = slide.querySelector('.wall-caption-ago');
    if (!takenAt || !ago) continue;
    const text = ageText(takenAt, now, skewMs);
    if (ago.textContent !== text) ago.textContent = text;
  }
}
