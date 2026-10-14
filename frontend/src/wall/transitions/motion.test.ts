import { describe, expect, it } from 'vitest';
import { seededRng } from '../rng';
import { bandClip, glitchSlices, outsideClip } from './motion';

describe('glitch slices', () => {
  it('three channels, bands inside the picture, the last step settled', () => {
    const channels = glitchSlices(seededRng(7), 9);
    expect(channels).toHaveLength(3);
    for (const slices of channels) {
      expect(slices).toHaveLength(10);
      for (const s of slices) {
        expect(s.top).toBeGreaterThanOrEqual(0);
        expect(s.bottom).toBeGreaterThanOrEqual(0);
        expect(s.top + s.bottom).toBeLessThan(100);
      }
      expect(slices.at(-1)).toEqual({ top: 0, bottom: 0, x: 0, y: 0 });
      // the new photo takes over: later bands are taller than the first one
      const height = (i: number) => 100 - slices[i]!.top - slices[i]!.bottom;
      expect(height(8)).toBeGreaterThan(height(0));
    }
  });

  it('the old photo fills exactly what the band leaves out', () => {
    const s = { top: 20, bottom: 30, x: 0, y: 0 };
    expect(bandClip(s)).toBe('inset(20% 0 30% 0)');
    expect(outsideClip(s)).toBe('polygon(0 0, 100% 0, 100% 20%, 0 20%, 0 70%, 100% 70%, 100% 100%, 0 100%)');
    // settled: the band is everything, the outside collapses to nothing
    expect(outsideClip({ top: 0, bottom: 0, x: 0, y: 0 })).toContain('100% 0%, 0 0%, 0 100%');
  });
});
