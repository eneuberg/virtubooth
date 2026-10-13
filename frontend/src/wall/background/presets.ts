/**
 * Background scenes for the 2D canvas (internal size ≤ 960×540). Each preset builds a
 * scene for a size and palette; `draw(t)` paints one frame at scene time t (seconds).
 */
import type { BackgroundPreset } from '../api/types';
import type { Rng } from '../rng';

export type Rgb = readonly [number, number, number];

export interface Palette {
  bg: Rgb;
  primary: Rgb;
  secondary: Rgb;
}

export interface Scene {
  draw(ctx: CanvasRenderingContext2D, t: number): void;
}

export interface Preset {
  /** false: drawn once, no animation loop */
  animated: boolean;
  create(w: number, h: number, palette: Palette, rng: Rng, grain: CanvasPattern | null): Scene;
}

const TAU = Math.PI * 2;

export function hexToRgb(hex: string): Rgb {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return [43, 43, 49];
  const n = parseInt(m[1]!, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function rgba(c: Rgb, a: number): string {
  return `rgba(${c[0]},${c[1]},${c[2]},${a.toFixed(3)})`;
}

export function mixRgb(a: Rgb, b: Rgb, t: number): Rgb {
  const at = (i: 0 | 1 | 2) => Math.round(a[i] + (b[i] - a[i]) * t);
  return [at(0), at(1), at(2)];
}

const WHITE: Rgb = [255, 255, 255];
const BLACK: Rgb = [0, 0, 0];

function fill(ctx: CanvasRenderingContext2D, c: Rgb, w: number, h: number): void {
  ctx.globalCompositeOperation = 'source-over';
  ctx.globalAlpha = 1;
  ctx.fillStyle = rgba(c, 1);
  ctx.fillRect(0, 0, w, h);
}

function glow(ctx: CanvasRenderingContext2D, x: number, y: number, r: number, c: Rgb, a: number): void {
  const g = ctx.createRadialGradient(x, y, 0, x, y, Math.max(1, r));
  g.addColorStop(0, rgba(c, a));
  g.addColorStop(0.55, rgba(c, a * 0.45));
  g.addColorStop(1, rgba(c, 0));
  ctx.fillStyle = g;
  ctx.fillRect(x - r, y - r, r * 2, r * 2);
}

function vignette(w: number, h: number): HTMLCanvasElement | null {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d');
  if (!ctx) return null;
  const g = ctx.createRadialGradient(
    w / 2,
    h / 2,
    Math.min(w, h) * 0.35,
    w / 2,
    h / 2,
    Math.hypot(w, h) * 0.6,
  );
  g.addColorStop(0, 'rgba(0,0,0,0)');
  g.addColorStop(1, 'rgba(0,0,0,0.5)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
  return c;
}

/** Film grain from the shared noise tile, moved every frame. */
function drawGrain(
  ctx: CanvasRenderingContext2D,
  grain: CanvasPattern | null,
  w: number,
  h: number,
  t: number,
) {
  if (!grain) return;
  const ox = Math.floor((Math.sin(t * 91.7) * 0.5 + 0.5) * 128);
  const oy = Math.floor((Math.cos(t * 73.3) * 0.5 + 0.5) * 128);
  ctx.globalCompositeOperation = 'source-over';
  ctx.globalAlpha = 1;
  ctx.save();
  ctx.translate(-ox, -oy);
  ctx.fillStyle = grain;
  ctx.fillRect(0, 0, w + 128, h + 128);
  ctx.restore();
}

/** Drifting gradient blobs, a few rising sparkles, grain, vignette. */
const blobs: Preset = {
  animated: true,
  create(w, h, pal, rng, grain) {
    const colors = [
      pal.primary,
      pal.secondary,
      mixRgb(pal.primary, pal.secondary, 0.5),
      pal.primary,
      pal.secondary,
      mixRgb(pal.primary, WHITE, 0.25),
    ];
    const items = colors.map((color) => ({
      color,
      ax: 0.28 + rng() * 0.2,
      ay: 0.26 + rng() * 0.16,
      sx: 0.12 + rng() * 0.14,
      sy: 0.1 + rng() * 0.14,
      sr: 0.25 + rng() * 0.3,
      px: rng() * TAU,
      py: rng() * TAU,
      pr: rng() * TAU,
      r: 0.38 + rng() * 0.22,
      a: 0.42 + rng() * 0.2,
    }));
    const sparks = Array.from({ length: 18 }, () => ({
      x: rng(),
      y: rng(),
      v: 0.012 + rng() * 0.025,
      r: 1 + rng() * 2.2,
      ph: rng() * TAU,
      c: rng() < 0.5 ? pal.primary : pal.secondary,
    }));
    const vig = vignette(w, h);
    const bg = mixRgb(pal.bg, BLACK, 0.12);
    return {
      draw(ctx, t) {
        fill(ctx, bg, w, h);
        ctx.globalCompositeOperation = 'screen';
        for (const b of items) {
          const x = w * (0.5 + b.ax * Math.sin(t * b.sx + b.px));
          const y = h * (0.5 + b.ay * Math.cos(t * b.sy + b.py));
          const r = h * b.r * (1 + 0.18 * Math.sin(t * b.sr + b.pr));
          glow(ctx, x, y, r, b.color, b.a);
        }
        ctx.globalCompositeOperation = 'lighter';
        for (const s of sparks) {
          const y = (((s.y - t * s.v) % 1) + 1) % 1;
          const x = s.x + Math.sin(t * 0.4 + s.ph) * 0.015;
          const a = 0.25 + 0.35 * (0.5 + 0.5 * Math.sin(t * 1.7 + s.ph));
          glow(ctx, x * w, y * h, s.r * (h / 270) * 3, s.c, a);
        }
        if (vig) {
          ctx.globalCompositeOperation = 'source-over';
          ctx.drawImage(vig, 0, 0);
        }
        drawGrain(ctx, grain, w, h, t);
      },
    };
  },
};

/** Slow ribbons of light across a darker sky, twinkling stars. */
const aurora: Preset = {
  animated: true,
  create(w, h, pal, rng, grain) {
    const colors = [pal.primary, pal.secondary, mixRgb(pal.primary, pal.secondary, 0.5), pal.primary];
    const ribbons = colors.map((color, i) => ({
      color,
      base: h * (0.22 + i * 0.16 + rng() * 0.05),
      amp: h * (0.06 + rng() * 0.06),
      k: (TAU / w) * (0.6 + rng() * 0.9),
      s: 0.25 + rng() * 0.3,
      ph: rng() * TAU,
      th: h * (0.07 + rng() * 0.05),
    }));
    const stars = Array.from({ length: 60 }, () => ({ x: rng() * w, y: rng() * h * 0.7, ph: rng() * TAU }));
    const vig = vignette(w, h);
    const bg = mixRgb(pal.bg, BLACK, 0.35);
    return {
      draw(ctx, t) {
        fill(ctx, bg, w, h);
        ctx.globalCompositeOperation = 'lighter';
        for (const s of stars) {
          ctx.globalAlpha = 0.15 + 0.35 * (0.5 + 0.5 * Math.sin(t * 2 + s.ph));
          ctx.fillStyle = '#ffffff';
          ctx.fillRect(s.x, s.y, 1.4, 1.4);
        }
        ctx.globalAlpha = 1;
        ctx.globalCompositeOperation = 'screen';
        for (const r of ribbons) {
          const at = (x: number) =>
            r.base +
            r.amp * Math.sin(x * r.k + t * r.s + r.ph) +
            r.amp * 0.5 * Math.sin(x * r.k * 2.3 - t * r.s * 1.4);
          const thick = (x: number) => r.th * (1 + 0.6 * Math.sin(x * r.k * 0.7 + t * 0.35 + r.ph));
          ctx.beginPath();
          for (let x = 0; x <= w + 16; x += 16) ctx.lineTo(x, at(x) - thick(x));
          for (let x = w + 16; x >= 0; x -= 16) ctx.lineTo(x, at(x) + thick(x) * 1.8);
          ctx.closePath();
          const g = ctx.createLinearGradient(0, r.base - r.amp * 2.5, 0, r.base + r.amp * 3);
          g.addColorStop(0, rgba(r.color, 0));
          g.addColorStop(0.45, rgba(r.color, 0.5));
          g.addColorStop(0.6, rgba(mixRgb(r.color, WHITE, 0.3), 0.35));
          g.addColorStop(1, rgba(r.color, 0));
          ctx.fillStyle = g;
          ctx.fill();
        }
        if (vig) {
          ctx.globalCompositeOperation = 'source-over';
          ctx.drawImage(vig, 0, 0);
        }
        drawGrain(ctx, grain, w, h, t);
      },
    };
  },
};

/** A retro perspective floor grid rolling towards the viewer, sweeping spots, sparkles. */
const disco: Preset = {
  animated: true,
  create(w, h, pal, rng) {
    const horizon = h * 0.56;
    const spots = [pal.primary, pal.secondary, mixRgb(pal.primary, WHITE, 0.6)].map((c) => ({
      c,
      s: 0.35 + rng() * 0.35,
      ph: rng() * TAU,
    }));
    const sparkles = Array.from({ length: 40 }, () => ({
      x: rng() * w,
      y: rng() * horizon * 0.9,
      ph: rng() * TAU,
    }));
    const bg = mixRgb(pal.bg, BLACK, 0.4);
    return {
      draw(ctx, t) {
        fill(ctx, bg, w, h);
        ctx.globalCompositeOperation = 'screen';
        glow(ctx, w / 2, horizon, h * 0.62, pal.secondary, 0.5);
        glow(ctx, w / 2, horizon, h * 0.25, mixRgb(pal.secondary, WHITE, 0.4), 0.35);
        // floor grid
        ctx.globalCompositeOperation = 'lighter';
        ctx.strokeStyle = rgba(pal.primary, 0.55);
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        for (let i = -14; i <= 14; i++) {
          ctx.moveTo(w / 2 + i * w * 0.018, horizon);
          ctx.lineTo(w / 2 + i * w * 0.2, h);
        }
        ctx.stroke();
        const phase = (t * 0.8) % 1;
        for (let k = 0; k < 16; k++) {
          const d = 1 + k - phase;
          const y = horizon + (h - horizon) / d;
          ctx.strokeStyle = rgba(pal.primary, Math.min(0.85, 1.1 / d));
          ctx.beginPath();
          ctx.moveTo(0, y);
          ctx.lineTo(w, y);
          ctx.stroke();
        }
        // spotlights: a beam from the ceiling to a moving pool of light on the floor
        ctx.globalCompositeOperation = 'screen';
        spots.forEach((s, i) => {
          const top = w * (0.2 + 0.3 * i);
          const fx = w * (0.5 + 0.42 * Math.sin(t * s.s + s.ph));
          const fy = horizon + (h - horizon) * (0.45 + 0.3 * Math.sin(t * s.s * 0.7 + s.ph));
          const beam = ctx.createLinearGradient(top, 0, fx, fy);
          beam.addColorStop(0, rgba(s.c, 0.38));
          beam.addColorStop(1, rgba(s.c, 0.04));
          ctx.fillStyle = beam;
          ctx.beginPath();
          ctx.moveTo(top - 6, -4);
          ctx.lineTo(top + 6, -4);
          ctx.lineTo(fx + h * 0.16, fy);
          ctx.lineTo(fx - h * 0.16, fy);
          ctx.closePath();
          ctx.fill();
          ctx.save();
          ctx.translate(fx, fy);
          ctx.scale(1, 0.32);
          glow(ctx, 0, 0, h * 0.2, s.c, 0.6);
          ctx.restore();
        });
        ctx.globalCompositeOperation = 'lighter';
        for (const s of sparkles) {
          const a = Math.max(0, Math.sin(t * 3 + s.ph));
          if (a < 0.6) continue;
          ctx.globalAlpha = (a - 0.6) * 2;
          ctx.fillStyle = '#ffffff';
          ctx.fillRect(s.x - 2, s.y - 0.5, 4, 1);
          ctx.fillRect(s.x - 0.5, s.y - 2, 1, 4);
        }
        ctx.globalAlpha = 1;
      },
    };
  },
};

/** Slowly falling, tumbling confetti over soft glows. */
const confetti: Preset = {
  animated: true,
  create(w, h, pal, rng) {
    const palette = [pal.primary, pal.secondary, WHITE, [255, 210, 63] as const, pal.primary];
    const pieces = Array.from({ length: 90 }, (_, i) => ({
      x: rng() * w,
      y: rng() * h,
      v: h * (0.04 + rng() * 0.07),
      sway: 10 + rng() * 30,
      ph: rng() * TAU,
      spin: 0.6 + rng() * 2.2,
      size: h * (0.008 + rng() * 0.012),
      c: palette[i % palette.length]!,
    }));
    const vig = vignette(w, h);
    return {
      draw(ctx, t) {
        fill(ctx, pal.bg, w, h);
        ctx.globalCompositeOperation = 'screen';
        glow(ctx, w * (0.2 + 0.05 * Math.sin(t * 0.2)), h * 0.15, h * 0.9, pal.primary, 0.35);
        glow(ctx, w * (0.8 + 0.05 * Math.cos(t * 0.17)), h * 0.9, h * 0.9, pal.secondary, 0.32);
        ctx.globalCompositeOperation = 'source-over';
        for (const p of pieces) {
          const y = (p.y + t * p.v) % (h + 20);
          const x = p.x + Math.sin(t * 0.8 + p.ph) * p.sway;
          const rot = t * p.spin + p.ph;
          ctx.save();
          ctx.translate(x, y - 10);
          ctx.rotate(rot);
          ctx.scale(1, Math.cos(rot * 1.3));
          ctx.globalAlpha = 0.85;
          ctx.fillStyle = rgba(p.c, 1);
          ctx.fillRect(-p.size, -p.size * 0.5, p.size * 2, p.size);
          ctx.restore();
        }
        ctx.globalAlpha = 1;
        if (vig) ctx.drawImage(vig, 0, 0);
      },
    };
  },
};

/** The background colour with two faint glows; painted once. */
const plain: Preset = {
  animated: false,
  create(w, h, pal) {
    const vig = vignette(w, h);
    return {
      draw(ctx) {
        fill(ctx, pal.bg, w, h);
        ctx.globalCompositeOperation = 'screen';
        glow(ctx, w * 0.15, h * 0.1, h * 0.9, pal.primary, 0.18);
        glow(ctx, w * 0.85, h * 0.95, h * 0.9, pal.secondary, 0.16);
        ctx.globalCompositeOperation = 'source-over';
        if (vig) ctx.drawImage(vig, 0, 0);
      },
    };
  },
};

export const PRESET_SCENES: Record<BackgroundPreset, Preset> = { blobs, aurora, disco, confetti, plain };
