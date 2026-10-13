import { describe, expect, it } from 'vitest';
import {
  germanDate,
  hasOverlay,
  isVessel,
  overlayInfo,
  pixelFontText,
  seeded,
  shadePath,
  vcrDate,
  VESSEL_SHAPES,
  vesselIconTransform,
} from './overlays';

describe('Beer Cam outlines', () => {
  it('are in photo space and fill most of the frame height', () => {
    const [, by, , bh] = VESSEL_SHAPES.bottle.box;
    const [, cy, , ch] = VESSEL_SHAPES.cup.box;
    expect(bh / 1440).toBeGreaterThan(0.8); // legacy e2e: bottle > 0.8 × frame height
    expect(ch / 1440).toBeGreaterThan(0.7); // cup > 0.7 ×, about the bottle's size
    expect(by + bh).toBeLessThanOrEqual(1440);
    expect(cy + ch).toBeLessThanOrEqual(1440);
  });

  it('are centred', () => {
    for (const shape of Object.values(VESSEL_SHAPES)) {
      const [x, , w] = shape.box;
      expect(x + w / 2).toBe(540);
    }
  });

  it('shade everything around the drink (even-odd)', () => {
    expect(shadePath('cup').startsWith('M0 0 H1080 V1440 H0 Z ')).toBe(true);
    expect(shadePath('cup')).toContain(VESSEL_SHAPES.cup.outline);
  });

  it('map into a 24 px icon with one scale for both', () => {
    expect(vesselIconTransform('bottle')).toMatch(/^translate\(\S+ \S+\) scale\(0\.01774\)$/);
    expect(vesselIconTransform('cup')).toMatch(/scale\(0\.01774\)$/);
  });

  it('knows its vessels', () => {
    expect(isVessel('bottle')).toBe(true);
    expect(isVessel('cup')).toBe(true);
    expect(isVessel('glass')).toBe(false);
    expect(isVessel(null)).toBe(false);
    expect(VESSEL_SHAPES.bottle.hint).toBe('Halte die Flasche in den Umriss.');
  });
});

describe('filter overlays', () => {
  it('belong to the frame filters only', () => {
    expect(['party', 'emoji', 'vhs', 'retro', 'comic'].every(hasOverlay)).toBe(true);
    expect(['normal', 'bw', 'sepia', 'colorpop', 'neon'].some(hasOverlay)).toBe(false);
  });

  it('are deterministic', () => {
    const a = seeded(7);
    const b = seeded(7);
    const first = [a(), a(), a()];
    expect([b(), b(), b()]).toEqual(first);
    expect(first.every((n) => n >= 0 && n < 1)).toBe(true);
  });

  it('write German dates', () => {
    const date = new Date(2026, 9, 3, 22, 41);
    expect(germanDate(date)).toBe('03.10.2026');
    expect(vcrDate(date)).toBe('OKT. 03 2026');
  });

  it('transliterate the party name for the pixel font', () => {
    expect(pixelFontText('Eriks Geburtstag')).toBe('ERIKS GEBURTSTAG');
    expect(pixelFontText('Ömers & Jürgens Gartenparty 🎉')).toBe('OEMERS & JUERGENS GARTENPARTY');
    expect(pixelFontText('Straße')).toBe('STRASSE');
    expect(pixelFontText('  🎉 ')).toBe('');
  });

  it('caption the party frame', () => {
    expect(overlayInfo('Eriks Geburtstag', new Date(0)).title).toBe('Eriks Geburtstag 🎉');
    expect(overlayInfo('  ').partyName).toBe('Party');
    expect(overlayInfo(null).partyName).toBe('Party');
  });
});
