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

export interface SlideOptions {
  /** client clock minus server clock */
  skewMs: number;
}

/**
 *  div.wall-slide > figure.wall-frame (sized) > div.wall-card > [div.wall-pic > img, figcaption.wall-caption]
 */
export function buildSlide(stage: HTMLElement, photo: WallPhoto, img: HTMLImageElement, opts: SlideOptions) {
  const slide = el('div', 'wall-slide');
  slide.dataset['photo'] = photo.id;
  const frame = el('figure', 'wall-frame');
  const rect = stage.getBoundingClientRect();
  const width = rect.width || window.innerWidth;
  const height = rect.height || window.innerHeight;
  const size = fitBox(aspectOf(photo), width * 0.74, height * 0.84);
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
  caption.append(el('span', 'wall-caption-ago', formatRelative(photo.taken_at, Date.now() - opts.skewMs)));
  card.append(pic, caption);
  frame.append(card);
  slide.append(frame);
  return slide;
}
