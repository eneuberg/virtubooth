/**
 * The colour of an analysis frame: one per kind of thing, so the same thing has the
 * same colour on every tile (no legend needed: the frame's chip names it). The key is
 * the English label (the COCO class when it is one, so „Becher“ and „Tasse“ match);
 * faces and hands are just labels too („face“, „hand“). The most common things have
 * fixed, clearly distinct colours; every other label gets one of the rest by a stable
 * hash. The chip text is black or white, whichever reads better on the colour
 * (labelColors.test.ts). Applied through the CSSOM, so the CSP allows them.
 */

export interface LabelColor {
  /** the frame and its chip */
  color: string;
  /** the chip's text on `color` */
  text: '#000000' | '#ffffff';
}

/** the common things: fixed and clearly distinct */
export const FIXED_COLORS: Readonly<Record<string, string>> = {
  person: '#38bdf8', // sky
  face: '#ffa630', // orange
  hand: '#22c55e', // green
  bottle: '#ff4fa3', // pink
  cup: '#facc15', // yellow
  'wine glass': '#a855f7', // purple
  'cell phone': '#2563eb', // blue
  cake: '#dc2626', // red
};

/** everything else, by hash; none of them close to a fixed one */
export const HASHED_COLORS: readonly string[] = [
  '#2dd4bf', // teal
  '#a3e635', // lime
  '#818cf8', // indigo
  '#f0abfc', // light fuchsia
  '#b45309', // brown
  '#0e7490', // dark cyan
  '#ffffff', // white
  '#64748b', // slate
  '#7f1d1d', // maroon
  '#1e3a8a', // navy
  '#4d7c0f', // olive
  '#1f2937', // near black
];

/** the key of a label: lower case, single spaces („Wine_Glass“ = „wine glass“) */
export function labelKey(label: string): string {
  return label
    .trim()
    .toLowerCase()
    .replaceAll(/[\s_-]+/g, ' ');
}

/** FNV-1a, 32 bit: stable across browsers and sessions */
function hash(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

const channel = (v: number) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);

/** WCAG relative luminance of `#rrggbb` */
export function luminance(hex: string): number {
  const n = Number.parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => channel(v / 255));
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}

/** WCAG contrast ratio of two luminances */
export const contrast = (a: number, b: number) => (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);

/** black or white, whichever has more contrast on `hex` */
export function textOn(hex: string): LabelColor['text'] {
  const l = luminance(hex);
  return contrast(l, 0) >= contrast(l, 1) ? '#000000' : '#ffffff';
}

const cache = new Map<string, LabelColor>();

/** The frame colour of a label (an English key, or „face“/„hand“). */
export function labelColor(label: string): LabelColor {
  const key = labelKey(label);
  let out = cache.get(key);
  if (!out) {
    const color = FIXED_COLORS[key] ?? HASHED_COLORS[hash(key) % HASHED_COLORS.length]!;
    out = { color, text: textOn(color) };
    cache.set(key, out);
  }
  return out;
}
