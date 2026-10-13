/**
 * Gallery: a mosaic of `rows` rows that scroll sideways for ever (alternating
 * directions). Each row has a fixed pool of tiles; a tile that left the screen moves to
 * the other end and gets the next photo, so the number of live <img> never grows.
 */
import type { GallerySpeed, WallPhoto } from '../api/types';
import { mathRng, type Rng } from '../rng';
import { createSelector, emptyContext, recordShown, type Selector } from '../select/algorithms';
import { releaseImage } from '../tv/preload';
import { aspectOf } from './slide';

export interface GalleryInput {
  photos: readonly WallPhoto[];
  rows: number;
  speed: GallerySpeed;
}

/** scroll speed in screen heights per second */
export const SPEEDS: Record<GallerySpeed, number> = { slow: 0.028, medium: 0.055, fast: 0.1 };
const MIN_ASPECT = 0.62;
const MAX_ASPECT = 1.6;

interface Tile {
  el: HTMLElement;
  img: HTMLImageElement;
  label: HTMLElement;
  photo: WallPhoto | null;
  x: number;
  w: number;
}

interface Row {
  el: HTMLElement;
  strip: HTMLElement;
  tiles: Tile[];
  dir: 1 | -1;
  speed: number;
  offset: number;
}

export class GalleryEngine {
  private input: GalleryInput;
  private readonly stage: HTMLElement;
  private readonly selector: Selector;
  private readonly ctx = emptyContext();
  private rows: Row[] = [];
  private frame = 0;
  private last: number | null = null;
  private width = 0;
  private height = 0;
  private tileH = 0;
  private gap = 0;

  constructor(stage: HTMLElement, input: GalleryInput, rng: Rng = mathRng) {
    this.stage = stage;
    this.input = input;
    this.selector = createSelector('shuffle', { n: 1 }, rng);
  }

  start(): void {
    this.build();
    window.addEventListener('resize', this.onResize);
    this.frame = requestAnimationFrame(this.tick);
  }

  stop(): void {
    cancelAnimationFrame(this.frame);
    window.removeEventListener('resize', this.onResize);
    this.teardown();
  }

  private readonly onResize = (): void => this.build();

  update(input: GalleryInput): void {
    const relayout = input.rows !== this.input.rows;
    this.input = input;
    if (relayout) {
      this.build();
      return;
    }
    for (const row of this.rows) row.speed = this.speedFor(this.rows.indexOf(row));
    // removed photos leave at once: their tiles get another photo in place
    const ids = new Set(input.photos.map((p) => p.id));
    for (const row of this.rows) {
      for (const tile of row.tiles) {
        if (tile.photo && !ids.has(tile.photo.id)) this.assign(tile, this.nextPhoto(), true);
      }
    }
  }

  private speedFor(index: number): number {
    return this.height * SPEEDS[this.input.speed] * (1 + 0.18 * (index % 2));
  }

  private nextPhoto(): WallPhoto | null {
    const photo = this.selector.next(this.input.photos, this.ctx);
    if (photo) recordShown(this.ctx, photo.id);
    return photo;
  }

  private urlFor(photo: WallPhoto): string {
    // thumbnails (400 px) are sharp enough for small tiles and keep TV memory low
    return this.tileH * (window.devicePixelRatio || 1) > 420 ? photo.urls.m : photo.urls.s;
  }

  /** `keepWidth`: a swap in place (on screen) must not push into the neighbours */
  private assign(tile: Tile, photo: WallPhoto | null, keepWidth = false): void {
    tile.photo = photo;
    if (!photo) {
      releaseImage(tile.img);
      tile.el.hidden = true;
      return;
    }
    tile.el.hidden = false;
    if (!keepWidth) {
      tile.w = Math.round(this.tileH * Math.min(MAX_ASPECT, Math.max(MIN_ASPECT, aspectOf(photo))));
      tile.el.style.width = `${tile.w}px`;
    }
    tile.img.alt = `Foto von ${photo.author}`;
    tile.img.src = this.urlFor(photo);
    tile.label.textContent = photo.author;
  }

  private teardown(): void {
    for (const row of this.rows) {
      for (const tile of row.tiles) releaseImage(tile.img);
      row.el.remove();
    }
    this.rows = [];
  }

  private build(): void {
    this.teardown();
    const rect = this.stage.getBoundingClientRect();
    this.width = rect.width || window.innerWidth;
    this.height = rect.height || window.innerHeight;
    const rows = Math.min(6, Math.max(2, this.input.rows));
    this.gap = Math.round(this.height * 0.02);
    this.tileH = Math.floor((this.height - this.gap * (rows - 1)) / rows);
    const minW = this.tileH * MIN_ASPECT + this.gap;
    const maxW = this.tileH * MAX_ASPECT + this.gap;
    const count = Math.ceil((this.width + 2 * maxW) / minW) + 1;
    for (let r = 0; r < rows; r++) {
      const el = document.createElement('div');
      el.className = 'wall-row';
      el.style.top = `${r * (this.tileH + this.gap)}px`;
      el.style.height = `${this.tileH}px`;
      const strip = document.createElement('div');
      strip.className = 'wall-strip';
      el.append(strip);
      const row: Row = {
        el,
        strip,
        tiles: [],
        dir: r % 2 === 0 ? -1 : 1,
        speed: this.speedFor(r),
        offset: 0,
      };
      // start somewhere in the middle: both directions have tiles on screen at once
      let x = -maxW;
      for (let i = 0; i < count; i++) {
        const tileEl = document.createElement('div');
        tileEl.className = 'wall-tile';
        const img = new Image();
        img.decoding = 'async';
        img.draggable = false;
        const label = document.createElement('span');
        label.className = 'wall-tile-by';
        tileEl.append(img, label);
        strip.append(tileEl);
        const tile: Tile = { el: tileEl, img, label, photo: null, x, w: 0 };
        this.assign(tile, this.nextPhoto());
        tile.x = x;
        tileEl.style.transform = `translate3d(${x}px, 0, 0)`;
        x += tile.w + this.gap;
        row.tiles.push(tile);
      }
      this.rows.push(row);
      this.stage.append(el);
    }
  }

  private readonly tick = (now: number): void => {
    this.frame = requestAnimationFrame(this.tick);
    const dt = this.last === null ? 0 : Math.min(0.1, (now - this.last) / 1000);
    this.last = now;
    for (const row of this.rows) {
      row.offset += row.dir * row.speed * dt;
      row.strip.style.transform = `translate3d(${row.offset.toFixed(2)}px, 0, 0)`;
      this.recycle(row);
    }
  };

  /** Tiles that left the screen go to the other end with the next photo. */
  private recycle(row: Row): void {
    const left = -row.offset; // the screen's left edge in strip coordinates
    const right = left + this.width;
    for (const tile of row.tiles) {
      if (row.dir < 0 && tile.x + tile.w < left - this.gap) {
        const end = Math.max(...row.tiles.map((t) => t.x + t.w));
        this.assign(tile, this.nextPhoto());
        tile.x = end + this.gap;
        tile.el.style.transform = `translate3d(${tile.x}px, 0, 0)`;
      } else if (row.dir > 0 && tile.x > right + this.gap) {
        const start = Math.min(...row.tiles.map((t) => t.x));
        this.assign(tile, this.nextPhoto());
        tile.x = start - this.gap - tile.w;
        tile.el.style.transform = `translate3d(${tile.x}px, 0, 0)`;
      }
    }
  }
}
