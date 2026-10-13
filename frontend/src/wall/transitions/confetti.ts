/**
 * Confetti: two party poppers burst from the bottom corners (canvas), then a crossfade.
 * The canvas keeps falling after the transition is done and removes itself.
 */
import { crossfade } from './motion';
import type { Transition } from './types';

interface Piece {
  x: number;
  y: number;
  vx: number;
  vy: number;
  rot: number;
  spin: number;
  w: number;
  h: number;
  color: string;
}

const MAX_W = 960;

export const confetti: Transition = (args) => {
  const { stage, ms, signal, colors, rng } = args;
  const canvas = document.createElement('canvas');
  canvas.className = 'wall-confetti';
  const rect = stage.getBoundingClientRect();
  const w = Math.max(1, Math.min(MAX_W, Math.round(rect.width)));
  const h = Math.max(1, Math.round((w * rect.height) / Math.max(1, rect.width)));
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  if (ctx) {
    stage.append(canvas);
    const palette = [colors.primary, colors.secondary, '#ffffff', '#ffd23f', colors.primary];
    const pieces: Piece[] = [];
    for (let i = 0; i < 180; i++) {
      const left = i % 2 === 0;
      const spread = 0.12 + rng() * 0.55;
      const angle = -Math.PI / 2 + (left ? spread : -spread);
      const speed = h * (1.3 + rng() * 1.1);
      pieces.push({
        x: left ? w * 0.04 : w * 0.96,
        y: h * 1.02,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        rot: rng() * Math.PI,
        spin: (rng() - 0.5) * 14,
        w: h * (0.012 + rng() * 0.012),
        h: h * (0.006 + rng() * 0.01),
        color: palette[i % palette.length]!,
      });
    }
    const gravity = h * 1.25;
    const life = Math.max(ms, 2600);
    let last = performance.now();
    const start = last;
    let frame = 0;
    const tick = (now: number): void => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      ctx.clearRect(0, 0, w, h);
      for (const p of pieces) {
        p.vy += gravity * dt;
        const drag = Math.pow(0.4, dt);
        p.vx *= drag;
        p.vy *= drag;
        p.x += p.vx * dt;
        p.y += p.vy * dt;
        p.rot += p.spin * dt;
        ctx.save();
        ctx.translate(p.x, p.y);
        ctx.rotate(p.rot);
        ctx.scale(1, Math.cos(p.rot * 1.7));
        ctx.fillStyle = p.color;
        ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
        ctx.restore();
      }
      if (now - start < life && !signal.aborted) frame = requestAnimationFrame(tick);
      else canvas.remove();
    };
    frame = requestAnimationFrame(tick);
    signal.addEventListener(
      'abort',
      () => {
        cancelAnimationFrame(frame);
        canvas.remove();
      },
      { once: true },
    );
  }
  return crossfade({ ...args, ms: Math.max(ms, 800) });
};
