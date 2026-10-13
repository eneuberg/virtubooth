/**
 * The wall's animated background on one 2D canvas. Framework-free: the admin preview
 * imports it too.
 *
 *   const bg = mountBackground(canvas, config.look);
 *   bg.update(nextLook);
 *   bg.destroy();
 *
 * The canvas is drawn at ≤ 960×540 and scaled by CSS; frames are capped at `look.fps`;
 * nothing is drawn while the page is hidden; `plain` paints once (no animation loop);
 * `look.calm` and reduced motion slow everything down.
 */
import type { WallLook } from '../api/types';
import { mathRng, seededRng } from '../rng';
import { createFpsLimiter } from './fps';
import { PRESET_SCENES, hexToRgb, type Scene } from './presets';

export { createFpsLimiter, type FpsLimiter } from './fps';

export interface BackgroundHandle {
  update(look: WallLook): void;
  destroy(): void;
}

export interface BackgroundOptions {
  /** internal width cap (default 960) */
  maxWidth?: number;
}

const NOISE = 128;

function noiseTile(ctx: CanvasRenderingContext2D): CanvasPattern | null {
  const tile = document.createElement('canvas');
  tile.width = NOISE;
  tile.height = NOISE;
  const t = tile.getContext('2d');
  if (!t) return null;
  const data = t.createImageData(NOISE, NOISE);
  for (let i = 0; i < data.data.length; i += 4) {
    const v = Math.floor(mathRng() * 255);
    data.data[i] = v;
    data.data[i + 1] = v;
    data.data[i + 2] = v;
    data.data[i + 3] = Math.floor(mathRng() * 22);
  }
  t.putImageData(data, 0, 0);
  return ctx.createPattern(tile, 'repeat');
}

function reducedMotion(): boolean {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function mountBackground(
  canvas: HTMLCanvasElement,
  look: WallLook,
  options: BackgroundOptions = {},
): BackgroundHandle {
  const maxWidth = options.maxWidth ?? 960;
  const context = canvas.getContext('2d', { alpha: false });
  if (!context) return { update: () => undefined, destroy: () => undefined };
  const ctx: CanvasRenderingContext2D = context;
  const grain = noiseTile(ctx);
  const limiter = createFpsLimiter(look.fps);
  let current = look;
  let scene: Scene | null = null;
  let w = 0;
  let h = 0;
  let frame = 0;
  let running = false;
  let sceneTime = 0;
  let lastNow: number | null = null;
  let destroyed = false;

  const speed = (): number => (current.calm || reducedMotion() ? 0.35 : 1);

  function build(): void {
    const cssW = canvas.clientWidth || window.innerWidth || 960;
    const cssH = canvas.clientHeight || window.innerHeight || 540;
    w = Math.max(1, Math.min(maxWidth, Math.round(cssW)));
    h = Math.max(1, Math.round((w * cssH) / cssW));
    canvas.width = w;
    canvas.height = h;
    const palette = {
      bg: hexToRgb(current.background),
      primary: hexToRgb(current.primary),
      secondary: hexToRgb(current.secondary),
    };
    // seeded per preset: the same look always gets the same composition
    scene = PRESET_SCENES[current.preset].create(
      w,
      h,
      palette,
      seededRng(0x5eed + current.preset.length),
      grain,
    );
    scene.draw(ctx, sceneTime);
  }

  function loop(now: number): void {
    frame = requestAnimationFrame(loop);
    if (!limiter.ready(now)) return;
    if (lastNow !== null) sceneTime += (Math.min(now - lastNow, 100) / 1000) * speed();
    lastNow = now;
    scene?.draw(ctx, sceneTime);
  }

  function start(): void {
    if (running || destroyed || document.hidden || !PRESET_SCENES[current.preset].animated) return;
    running = true;
    lastNow = null;
    frame = requestAnimationFrame(loop);
  }

  function stop(): void {
    running = false;
    cancelAnimationFrame(frame);
  }

  const onVisibility = (): void => {
    if (document.hidden) stop();
    else start();
  };
  let resizeTimer: ReturnType<typeof setTimeout> | undefined;
  const onResize = (): void => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(build, 150);
  };
  document.addEventListener('visibilitychange', onVisibility);
  window.addEventListener('resize', onResize);
  build();
  start();

  return {
    update(next) {
      const rebuild =
        next.preset !== current.preset ||
        next.primary !== current.primary ||
        next.secondary !== current.secondary ||
        next.background !== current.background;
      current = next;
      limiter.setFps(next.fps);
      if (rebuild) {
        stop();
        build();
      }
      start();
    },
    destroy() {
      destroyed = true;
      stop();
      clearTimeout(resizeTimer);
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('resize', onResize);
    },
  };
}
