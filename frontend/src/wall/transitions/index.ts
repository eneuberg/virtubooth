/**
 * Transition registry: one runner per contract id, and the choice per slide
 * (`random` = „Zufall“: weighted, never the same twice in a row; calm or reduced
 * motion → crossfade only; no WebGL → no shader transitions).
 */
import { TRANSITION_IDS, type ConcreteTransition, type WallTransition } from '../api/types';
import { pickWeighted, type Rng } from '../rng';
import { confetti } from './confetti';
import { crossfade, glitch, jelly, kenburns, polaroid, slot, spring, stamp } from './motion';
import { dither, pixelate } from './shader';
import type { Transition } from './types';

export type { Transition, TransitionArgs } from './types';

export const TRANSITIONS: Record<ConcreteTransition, Transition> = {
  crossfade,
  kenburns,
  spring,
  dither,
  pixelate,
  glitch,
  polaroid,
  slot,
  jelly,
  stamp,
  confetti,
};

/** „Zufall“ weights: the playful ones a bit more often. */
export const RANDOM_WEIGHTS: Record<ConcreteTransition, number> = {
  crossfade: 1,
  kenburns: 2,
  spring: 2,
  dither: 1.2,
  pixelate: 1.2,
  glitch: 1.2,
  polaroid: 2,
  slot: 1,
  jelly: 1.5,
  stamp: 1.5,
  confetti: 1,
};

const CONCRETE = TRANSITION_IDS.filter((id): id is ConcreteTransition => id !== 'random');

const NEEDS_WEBGL: ReadonlySet<ConcreteTransition> = new Set(['dither', 'pixelate']);

export interface PickOptions {
  calm: boolean;
  reducedMotion: boolean;
  webgl: boolean;
}

export function pickTransition(
  configured: WallTransition,
  previous: ConcreteTransition | null,
  rng: Rng,
  opts: PickOptions,
): ConcreteTransition {
  if (opts.calm || opts.reducedMotion) return 'crossfade';
  if (configured !== 'random') {
    return NEEDS_WEBGL.has(configured) && !opts.webgl ? 'crossfade' : configured;
  }
  const choices = CONCRETE.filter((id) => id !== previous && (opts.webgl || !NEEDS_WEBGL.has(id))).map(
    (id) => [id, RANDOM_WEIGHTS[id]] as const,
  );
  return pickWeighted(choices, rng) ?? 'crossfade';
}

export function prefersReducedMotion(): boolean {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}
