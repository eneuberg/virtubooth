// @vitest-environment node
/**
 * WCAG contrast of the palette pairs the components actually use (DESIGN.md has the table).
 * Reads the hex values from app.css, so a token change that breaks contrast fails here.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const css = readFileSync(new URL('./app.css', import.meta.url), 'utf8');

function token(name: string): string {
  const m = new RegExp(`--color-${name}:\\s*(#[0-9a-f]{3,6})`, 'i').exec(css);
  if (!m?.[1]) throw new Error(`no hex token --color-${name}`);
  return m[1];
}

function luminance(hex: string): number {
  const full = hex.length === 4 ? hex.replace(/^#(.)(.)(.)$/, '#$1$1$2$2$3$3') : hex;
  const channel = (i: number) => {
    const c = parseInt(full.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

function contrast(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

// [foreground, background, minimum]: 4.5 for text, 3 for large text / UI parts
const PAIRS: Array<[string, string, number]> = [
  // Rotlicht (dark)
  ['papier', 'rot-900', 4.5],
  ['papier', 'rot-800', 4.5],
  ['papier', 'rot-950', 4.5],
  ['papier-muted', 'rot-900', 4.5],
  ['papier-muted', 'rot-800', 4.5],
  ['papier-muted', 'kamera', 4.5],
  ['safelight', 'rot-900', 4.5],
  ['safelight', 'kamera', 4.5],
  ['rot-900', 'safelight', 4.5],
  ['fettstift-hell', 'rot-900', 4.5],
  ['fettstift-hell', 'rot-800', 4.5],
  ['white', 'fettstift', 4.5],
  ['gruen-hell', 'rot-900', 4.5],
  ['gruen-hell', 'kamera', 4.5],
  ['rot-900', 'papier', 4.5],
  ['fettstift-tief', 'papier', 4.5],
  // Leuchttisch (light)
  ['negativ', 'leuchttisch', 4.5],
  ['negativ', 'leuchttisch-weiss', 4.5],
  ['negativ', 'leuchttisch-sunk', 4.5],
  ['negativ-muted', 'leuchttisch', 4.5],
  ['negativ-muted', 'leuchttisch-weiss', 4.5],
  ['negativ-muted', 'leuchttisch-sunk', 4.5],
  ['fettstift', 'leuchttisch', 4.5],
  ['fettstift', 'leuchttisch-weiss', 4.5],
  ['negativ', 'safelight', 4.5],
  ['bernstein', 'leuchttisch', 4.5],
  ['bernstein', 'leuchttisch-weiss', 4.5],
  ['gruen', 'leuchttisch', 4.5],
  ['leuchttisch', 'negativ', 4.5],
  ['safelight', 'negativ', 4.5],
  ['bernstein-hell', 'negativ', 4.5],
  // UI boundaries (3:1): input borders, focus rings
  ['negativ-field', 'leuchttisch-weiss', 3],
  ['safelight', 'rot-800', 3],
  ['negativ', 'leuchttisch-hover', 3],
];

describe('palette contrast (WCAG 2.2 AA)', () => {
  it.each(PAIRS)('%s on %s ≥ %d:1', (fg, bg, min) => {
    expect(contrast(token(fg), token(bg))).toBeGreaterThanOrEqual(min);
  });
});
