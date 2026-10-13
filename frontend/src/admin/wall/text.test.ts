import { describe, expect, it } from 'vitest';
import { boxStyle, countsText, factValue, openWallsText, passwordText } from './text';

describe('text', () => {
  it('counts open walls', () => {
    expect(openWallsText(0)).toBe('0 Wände offen');
    expect(openWallsText(1)).toBe('1 Wand offen');
    expect(openWallsText(3)).toBe('3 Wände offen');
  });

  it('says the password state', () => {
    expect(passwordText({ set: false, changed_at: null })).toBe(
      'Noch kein Passwort: die Live-Wall ist gesperrt.',
    );
    expect(passwordText({ set: true, changed_at: '2026-10-13T18:41:00Z' })).toMatch(
      /^Passwort gesetzt am .+\.$/,
    );
  });

  it('sums up the analysis', () => {
    expect(countsText({ pending: 2, running: 1, done: 12, failed: 1, skipped: 0, total: 16 })).toBe(
      '12 fertig · 3 warten · 1 fehlgeschlagen',
    );
  });

  it('turns a box into % geometry, clipped to the photo', () => {
    expect(boxStyle({ x: 0.1, y: 0.2, w: 0.25, h: 0.3 })).toEqual({
      left: '10.00%',
      top: '20.00%',
      width: '25.00%',
      height: '30.00%',
    });
    expect(boxStyle({ x: 0.9, y: -0.1, w: 0.5, h: 0.5 })).toEqual({
      left: '90.00%',
      top: '0.00%',
      width: '10.00%',
      height: '40.00%',
    });
  });

  it('shows raw facts', () => {
    expect(factValue(3)).toBe('3');
    expect(factValue(0.41234)).toBe('0.412');
  });
});
