/**
 * The theme's token → CSS mapping. The expected derived values are what the server
 * computes (backend/tests/api/test_theme.py, services/theme.py): the preview of
 * unsaved colours must match what /api/theme.css will send.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  applyTheme,
  contrast,
  contrastProblems,
  inkOf,
  mix,
  NEON_NACHT,
  readableOn,
  themeVariables,
  type ThemeColors,
} from './theme';

const KLASSISCH: ThemeColors = {
  background: '#2b0f0c',
  surface: '#3b1712',
  depth: '#1c0806',
  primary: '#ffa630',
  secondary: '#fbefe9',
  tertiary: '#c9b8b0',
  accent: '#ff7a66',
  highlight: '#ffbb5c',
  hit: '#84d49b',
  text: '#fbefe9',
  text_muted: '#c9b8b0',
};

describe('theme maths (mirrors services/theme.py)', () => {
  it('contrast', () => {
    expect(contrast('#000000', '#ffffff')).toBeCloseTo(21);
    expect(contrast(NEON_NACHT.primary, NEON_NACHT.background)).toBeCloseTo(4.07, 2);
  });

  it('readableOn picks what the server picks', () => {
    expect(readableOn(NEON_NACHT.primary, NEON_NACHT)).toBe('#000000');
    expect(readableOn(NEON_NACHT.accent, NEON_NACHT)).toBe('#1b1b1a');
    expect(readableOn(KLASSISCH.primary, KLASSISCH)).toBe('#2b0f0c');
  });

  it('inkOf lightens electric violet just enough and leaves amber alone', () => {
    expect(inkOf(NEON_NACHT.primary, NEON_NACHT)).toBe('#cc4ffe');
    expect(inkOf(KLASSISCH.primary, KLASSISCH)).toBe('#ffa630');
    expect(mix('#000000', '#ffffff', 0.5)).toBe('#808080');
  });

  it('contrastProblems names the unreadable pairs', () => {
    expect(contrastProblems(NEON_NACHT)).toEqual([]);
    const bad = contrastProblems({ ...NEON_NACHT, text: '#4a4a4a' });
    expect(bad.map(([fg, bg]) => `${fg}/${bg}`)).toEqual(['text/background', 'text/surface']);
  });
});

describe('themeVariables', () => {
  it('maps every colour and the derived ones to --t-*', () => {
    const vars = themeVariables(KLASSISCH);
    expect(vars['--t-background']).toBe('#2b0f0c');
    expect(vars['--t-text-muted']).toBe('#c9b8b0');
    expect(vars['--t-on-primary']).toBe('#2b0f0c');
    expect(vars['--t-primary-ink']).toBe('#ffa630');
    expect(Object.keys(vars)).toHaveLength(14);
  });

  it('applyTheme sets them on <html> and the theme-color meta', () => {
    const meta = document.createElement('meta');
    meta.name = 'theme-color';
    document.head.append(meta);
    applyTheme(NEON_NACHT);
    const style = document.documentElement.style;
    expect(style.getPropertyValue('--t-primary')).toBe('#c026ff');
    expect(style.getPropertyValue('--t-on-primary')).toBe('#000000');
    expect(meta.getAttribute('content')).toBe('#1b1b1a');
    meta.remove();
  });

  it('app.css defaults are Neon Nacht (the page before /api/theme.css loads)', () => {
    const css = readFileSync('src/styles/app.css', 'utf8');
    for (const [name, value] of Object.entries(themeVariables(NEON_NACHT))) {
      expect(css).toContain(`${name}: ${value};`);
    }
  });
});
