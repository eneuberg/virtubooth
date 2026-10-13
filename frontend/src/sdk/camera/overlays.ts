/**
 * What is drawn on top of the camera picture. OWNER: wave 2 "AC".
 *
 * 1. Beer Cam outlines (port of beer/static/shapes.js): a German 0.5 l "Euroflasche"
 *    by default, or a 0.5 l party cup of about the same height. Paths are in photo
 *    space (1080×1440), so an SVG with viewBox 0 0 1080 1440 and
 *    preserveAspectRatio="none" over the 3:4 stage lines up 1:1 with the saved photo.
 *    The outline is a guide on screen only; it is never part of the photo.
 * 2. Fotobox filter overlays (port of booth/static/overlays.js + the overlay functions
 *    of filters.js): party frame, emoji props, VHS, retro HUD, comic burst. They are
 *    drawn once per filter selection into a transparent 1080×1440 canvas, composited
 *    over the filtered picture and saved with it, never mirrored (text stays readable).
 *    A seeded PRNG makes them identical every time. System fonts only (CSP font-src).
 */
import { PHOTO_H, PHOTO_W } from './capture';

// ------------------------------------------------------------ Beer Cam outlines

export type Vessel = 'bottle' | 'cup';

export interface VesselShape {
  label: string;
  /** the one hint line under the stage */
  hint: string;
  /** bounding box [x, y, w, h] in photo space (the toggle icon) */
  box: readonly [number, number, number, number];
  outline: string;
  details: string;
  shine: string;
}

export const VESSELS: readonly Vessel[] = ['bottle', 'cup'];

export const VESSEL_SHAPES: Record<Vessel, VesselShape> = {
  bottle: {
    label: 'Flasche',
    hint: 'Halte die Flasche in den Umriss.',
    box: [364, 100, 352, 1240],
    outline: [
      'M540 1340 H679 Q707 1340 707 1312 V640',
      'C707 506 608 470 608 362', // right shoulder
      'V168 C608 160 616 158 616 150 V112 Q616 100 604 100', // neck, lip, crown cap
      'H476 Q464 100 464 112 V150 C464 158 472 160 472 168',
      'V362 C472 470 373 506 373 640', // left shoulder
      'V1312 Q373 1340 401 1340 Z',
    ].join(' '),
    details: [
      'M464 138 H616', // crown cap rim
      'M373 820 Q540 852 707 820', // body label
      'M373 1150 Q540 1182 707 1150',
    ].join(' '),
    shine: 'M408 700 V1270',
  },
  cup: {
    label: 'Becher',
    hint: 'Halte den Becher in den Umriss.',
    box: [214, 220, 652, 1100],
    outline: [
      'M540 1320 H716 Q740 1320 742 1296', // bottom right corner
      'L834 266', // right wall
      'H846 Q866 266 866 246 Q866 226 846 226', // rolled rim, right end
      'H234 Q214 226 214 246 Q214 266 234 266', // rim, left end
      'H246 L338 1296 Q340 1320 364 1320 Z', // left wall
    ].join(' '),
    details: [
      'M256 372 q35.5 -32 71 0 t71 0 t71 0 t71 0 t71 0 t71 0 t71 0 t71 0', // foam line
      'M280 640 Q540 668 800 640', // the classic party-cup ridges
      'M308 960 Q540 986 772 960',
    ].join(' '),
    shine: 'M309 470 L376 1220',
  },
};

export function isVessel(value: unknown): value is Vessel {
  return value === 'bottle' || value === 'cup';
}

/** The even-odd shade path: the whole frame minus the silhouette (everything around the drink). */
export function shadePath(vessel: Vessel): string {
  return `M0 0 H${PHOTO_W} V${PHOTO_H} H0 Z ${VESSEL_SHAPES[vessel].outline}`;
}

/**
 * Maps the silhouette into a 24×24 icon box (lucide's grid): one scale for both
 * vessels so their sizes compare, bottom-aligned, centred.
 */
