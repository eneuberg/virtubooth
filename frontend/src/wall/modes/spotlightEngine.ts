/**
 * Spotlight: one photo at a time, chosen by the configured algorithm, changed every
 * `interval_s` with a transition. Imperative (DOM + WAAPI), driven by `update(state)`.
 *
 * - The next photo is chosen right after a change and decoded in the background.
 * - When the shown (or the upcoming) photo is removed, the engine changes at once.
 * - Every image leaves through the preloader's release (src = '').
 * - The caption's age („vor 3 Min.“) counts on while a photo is shown.
 * - Cards stay clear of the corner overlay; they are fitted again when the stage or the
 *   corner changes size (TV resolution, fullscreen, the QR code switched on).
 */
import type { ConcreteTransition, WallConfig, WallPhoto } from '../api/types';
import { webglAvailable } from '../gl/gl';
import { mathRng, type Rng } from '../rng';
import { createSelector, recordShown, type SelectContext, type Selector } from '../select/algorithms';
import { pickTransition, prefersReducedMotion, TRANSITIONS } from '../transitions';
import { createPreloader, type Preloader } from '../tv/preload';
import { buildSlide, refreshAges, relayoutSlides, spotlightUrl, type Box } from './slide';

export interface SpotlightInput {
  photos: readonly WallPhoto[];
  fresh: readonly string[];
  highlights: readonly string[];
  config: WallConfig;
  clockSkewMs: number;
}

interface Shown {
  photo: WallPhoto;
  el: HTMLElement;
  img: HTMLImageElement;
}

const QUICK_MS = 500;
const RETRY_MS = 1500;
const AGE_REFRESH_MS = 15_000;

export class SpotlightEngine {
  private input: SpotlightInput;
  private readonly stage: HTMLElement;
  private readonly rng: Rng;
  private readonly preloader: Preloader;
  private readonly ctx: SelectContext;
  private selector: Selector;
  private selectorKey: string;
  private current: Shown | null = null;
  private pending: WallPhoto | null = null;
  private lastTransition: ConcreteTransition | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private chain: Promise<void> = Promise.resolve();
  private abort: AbortController | null = null;
  private queued = false;
  private stopped = false;
  private ageTimer: ReturnType<typeof setInterval> | undefined;
  private observer: ResizeObserver | null = null;
  private observedCorner: Element | null = null;

  constructor(
    stage: HTMLElement,
    input: SpotlightInput,
    rng: Rng = mathRng,
    preloader: Preloader = createPreloader(3),
  ) {
    this.stage = stage;
    this.input = input;
    this.rng = rng;
    this.preloader = preloader;
    this.ctx = { shown: new Map(), fresh: input.fresh, highlights: input.highlights };
    this.selectorKey = this.keyOf(input.config);
    this.selector = this.makeSelector();
  }

  start(): void {
    this.ageTimer = setInterval(() => refreshAges(this.stage, this.input.clockSkewMs), AGE_REFRESH_MS);
    if (typeof ResizeObserver === 'function') {
      this.observer = new ResizeObserver(() => this.relayout());
      this.observer.observe(this.stage);
    } else {
      window.addEventListener('resize', this.relayout);
    }
    this.enqueue(false);
  }

  stop(): void {
    this.stopped = true;
    clearTimeout(this.timer);
    clearInterval(this.ageTimer);
    this.observer?.disconnect();
    this.observer = null;
    this.observedCorner = null;
    window.removeEventListener('resize', this.relayout);
    this.abort?.abort();
    this.preloader.clear();
    for (const img of this.stage.querySelectorAll('img')) this.preloader.release(img);
    this.stage.replaceChildren();
    this.current = null;
  }

  update(input: SpotlightInput): void {
    this.input = input;
    this.ctx.fresh = input.fresh;
    this.ctx.highlights = input.highlights;
    const key = this.keyOf(input.config);
    if (key !== this.selectorKey) {
      this.selectorKey = key;
      this.selector = this.makeSelector();
      this.pending = null;
    }
    const ids = new Set(input.photos.map((p) => p.id));
    if (this.pending && !ids.has(this.pending.id)) this.pending = null;
    if (this.current && !ids.has(this.current.photo.id)) {
      // the shown photo was removed: change now
      clearTimeout(this.timer);
      this.abort?.abort();
      this.enqueue(true);
    } else if (!this.current && !this.queued && input.photos.length > 0) {
      this.enqueue(false);
    }
    // a config change may have moved, grown or removed the corner (rendered by now)
    this.relayout();
  }

  /** The corner overlay's box, watched for size changes. */
  private corner(): Box | null {
    const corner = this.stage.closest('.wall')?.querySelector('.wall-corner') ?? null;
    if (corner !== this.observedCorner && this.observer) {
      if (this.observedCorner) this.observer.unobserve(this.observedCorner);
      if (corner) this.observer.observe(corner);
    }
    this.observedCorner = corner;
    return corner ? corner.getBoundingClientRect() : null;
  }

