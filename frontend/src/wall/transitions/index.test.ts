import { describe, expect, it } from 'vitest';
import { TRANSITION_IDS } from '../api/types';
import { seededRng } from '../rng';
import { pickTransition, TRANSITIONS } from './index';

const lively = { calm: false, reducedMotion: false, webgl: true };

describe('transition registry', () => {
  it('has a runner for every contract id (random picks one of them)', () => {
    expect([...Object.keys(TRANSITIONS), 'random'].toSorted()).toEqual([...TRANSITION_IDS].toSorted());
    for (const run of Object.values(TRANSITIONS)) expect(typeof run).toBe('function');
  });

  it('runs the configured transition', () => {
    expect(pickTransition('glitch', null, seededRng(1), lively)).toBe('glitch');
    expect(pickTransition('glitch', 'glitch', seededRng(1), lively)).toBe('glitch');
  });

  it('Zufall never picks the same transition twice in a row and uses many', () => {
    const rng = seededRng(42);
    let last = pickTransition('random', null, rng, lively);
    const seen = new Set([last]);
    for (let i = 0; i < 500; i++) {
      const next = pickTransition('random', last, rng, lively);
      expect(next).not.toBe(last);
      seen.add(next);
      last = next;
    }
    expect(seen.size).toBe(11);
    expect([...seen]).not.toContain('random');
  });

  it('reduced motion or a calm look → crossfade only', () => {
    const rng = seededRng(3);
    for (const id of TRANSITION_IDS) {
      expect(pickTransition(id, null, rng, { ...lively, reducedMotion: true })).toBe('crossfade');
      expect(pickTransition(id, null, rng, { ...lively, calm: true })).toBe('crossfade');
    }
  });

  it('without WebGL: no shader transitions', () => {
    const rng = seededRng(5);
    const noGl = { ...lively, webgl: false };
    expect(pickTransition('dither', null, rng, noGl)).toBe('crossfade');
    expect(pickTransition('pixelate', null, rng, noGl)).toBe('crossfade');
    for (let i = 0; i < 300; i++)
      expect(['dither', 'pixelate']).not.toContain(pickTransition('random', null, rng, noGl));
  });
});
