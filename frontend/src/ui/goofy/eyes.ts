/**
 * The googly eyes' physics, without the DOM: a pupil is a loose disc in its eye. It is
 * pulled towards where the eye looks by an underdamped spring (so it overshoots and
 * wobbles like the plastic ones), and gravity makes it sag a little. Two eyes get
 * slightly different springs, so they never move quite in step.
 */

export interface Vec {
  x: number;
  y: number;
}

export interface Pupil {
  pos: Vec;
  vel: Vec;
}

export interface Spring {
  /** stiffness (1/s²) */
  k: number;
  /** damping (1/s): well below 2·√k, so it rings */
  c: number;
}

/** the left and the right eye: never in step */
export const SPRINGS: readonly [Spring, Spring] = [
  { k: 210, c: 9 },
  { k: 160, c: 7.5 },
];

/** how far down a resting pupil sags, as a share of its free radius */
export const SAG = 0.18;

/**
 * Where a pupil wants to be (in units of its free radius, |v| ≤ 1) when the eye at
 * `eye` looks at `target`: towards it, all the way once the target is a few eye widths
 * away, plus a little gravity.
 */
export function aim(eye: Vec, target: Vec, eyeSize: number): Vec {
  const dx = target.x - eye.x;
  const dy = target.y - eye.y;
  const dist = Math.hypot(dx, dy);
  const reach = dist === 0 ? 0 : Math.min(1, dist / (eyeSize * 3));
  const x = dist === 0 ? 0 : (dx / dist) * reach;
  const y = (dist === 0 ? 0 : (dy / dist) * reach) + SAG;
  return clampUnit({ x, y });
}

export function clampUnit(v: Vec): Vec {
  const len = Math.hypot(v.x, v.y);
  return len <= 1 ? v : { x: v.x / len, y: v.y / len };
}

/** One integration step (semi-implicit Euler; `dt` in seconds, capped at 1/30 s). The
 * pupil stays inside its eye: at the rim it bounces back with half its speed. */
export function step(p: Pupil, goal: Vec, spring: Spring, dt: number): Pupil {
  const h = Math.min(dt, 1 / 30);
  const ax = spring.k * (goal.x - p.pos.x) - spring.c * p.vel.x;
  const ay = spring.k * (goal.y - p.pos.y) - spring.c * p.vel.y;
  let vel = { x: p.vel.x + ax * h, y: p.vel.y + ay * h };
  let pos = { x: p.pos.x + vel.x * h, y: p.pos.y + vel.y * h };
  const len = Math.hypot(pos.x, pos.y);
  if (len > 1) {
    // bonk: back onto the rim, the outward part of the speed reversed and halved
    const n = { x: pos.x / len, y: pos.y / len };
    pos = n;
    const out = vel.x * n.x + vel.y * n.y;
    if (out > 0) vel = { x: vel.x - 1.5 * out * n.x, y: vel.y - 1.5 * out * n.y };
  }
  return { pos, vel };
}

/** At rest: close to its goal and hardly moving (the loop can stop). */
export function settled(p: Pupil, goal: Vec): boolean {
  return (
    Math.abs(p.pos.x - goal.x) < 0.004 &&
    Math.abs(p.pos.y - goal.y) < 0.004 &&
    Math.abs(p.vel.x) < 0.02 &&
    Math.abs(p.vel.y) < 0.02
  );
}
