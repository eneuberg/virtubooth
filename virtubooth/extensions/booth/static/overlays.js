// Drawing helpers for filter overlays (frames, stickers, HUDs).
// Overlays are drawn once into a transparent OUTPUT_W×OUTPUT_H 2D canvas and
// composited on top of the filtered video (never mirrored, so text stays readable).

export const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif';
export const EMOJI_FONT = '"Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji", sans-serif';
export const MONO_FONT = 'ui-monospace, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace';
export const PARTY_COLORS = ['#ff3d8b', '#ff8a00', '#ffd23f', '#2de2e6', '#7b2ff7', '#3ddc84', '#ffffff'];

/** Deterministic random numbers (same overlay every time). */
export function seeded(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function roundRectPath(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/**
 * Set the largest font size ≤ max at which `text` fits into maxWidth; below
 * `min` the text is shortened with "…". Returns the text to draw.
 */
export function fitFont(ctx, text, maxWidth, max, min, weight = 900, family = FONT) {
  let size = max;
  for (; size > min; size -= 2) {
    ctx.font = `${weight} ${size}px ${family}`;
    if (ctx.measureText(text).width <= maxWidth) return text;
  }
  ctx.font = `${weight} ${size}px ${family}`;
  let chars = [...text];
  while (chars.length > 1 && ctx.measureText(`${chars.join('')}…`).width > maxWidth) chars = chars.slice(0, -1);
  return ctx.measureText(text).width <= maxWidth ? text : `${chars.join('').trimEnd()}…`;
}

/** Text with a fat rounded outline (sticker look). */
export function outlinedText(ctx, text, x, y, { fill = '#fff', stroke = '#2b0a45', width = 12, shadow = 'rgba(0,0,0,0.35)' } = {}) {
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

/** An emoji sticker: rotated, with a soft drop shadow. */
export function sticker(ctx, emoji, x, y, size, degrees = 0) {
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

/** One confetti piece: a little strip, dot or star. */
export function confettiPiece(ctx, rnd, x, y, scale = 1) {
  const color = PARTY_COLORS[Math.floor(rnd() * PARTY_COLORS.length)];
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

export function star(ctx, x, y, r, points = 5, inner = 0.45) {
  ctx.beginPath();
  for (let i = 0; i < points * 2; i++) {
    const radius = i % 2 ? r * inner : r;
    const a = (i * Math.PI) / points - Math.PI / 2;
    ctx.lineTo(x + Math.cos(a) * radius, y + Math.sin(a) * radius);
  }
  ctx.closePath();
  ctx.fill();
}

const MONTHS = ['JAN', 'FEB', 'MÄR', 'APR', 'MAI', 'JUN', 'JUL', 'AUG', 'SEP', 'OKT', 'NOV', 'DEZ'];

export function germanDate(date) {
  const dd = String(date.getDate()).padStart(2, '0');
  const mm = String(date.getMonth() + 1).padStart(2, '0');
  return `${dd}.${mm}.${date.getFullYear()}`;
}

export function vcrDate(date) {
  return `${MONTHS[date.getMonth()]}. ${String(date.getDate()).padStart(2, '0')} ${date.getFullYear()}`;
}

// 5×7 pixel font (rows concatenated, '#' = pixel) for the Retro-Pixel HUD
const PIXEL_FONT = {
  A: '.###.#...##...#######...##...##...#', B: '####.#...##...#####.#...##...#####.',
  C: '.###.#...##....#....#....#...#.###.', D: '####.#...##...##...##...##...#####.',
  E: '######....#....####.#....#....#####', F: '######....#....####.#....#....#....',
  G: '.###.#...##....#.####...##...#.####', H: '#...##...##...#######...##...##...#',
  I: '.###...#....#....#....#....#...###.', J: '..###...#....#....#....#.#..#..##..',
  K: '#...##..#.#.#..##...#.#..#..#.#...#', L: '#....#....#....#....#....#....#####',
  M: '#...###.###.#.##.#.##...##...##...#', N: '#...##...###..##.#.##..###...##...#',
  O: '.###.#...##...##...##...##...#.###.', P: '####.#...##...#####.#....#....#....',
  Q: '.###.#...##...##...##.#.##..#..##.#', R: '####.#...##...#####.#.#..#..#.#...#',
  S: '.#####....#.....###.....#....#####.', T: '#####..#....#....#....#....#....#..',
  U: '#...##...##...##...##...##...#.###.', V: '#...##...##...##...##...#.#.#...#..',
  W: '#...##...##...##.#.##.#.##.#.#.#.#.', X: '#...##...#.#.#...#...#.#.#...##...#',
  Y: '#...##...#.#.#...#....#....#....#..', Z: '#####....#...#...#...#...#....#####',
  0: '.###.#...##..###.#.###..##...#.###.', 1: '..#...##....#....#....#....#...###.',
  2: '.###.#...#....#...#...#...#...#####', 3: '#####...#...#.....#.....##...#.###.',
  4: '...#...##..#.#.#..#.#####...#....#.', 5: '######....####.....#....##...#.###.',
  6: '..##..#...#....####.#...##...#.###.', 7: '#####....#...#...#...#....#....#...',
  8: '.###.#...##...#.###.#...##...#.###.', 9: '.###.#...##...#.####....#...#..##..',
  '!': '..#....#....#....#....#.........#..', '?': '.###.#...#....#...#...#.........#..',
  '-': '...............#####...............', '.': '..........................##...##..',
  ':': '......##...##.........##...##......', "'": '..#....#...#.......................',
  '&': '.##..#..#.#.#...#...#.#.##..#..##.#', '#': '.#.#..#.#.#####.#.#.#####.#.#..#.#.',
  '+': '.......#....#..#####..#....#.......', ' ': '...................................',
};
const TRANSLIT = { Ä: 'AE', Ö: 'OE', Ü: 'UE', ß: 'SS', É: 'E', È: 'E', À: 'A' };

export function pixelFontText(text) {
  return [...text.toUpperCase()].map((ch) => TRANSLIT[ch] ?? ch).join('')
    .split('').filter((ch) => PIXEL_FONT[ch]).join('').replace(/\s+/g, ' ').trim();
}

/** Width in px of pixelText() for `text` at `cell` px per font pixel. */
export function pixelTextWidth(text, cell) {
  const n = pixelFontText(text).length;
  return n ? (n * 6 - 1) * cell : 0;
}

/** Text in the 5×7 pixel font; `align` is relative to x. Returns the width. */
export function pixelText(ctx, text, x, y, cell, color, { align = 'left' } = {}) {
  const chars = pixelFontText(text);
  const width = pixelTextWidth(chars, cell);
  let left = align === 'right' ? x - width : align === 'center' ? x - width / 2 : x;
  left = Math.round(left);
  ctx.fillStyle = color;
  [...chars].forEach((ch, k) => {
    const glyph = PIXEL_FONT[ch];
    for (let i = 0; i < 35; i++) {
      if (glyph[i] === '#') ctx.fillRect(left + (k * 6 + (i % 5)) * cell, y + Math.floor(i / 5) * cell, cell, cell);
    }
  });
  return width;
}

/** Draw a bitmap ('#' = pixel) in cell-sized blocks. */
export function pixelSprite(ctx, rows, x, y, cell, color) {
  ctx.fillStyle = color;
  rows.forEach((row, j) => {
    for (let i = 0; i < row.length; i++) {
      if (row[i] === '#') ctx.fillRect(x + i * cell, y + j * cell, cell, cell);
    }
  });
}

export const HEART = [
  '.##.##.',
  '#######',
  '#######',
  '.#####.',
  '..###..',
  '...#...',
];
