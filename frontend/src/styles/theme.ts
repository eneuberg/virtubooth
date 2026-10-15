/**
 * The theme (Allgemeines → Erscheinungsbild): the guest UI's and the Live Wall's
 * colours as CSS custom properties `--t-<name>` on <html>.
 *
 * Before the first paint they come from `/api/theme.css`, which the server links in
 * every guest page's <head> (CSP-clean). This module sets the same properties through
 * the CSSOM: when the guest app comes back to the foreground (the host may have
 * changed the theme), for the wall's `config` event, and for the admin preview.
 * app.css maps `--t-*` onto the guest surface (`html[data-vb-theme]`); the admin
 * pages never carry that attribute and keep their own look.
 *
 * The derived colours mirror backend/src/virtubooth/services/theme.py exactly
 * (`readable_on`, `ink_of`, `css_variables`), so a preview of unsaved colours shows
 * what the server will send.
 */

export const THEME_COLOR_KEYS = [
  'background',
  'surface',
  'depth',
  'primary',
  'secondary',
  'tertiary',
  'accent',
  'highlight',
  'hit',
  'text',
  'text_muted',
] as const;

export type ThemeColorKey = (typeof THEME_COLOR_KEYS)[number];
export type ThemeColors = Record<ThemeColorKey, string>;

/** The layer on top of the colours: calm, „party“ (calm plus a few deliberate gags,
 * styles/party.css) or „goofy“ (Verspielt, the default: the fairground look,
 * styles/goofy.css). */
export type ThemeStyle = 'elegant' | 'party' | 'goofy';
export const THEME_STYLES: readonly ThemeStyle[] = ['elegant', 'party', 'goofy'];
/** what a theme without a (known) style gets, like the server (services/theme.py):
 * the default look is Neon Nacht in the goofy style */
export const DEFAULT_STYLE: ThemeStyle = 'goofy';

export function isThemeStyle(value: unknown): value is ThemeStyle {
  return typeof value === 'string' && (THEME_STYLES as readonly string[]).includes(value);
}

export interface PublicTheme {
  preset: 'neon_nacht' | 'klassisch' | 'rummel' | 'custom';
  colors: ThemeColors;
  style?: ThemeStyle;
  on_primary: string;
  on_accent: string;
  primary_ink: string;
  rev: number;
}

export const MIN_CONTRAST = 4.5;
export const HEX_RE = /^#[0-9a-f]{6}$/;

/** „Neon Nacht“, the default colours (services/theme.py NEON_NACHT; style goofy). */
export const NEON_NACHT: ThemeColors = {
  background: '#1b1b1a',
  surface: '#252229',
  depth: '#1a0733',
  primary: '#c026ff',
  secondary: '#eba6c6',
  tertiary: '#b6b6d8',
  accent: '#ff2fb0',
  highlight: '#cee4f7',
  hit: '#b6ff3c',
  text: '#fcf2f9',
  text_muted: '#bdb3c4',
};