export function vesselIconTransform(vessel: Vessel): string {
  const [x, y, w, h] = VESSEL_SHAPES[vessel].box;
  const scale = 22 / VESSEL_SHAPES.bottle.box[3];
  const tx = 12 - (x + w / 2) * scale;
  const ty = 23 - (y + h) * scale;
  return `translate(${tx.toFixed(3)} ${ty.toFixed(3)}) scale(${scale.toFixed(5)})`;
}

// --------------------------------------------------------- drawing helpers

export interface OverlayInfo {
  partyName: string;
  /** the party frame's big caption */
  title: string;
  date: Date;
}

type Ctx = CanvasRenderingContext2D;

export const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif';
export const EMOJI_FONT = '"Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji", sans-serif';
export const MONO_FONT = 'ui-monospace, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace';
const PARTY_COLORS = ['#ff3d8b', '#ff8a00', '#ffd23f', '#2de2e6', '#7b2ff7', '#3ddc84', '#ffffff'];

/** Deterministic random numbers (mulberry32): the same overlay every time. */
export function seeded(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function roundRectPath(ctx: Ctx, x: number, y: number, w: number, h: number, r: number): void {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/** User-perceived characters (an emoji with skin tone stays whole when cutting). */
function graphemes(text: string): string[] {
  if (typeof Intl !== 'undefined' && 'Segmenter' in Intl) {
    return Array.from(new Intl.Segmenter('de', { granularity: 'grapheme' }).segment(text), (s) => s.segment);
  }
  return Array.from(text);
}

/**
 * Sets the largest font size ≤ max at which `text` fits into maxWidth; below `min`
 * the text is shortened with "…". Returns the text to draw.
 */
export function fitFont(
  ctx: Ctx,
  text: string,
  maxWidth: number,
  max: number,
  min: number,
  weight = 900,
  family = FONT,
): string {
  let size = max;
  for (; size > min; size -= 2) {
    ctx.font = `${weight} ${size}px ${family}`;
    if (ctx.measureText(text).width <= maxWidth) return text;
  }
  ctx.font = `${weight} ${size}px ${family}`;
  if (ctx.measureText(text).width <= maxWidth) return text;
  let chars = graphemes(text);
  while (chars.length > 1 && ctx.measureText(`${chars.join('')}…`).width > maxWidth)
    chars = chars.slice(0, -1);
  return `${chars.join('').trimEnd()}…`;
}

function outlinedText(
  ctx: Ctx,
  text: string,
  x: number,
  y: number,
  { fill = '#fff', stroke = '#2b0a45', width = 12, shadow = 'rgba(0,0,0,0.35)' } = {},
): void {
  ctx.save();
  ctx.lineJoin = 'round';
  ctx.miterLimit = 2;
  ctx.shadowColor = shadow;
  ctx.shadowOffsetY = width * 0.6;
  ctx.shadowBlur = width;
  ctx.lineWidth = width;
  ctx.strokeStyle = stroke;
  ctx.strokeText(text, x, y);
  ctx.shadowColor = 'transparent';
  ctx.fillStyle = fill;
  ctx.fillText(text, x, y);
  ctx.restore();
}

function sticker(ctx: Ctx, emoji: string, x: number, y: number, size: number, degrees = 0): void {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate((degrees * Math.PI) / 180);
  ctx.font = `${size}px ${EMOJI_FONT}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.shadowColor = 'rgba(0, 0, 0, 0.4)';
  ctx.shadowBlur = size * 0.12;
  ctx.shadowOffsetY = size * 0.06;
  ctx.fillText(emoji, 0, 0);
  ctx.restore();
}

function star(ctx: Ctx, x: number, y: number, r: number, points = 5, inner = 0.45): void {
  ctx.beginPath();
  for (let i = 0; i < points * 2; i++) {
    const radius = i % 2 ? r * inner : r;
    const a = (i * Math.PI) / points - Math.PI / 2;
    ctx.lineTo(x + Math.cos(a) * radius, y + Math.sin(a) * radius);
  }
  ctx.closePath();
  ctx.fill();
}

function confettiPiece(ctx: Ctx, rnd: () => number, x: number, y: number, scale = 1): void {
  const color = PARTY_COLORS[Math.floor(rnd() * PARTY_COLORS.length)] ?? '#ffffff';
  const kind = rnd();
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(rnd() * Math.PI);
  ctx.fillStyle = color;
  if (kind < 0.55) {
    const w = (10 + rnd() * 10) * scale;
    ctx.fillRect(-w / 2, -w * 1.2, w, w * 2.4);
  } else if (kind < 0.85) {
    ctx.beginPath();
    ctx.arc(0, 0, (6 + rnd() * 8) * scale, 0, Math.PI * 2);
    ctx.fill();
  } else {
    star(ctx, 0, 0, (14 + rnd() * 10) * scale);
  }
  ctx.restore();
}

const MONTHS = ['JAN', 'FEB', 'MÄR', 'APR', 'MAI', 'JUN', 'JUL', 'AUG', 'SEP', 'OKT', 'NOV', 'DEZ'];

/** "13.10.2026" */
export function germanDate(date: Date): string {
  const dd = String(date.getDate()).padStart(2, '0');
  const mm = String(date.getMonth() + 1).padStart(2, '0');
  return `${dd}.${mm}.${date.getFullYear()}`;
}

/** "OKT. 13 2026" (a VCR's date stamp) */
export function vcrDate(date: Date): string {
  return `${MONTHS[date.getMonth()] ?? ''}. ${String(date.getDate()).padStart(2, '0')} ${date.getFullYear()}`;
}

// 5×7 pixel font (rows concatenated, '#' = pixel) for the Retro-Pixel HUD
const PIXEL_FONT: Record<string, string> = {
  A: '.###.#...##...#######...##...##...#',
  B: '####.#...##...#####.#...##...#####.',
  C: '.###.#...##....#....#....#...#.###.',
  D: '####.#...##...##...##...##...#####.',
  E: '######....#....####.#....#....#####',
  F: '######....#....####.#....#....#....',
  G: '.###.#...##....#.####...##...#.####',
  H: '#...##...##...#######...##...##...#',
  I: '.###...#....#....#....#....#...###.',
  J: '..###...#....#....#....#.#..#..##..',
  K: '#...##..#.#.#..##...#.#..#..#.#...#',
  L: '#....#....#....#....#....#....#####',
  M: '#...###.###.#.##.#.##...##...##...#',
  N: '#...##...###..##.#.##..###...##...#',
  O: '.###.#...##...##...##...##...#.###.',
  P: '####.#...##...#####.#....#....#....',
  Q: '.###.#...##...##...##.#.##..#..##.#',
  R: '####.#...##...#####.#.#..#..#.#...#',
  S: '.#####....#.....###.....#....#####.',
  T: '#####..#....#....#....#....#....#..',
  U: '#...##...##...##...##...##...#.###.',
  V: '#...##...##...##...##...#.#.#...#..',
  W: '#...##...##...##.#.##.#.##.#.#.#.#.',
  X: '#...##...#.#.#...#...#.#.#...##...#',
  Y: '#...##...#.#.#...#....#....#....#..',
  Z: '#####....#...#...#...#...#....#####',
  '0': '.###.#...##..###.#.###..##...#.###.',
  '1': '..#...##....#....#....#....#...###.',
  '2': '.###.#...#....#...#...#...#...#####',
  '3': '#####...#...#.....#.....##...#.###.',
  '4': '...#...##..#.#.#..#.#####...#....#.',
  '5': '######....####.....#....##...#.###.',
  '6': '..##..#...#....####.#...##...#.###.',
  '7': '#####....#...#...#...#....#....#...',
  '8': '.###.#...##...#.###.#...##...#.###.',
  '9': '.###.#...##...#.####....#...#..##..',
  '!': '..#....#....#....#....#.........#..',
  '?': '.###.#...#....#...#...#.........#..',
  '-': '...............#####...............',
  '.': '..........................##...##..',
  ':': '......##...##.........##...##......',
  "'": '..#....#...#.......................',
  '&': '.##..#..#.#.#...#...#.#.##..#..##.#',
  '#': '.#.#..#.#.#####.#.#.#####.#.#..#.#.',
  '+': '.......#....#..#####..#....#.......',
  ' ': '...................................',
};
const TRANSLIT: Record<string, string> = { Ä: 'AE', Ö: 'OE', Ü: 'UE', ß: 'SS', É: 'E', È: 'E', À: 'A' };

/** Upper case, umlauts transliterated, unknown characters dropped, spaces collapsed. */
export function pixelFontText(text: string): string {
  return text
    .toUpperCase()
    .split('')
    .map((ch) => TRANSLIT[ch] ?? ch)
    .join('')
    .split('')
    .filter((ch) => PIXEL_FONT[ch] !== undefined)
    .join('')
    .replace(/\s+/g, ' ')
    .trim();
}

function pixelText(
  ctx: Ctx,
  text: string,
  x: number,
  y: number,
  cell: number,
  color: string,
  align: 'left' | 'right' | 'center' = 'left',
): number {
  const chars = pixelFontText(text);
  const width = chars.length ? (chars.length * 6 - 1) * cell : 0;
  let left = align === 'right' ? x - width : align === 'center' ? x - width / 2 : x;
  left = Math.round(left);
  ctx.fillStyle = color;
  chars.split('').forEach((ch, k) => {
    const glyph = PIXEL_FONT[ch] ?? '';
    for (let i = 0; i < 35; i++) {
      if (glyph[i] === '#') {
        ctx.fillRect(left + (k * 6 + (i % 5)) * cell, y + Math.floor(i / 5) * cell, cell, cell);
      }
    }
  });
  return width;
}

const HEART = ['.##.##.', '#######', '#######', '.#####.', '..###..', '...#...'];

function pixelSprite(ctx: Ctx, rows: string[], x: number, y: number, cell: number, color: string): void {
  ctx.fillStyle = color;
  rows.forEach((row, j) => {
    for (let i = 0; i < row.length; i++) {
      if (row[i] === '#') ctx.fillRect(x + i * cell, y + j * cell, cell, cell);
    }
  });
}

// ---------------------------------------------------------- filter overlays

function partyFrame(ctx: Ctx, w: number, h: number, info: OverlayInfo): void {
  const side = 52;
  const top = 52;
  const bottom = 236;
  const radius = 44;
  const g = ctx.createLinearGradient(0, 0, w, h);
  g.addColorStop(0, '#ff3d8b');
  g.addColorStop(0.55, '#ff8a00');
  g.addColorStop(1, '#ffd23f');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);

  // confetti sprinkled over the frame
  const rnd = seeded(7);
  for (let n = 0; n < 420; n++) {
    const x = rnd() * w;
    const y = rnd() * h;
    if (x > side - 6 && x < w - side + 6 && y > top - 6 && y < h - bottom + 6) continue;
    ctx.globalAlpha = 0.55 + rnd() * 0.45;
    confettiPiece(ctx, rnd, x, y, 0.8);
  }
  ctx.globalAlpha = 1;

  // the photo window
  ctx.globalCompositeOperation = 'destination-out';
  roundRectPath(ctx, side, top, w - side * 2, h - top - bottom, radius);
  ctx.fill();
  ctx.globalCompositeOperation = 'source-over';
  ctx.lineWidth = 10;
  ctx.strokeStyle = '#ffffff';
  ctx.stroke();

  // caption
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  const cx = w / 2;
  const band = h - bottom;
  const title = fitFont(ctx, info.title, w - side * 2 - 40, 112, 48);
  outlinedText(ctx, title, cx, band + bottom * 0.42, { stroke: '#4a0d6b', width: 16 });
  ctx.font = `800 40px ${FONT}`;
  ctx.fillStyle = 'rgba(43, 10, 69, 0.85)';
  ctx.fillText(`${germanDate(info.date)}  ·  📸 Fotobox`, cx, band + bottom * 0.8);
}

function emojiProps(ctx: Ctx, w: number, h: number): void {
  const rnd = seeded(42);
  // confetti border: dense at the edges, thinning out towards the middle
  for (let n = 0; n < 300; n++) {
    const edge = Math.floor(rnd() * 4);
    const along = rnd();
    const depth = Math.pow(rnd(), 2.8) * 170;
    const x = edge === 0 ? depth : edge === 1 ? w - depth : along * w;
    const y = edge === 2 ? depth : edge === 3 ? h - depth : along * h;
    ctx.globalAlpha = 0.75 + rnd() * 0.25;
    confettiPiece(ctx, rnd, x, y, 1.1);
  }
  ctx.globalAlpha = 1;
  // stickers around the face, never on it
  const stickers: Array<[string, number, number, number, number]> = [
    ['🥳', 0.15, 0.09, 190, -14],
    ['🎉', 0.86, 0.1, 170, 16],
    ['🎈', 0.08, 0.36, 140, -10],
    ['✨', 0.93, 0.34, 120, 12],
    ['🍾', 0.1, 0.66, 140, -24],
    ['💃', 0.91, 0.64, 140, 8],
    ['🎊', 0.15, 0.91, 170, 12],
    ['😎', 0.5, 0.94, 150, 0],
    ['🍹', 0.85, 0.9, 170, -10],
  ];
  for (const [emoji, x, y, size, deg] of stickers) sticker(ctx, emoji, x * w, y * h, size, deg);
}

function vhsOverlay(ctx: Ctx, w: number, h: number, info: OverlayInfo): void {
  const pad = 72;
  ctx.textBaseline = 'alphabetic';
  const vcr = (text: string, x: number, y: number, align: CanvasTextAlign = 'left') => {
    ctx.textAlign = align;
    ctx.fillStyle = 'rgba(255, 0, 90, 0.55)';
    ctx.fillText(text, x - 3, y);
    ctx.fillStyle = 'rgba(0, 220, 255, 0.55)';
    ctx.fillText(text, x + 3, y);
    ctx.fillStyle = 'rgba(255, 255, 255, 0.92)';
    ctx.fillText(text, x, y);
  };
  ctx.save();
  ctx.shadowColor = 'rgba(0, 0, 0, 0.5)';
  ctx.shadowBlur = 8;
  ctx.font = `700 58px ${MONO_FONT}`;
  // ● REC
  ctx.fillStyle = '#ff2a2a';
  ctx.beginPath();
  ctx.arc(pad + 22, pad + 34, 22, 0, Math.PI * 2);
  ctx.fill();
  vcr('REC', pad + 62, pad + 54);
  // battery
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.92)';
  ctx.lineWidth = 6;
  ctx.strokeRect(w - pad - 104, pad + 10, 92, 46);
  ctx.fillStyle = 'rgba(255, 255, 255, 0.92)';
  ctx.fillRect(w - pad - 12, pad + 22, 10, 22);
  for (let i = 0; i < 3; i++) ctx.fillRect(w - pad - 96 + i * 28, pad + 18, 22, 30);
  // date + tape speed
  ctx.font = `700 52px ${MONO_FONT}`;
  vcr(vcrDate(info.date), pad, h - pad);
  vcr('SP', w - pad, h - pad, 'right');
  ctx.font = `700 40px ${MONO_FONT}`;
  vcr('▶ PLAY', pad, h - pad - 72);
  ctx.restore();
}

function retroHud(ctx: Ctx, w: number, h: number, info: OverlayInfo): void {
  const c = 10; // px per font pixel
  const hud = (text: string, x: number, y: number, align: 'left' | 'right', color = '#fff1e8') => {
    pixelText(ctx, text, x + c, y + c, c, '#1d2b53', align); // drop shadow
    pixelText(ctx, text, x, y, c, color, align);
  };
  hud('1UP', 50, 50, 'left', '#ff004d');
  for (let i = 0; i < 3; i++) {
    pixelSprite(ctx, HEART, 50 + i * 90 + c, 140 + c, c, '#1d2b53');
    pixelSprite(ctx, HEART, 50 + i * 90, 140, c, '#ff004d');
  }
  hud('HI-SCORE', w - 50, 50, 'right', '#ffa300');
  hud('999999', w - 50, 140, 'right');
  let name = pixelFontText(info.partyName) || 'PARTY';
  if (name.length > 26) {
    // 26 characters fit at 6 px per font pixel; cut at a word if possible
    const space = name.slice(0, 27).lastIndexOf(' ');
    name = space > 0 ? name.slice(0, space) : name.slice(0, 26);
  }
  const cell = Math.max(6, Math.min(14, Math.floor((w - 100) / (name.length * 6))));
  pixelText(ctx, name, w / 2 + cell, h - 60 - cell * 7 + cell, cell, '#1d2b53', 'center');
  pixelText(ctx, name, w / 2, h - 60 - cell * 7, cell, '#ffec27', 'center');
}

function comicOverlay(ctx: Ctx, w: number): void {
  // a "WOW!" burst in the top right corner
  ctx.save();
  ctx.translate(w - 190, 190);
  ctx.rotate(0.18);
  ctx.fillStyle = '#1a0526';
  star(ctx, 6, 10, 170, 12, 0.68);
  ctx.fillStyle = '#ffd23f';
  star(ctx, 0, 0, 160, 12, 0.68);
  ctx.fillStyle = '#ff3d8b';
  star(ctx, 0, 0, 112, 12, 0.72);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.font = `italic 900 74px ${FONT}`;
  outlinedText(ctx, 'WOW!', 0, 4, { fill: '#ffffff', stroke: '#1a0526', width: 12, shadow: 'transparent' });
  ctx.restore();
}

type OverlayDraw = (ctx: Ctx, w: number, h: number, info: OverlayInfo) => void;

const FILTER_OVERLAYS: Record<string, OverlayDraw> = {
  party: partyFrame,
  emoji: emojiProps,
  vhs: vhsOverlay,
  retro: retroHud,
  comic: comicOverlay,
};

/** Whether a filter draws an overlay. */
export function hasOverlay(filterId: string): boolean {
  return filterId in FILTER_OVERLAYS;
}

/**
 * Draws the overlay of `filterId` into `canvas` (cleared first; 3:4, normally
 * 1080×1440) and returns the canvas, or null when the filter has none. One canvas is reused:
 * iOS Safari caps the total canvas memory.
 */
export function drawOverlay(
  canvas: HTMLCanvasElement,
  filterId: string,
  info: OverlayInfo,
): HTMLCanvasElement | null {
  const draw = FILTER_OVERLAYS[filterId];
  if (!draw) return null;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = 'source-over';
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.save();
  // always drawn in photo coordinates; a smaller canvas (swatches) scales them down
  const scale = canvas.width / PHOTO_W;
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  draw(ctx, PHOTO_W, PHOTO_H, info);
  ctx.restore();
  return canvas;
}

/** The party name as the overlays show it: "<party> 🎉" on the frame. */
export function overlayInfo(partyName: string | null | undefined, date: Date = new Date()): OverlayInfo {
  const name = partyName?.trim() || 'Party';
  return { partyName: name, title: `${name} 🎉`, date };
}