  private readonly relayout = (): void => {
    if (!this.stopped) relayoutSlides(this.stage, this.corner());
  };

  private keyOf(config: WallConfig): string {
    return `${config.spotlight.algorithm}:${config.spotlight.n}`;
  }

  private makeSelector(): Selector {
    const { algorithm, n } = this.input.config.spotlight;
    return createSelector(algorithm, { n }, this.rng);
  }

  private enqueue(quick: boolean): void {
    if (this.stopped || this.queued) return;
    this.queued = true;
    this.chain = this.chain
      .then(() => {
        this.queued = false;
        return this.step(quick);
      })
      .catch(() => undefined);
  }

  private schedule(ms: number): void {
    clearTimeout(this.timer);
    if (!this.stopped) this.timer = setTimeout(() => this.enqueue(false), ms);
  }

  private choose(): WallPhoto | null {
    const pool = this.input.photos;
    const { algorithm } = this.input.config.spotlight;
    if (algorithm === 'fresh_first') {
      const ids = new Map(pool.map((p) => [p.id, p]));
      const fresh = this.input.fresh.find((id) => ids.has(id) && !this.ctx.shown.has(id));
      if (fresh !== undefined) {
        this.pending = null;
        return ids.get(fresh)!;
      }
    }
    const pending = this.pending && pool.some((p) => p.id === this.pending!.id) ? this.pending : null;
    this.pending = null;
    return pending ?? this.selector.next(pool, this.ctx);
  }

  private async step(quick: boolean): Promise<void> {
    if (this.stopped) return;
    const { spotlight, look } = this.input.config;
    if (this.input.photos.length === 0) {
      await this.clear();
      return;
    }
    let photo = this.choose();
    // never the same photo again right away when there is a choice
    if (photo && this.current && photo.id === this.current.photo.id && this.input.photos.length > 1) {
      photo = this.selector.next(this.input.photos, this.ctx);
    }
    if (!photo) return;
    let img: HTMLImageElement;
    try {
      img = await this.preloader.take(spotlightUrl(photo));
    } catch {
      recordShown(this.ctx, photo.id); // a broken image goes to the back of the line
      this.schedule(RETRY_MS);
      return;
    }
    if (this.stopped || !this.input.photos.some((p) => p.id === photo.id)) {
      this.preloader.release(img);
      if (!this.stopped) this.enqueue(true);
      return;
    }
    const slide = buildSlide(this.stage, photo, img, {
      skewMs: this.input.clockSkewMs,
      corner: this.corner(),
    });
    this.stage.append(slide);
    const from = this.current;
    const wantsGl =
      spotlight.transition === 'random' ||
      spotlight.transition === 'dither' ||
      spotlight.transition === 'pixelate';
    const kind: ConcreteTransition = quick
      ? 'crossfade'
      : pickTransition(spotlight.transition, this.lastTransition, this.rng, {
          calm: look.calm,
          reducedMotion: prefersReducedMotion(),
          webgl: wantsGl && webglAvailable(),
        });
    if (!quick) this.lastTransition = kind;
    this.current = { photo, el: slide, img };
    recordShown(this.ctx, photo.id);
    const abort = new AbortController();
    this.abort = abort;
    this.stage.dataset['transition'] = kind;
    await TRANSITIONS[kind]({
      stage: this.stage,
      from: from?.el ?? null,
      to: slide,
      ms: quick ? QUICK_MS : spotlight.transition_ms,
      hold: spotlight.interval_s * 1000,
      signal: abort.signal,
      colors: { primary: look.primary, secondary: look.secondary },
      rng: this.rng,
    });
    delete this.stage.dataset['transition'];
    if (this.abort === abort) this.abort = null;
    if (from) {
      this.preloader.release(from.img);
      from.el.remove();
    }
    if (this.stopped) return;
    // removed while it came in?
    if (!this.input.photos.some((p) => p.id === photo.id)) {
      this.enqueue(true);
      return;
    }
    this.prepareNext();
    this.schedule(spotlight.interval_s * 1000);
  }

  private prepareNext(): void {
    if (this.input.photos.length < 2) return;
    const next = this.selector.next(this.input.photos, this.ctx);
    this.pending = next;
    if (next) this.preloader.warm(spotlightUrl(next));
  }

  /** No photos left: fade the last one out. */
  private async clear(): Promise<void> {
    const from = this.current;
    this.current = null;
    if (!from) return;
    const anim = from.el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: QUICK_MS, fill: 'forwards' });
    await anim.finished.catch(() => undefined);
    this.preloader.release(from.img);
    from.el.remove();
  }
}