function channel(c: number): number {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

function rgb(hex: string): [number, number, number] {
  const at = (i: number) => parseInt(hex.slice(i, i + 2), 16);
  return [at(1), at(3), at(5)];
}

/** WCAG relative luminance of `#rrggbb`. */
export function luminance(hex: string): number {
  const [r, g, b] = rgb(hex);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/** WCAG contrast ratio (1 … 21). */
export function contrast(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/** `a` moved `amount` (0…1) towards `b` in sRGB. */
export function mix(a: string, b: string, amount: number): string {
  const ca = rgb(a);
  const cb = rgb(b);
  return (
    '#' +
    ca
      .map((v, i) => Math.round(v * (1 - amount) + cb[i]! * amount))
      .map((v) => v.toString(16).padStart(2, '0'))
      .join('')
  );
}

/** Text colour for a fill: the first of background, depth, text, black, white with
 * 4.5:1, else the one with the most contrast. */
export function readableOn(fill: string, colors: ThemeColors): string {
  const candidates = [colors.background, colors.depth, colors.text, '#000000', '#ffffff'];
  const ok = candidates.find((c) => contrast(fill, c) >= MIN_CONTRAST);
  if (ok) return ok;
  return candidates.reduce((best, c) => (contrast(fill, c) > contrast(fill, best) ? c : best));
}

/** `color` as text on background and surface: itself when it reads, else moved
 * towards `text` in 5 % steps until it does. */
export function inkOf(color: string, colors: ThemeColors): string {
  for (let step = 0; step <= 20; step++) {
    const c = mix(color, colors.text, step / 20);
    if (contrast(c, colors.background) >= MIN_CONTRAST && contrast(c, colors.surface) >= MIN_CONTRAST) {
      return c;
    }
  }
  return colors.text;
}

/** The pairs the server checks (400 `invalid_theme`), as [fg, bg, ratio] below 4.5:1. */
export function contrastProblems(colors: ThemeColors): [ThemeColorKey, ThemeColorKey, number][] {
  const pairs: [ThemeColorKey, ThemeColorKey][] = [
    ['text', 'background'],
    ['text', 'surface'],
    ['text_muted', 'background'],
    ['text_muted', 'surface'],
  ];
  return pairs
    .filter(([fg, bg]) => HEX_RE.test(colors[fg]) && HEX_RE.test(colors[bg]))
    .map(([fg, bg]) => [fg, bg, contrast(colors[fg], colors[bg])] as [ThemeColorKey, ThemeColorKey, number])
    .filter(([, , ratio]) => ratio < MIN_CONTRAST);
}

/** The custom properties for a set of colours (derived ones included):
 * `{'--t-background': '#1b1b1a', …, '--t-on-primary': …}`. */
export function themeVariables(colors: ThemeColors): Record<string, string> {
  const derived = {
    on_primary: readableOn(colors.primary, colors),
    on_accent: readableOn(colors.accent, colors),
    primary_ink: inkOf(colors.primary, colors),
  };
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries({ ...colors, ...derived })) {
    out[`--t-${key.replace(/_/g, '-')}`] = value;
  }
  return out;
}

/** Set the theme on an element (default: <html>) through the CSSOM. */
export function applyTheme(colors: ThemeColors, el: HTMLElement = document.documentElement): void {
  for (const [name, value] of Object.entries(themeVariables(colors))) {
    el.style.setProperty(name, value);
  }
  if (el === document.documentElement) {
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', colors.background);
  }
}

/** The style on <html data-vb-style> (the server writes it into every guest page; this
 * keeps it current when the host switches while the page is open). */
export function applyStyle(style: ThemeStyle | undefined, el: HTMLElement = document.documentElement): void {
  el.setAttribute('data-vb-style', isThemeStyle(style) ? style : DEFAULT_STYLE);
}

function isTheme(value: unknown): value is PublicTheme {
  if (!value || typeof value !== 'object' || !('colors' in value)) return false;
  const { colors } = value;
  return (
    !!colors &&
    typeof colors === 'object' &&
    THEME_COLOR_KEYS.every((k) => {
      const c: unknown = Object.getOwnPropertyDescriptor(colors, k)?.value;
      return typeof c === 'string' && HEX_RE.test(c);
    })
  );
}

/** Re-read `/api/theme` (ETag: usually a 304) and apply it when it changed. */
export async function refreshTheme(): Promise<void> {
  try {
    const res = await fetch('/api/theme', { credentials: 'same-origin' });
    if (!res.ok) return;
    const theme: unknown = await res.json();
    if (isTheme(theme)) {
      applyTheme(theme.colors);
      applyStyle(theme.style);
    }
  } catch {
    // offline: the colours from the page load stay
  }
}

/** Guest pages: refresh the theme whenever the page becomes visible again. */
function onVisible(): void {
  if (document.visibilityState === 'visible') void refreshTheme();
}

export function followTheme(): () => void {
  document.addEventListener('visibilitychange', onVisible);
  return () => document.removeEventListener('visibilitychange', onVisible);
}
