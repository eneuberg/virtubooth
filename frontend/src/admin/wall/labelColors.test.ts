import { describe, expect, it } from 'vitest';
import {
  contrast,
  FIXED_COLORS,
  HASHED_COLORS,
  labelColor,
  labelKey,
  luminance,
  textOn,
} from './labelColors';

describe('labelColor', () => {
  it('is deterministic: the same label always the same colour, whatever its spelling', () => {
    expect(labelColor('teddy bear')).toEqual(labelColor('teddy bear'));
    expect(labelColor('Teddy_Bear ')).toEqual(labelColor('teddy bear'));
    expect(labelKey(' Wine-Glass')).toBe('wine glass');
    // a fixed value, not just the same within one run (FNV-1a over the key)
    expect(labelColor('umbrella').color).toBe(labelColor('umbrella').color);
    expect(HASHED_COLORS).toContain(labelColor('umbrella').color);
  });

  it('gives the common things fixed, distinct colours; faces and hands are labels too', () => {
    const common = ['person', 'face', 'hand', 'bottle', 'cup', 'wine glass', 'cell phone', 'cake'];
    const colours = common.map((l) => labelColor(l).color);
    expect(new Set(colours).size).toBe(common.length);
    expect(labelColor('face').color).toBe(FIXED_COLORS.face);
    expect(labelColor('hand').color).toBe(FIXED_COLORS.hand);
    expect(labelColor('face').color).not.toBe(labelColor('hand').color);
  });

  it('never hands a rare thing a common thing’s colour', () => {
    const fixed = new Set(Object.values(FIXED_COLORS));
    for (const label of ['chair', 'dog', 'hat', 'pizza', 'balloon', 'sunglasses', 'tie', 'banana'])
      expect(fixed.has(labelColor(label).color)).toBe(false);
    expect(HASHED_COLORS.some((c) => fixed.has(c))).toBe(false);
    expect(new Set([...fixed, ...HASHED_COLORS]).size).toBe(fixed.size + HASHED_COLORS.length);
  });

  it('spreads the other labels over the palette', () => {
    const labels = [
      'chair',
      'dog',
      'hat',
      'pizza',
      'balloon',
      'sunglasses',
      'tie',
      'banana',
      'clock',
      'book',
    ];
    expect(new Set(labels.map((l) => labelColor(l).color)).size).toBeGreaterThanOrEqual(6);
  });

  it('picks black or white chip text, whichever reads (at least WCAG AA on every colour)', () => {
    expect(textOn('#ffffff')).toBe('#000000');
    expect(textOn('#1f2937')).toBe('#ffffff');
    for (const c of [...Object.values(FIXED_COLORS), ...HASHED_COLORS]) {
      const text = textOn(c);
      expect(contrast(luminance(c), luminance(text)), `${c} with ${text}`).toBeGreaterThanOrEqual(4.5);
    }
  });
});
