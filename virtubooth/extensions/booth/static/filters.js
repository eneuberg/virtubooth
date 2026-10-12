// Fotobox filter registry. Adding a filter:
//
//   1. add `{ "id", "name", "icon" }` to filters.json (the catalogue: the
//      server only accepts ids listed there; the order there is the strip order)
//   2. add one object with the same id to FILTERS below:
//
//   {
//     id: 'sepia',
//     // WebGL1 / GLSL ES 1.0 snippet defining `vec3 effect(vec2 uv)`.
//     // uv = output position, (0,0) top left. Helpers from renderer.js PRELUDE:
//     // video(uv), luma(c), saturation(c, s), contrast(c, k), scurve(x, k),
//     // vignette(uv, amount), hash(p), rgb2hsv(c), hsv2rgb(c), OUT (1080×1440),
//     // u_time (s), u_px (one camera pixel in uv units).
//     glsl: `vec3 effect(vec2 uv) { ... }`,
//     uniforms: { u_amount: 0.5 },          // optional: number | [2..4] | vec3 array
//     overlay(ctx, w, h, info) { ... },     // optional: draw frame/stickers once on a
//                                           // transparent w×h canvas; info = {partyName, title, date}
//     cpu(ctx, w, h) { ... },               // optional: Canvas2D fallback (no WebGL). Filters
//                                           // without it are hidden when WebGL is missing.
//   }
//
// Keep patterns in output space (uv * OUT), not screen pixels, so the saved
// 1080×1440 photo looks exactly like the smaller live preview.

import {
  FONT, HEART, MONO_FONT, confettiPiece, fitFont, germanDate, outlinedText, pixelSprite, pixelText,
  roundRectPath, seeded, sticker, star, vcrDate,
} from './overlays.js';

// ------------------------------------------------------- Canvas2D helpers

/** cpu fallback from a per-pixel function fn(d, i, x, y, w, h) on RGBA data. */
function pixelOp(fn) {
  return (ctx, w, h) => {
    const img = ctx.getImageData(0, 0, w, h);
    const d = img.data;
    for (let y = 0, i = 0; y < h; y++) {
      for (let x = 0; x < w; x++, i += 4) fn(d, i, x, y, w, h);
    }
    ctx.putImageData(img, 0, 0);
  };
}

const lum = (d, i) => 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
const smooth = (t) => t * t * (3 - 2 * t);

function vignette2d(x, y, w, h, amount) {
  const dx = (x / w - 0.5) * 0.75;
  const dy = y / h - 0.5;
  const t = Math.min(1, Math.max(0, (Math.sqrt(dx * dx + dy * dy) - 0.25) / 0.45));
  return 1 - amount * smooth(t);
}

const hex = (s) => [1, 3, 5].map((k) => parseInt(s.slice(k, k + 2), 16) / 255);

// PICO-8: a friendly 16 colour palette, skin tones survive it
const PICO8 = [
  '#000000', '#1d2b53', '#7e2553', '#008751', '#ab5236', '#5f574f', '#c2c3c7', '#fff1e8',
  '#ff004d', '#ffa300', '#ffec27', '#00e436', '#29adff', '#83769c', '#ff77a8', '#ffccaa',
].map(hex);

// ---------------------------------------------------------------- overlays

function partyFrame(ctx, w, h, info) {
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
  fitFont(ctx, info.title, w - side * 2 - 40, 112, 48);
  outlinedText(ctx, info.title, cx, band + bottom * 0.42, { stroke: '#4a0d6b', width: 16 });
  ctx.font = `800 40px ${FONT}`;
  ctx.fillStyle = 'rgba(43, 10, 69, 0.85)';
  ctx.fillText(`${germanDate(info.date)}  ·  📸 Fotobox`, cx, band + bottom * 0.8);
}

function emojiProps(ctx, w, h) {
  const rnd = seeded(42);
  // confetti border: dense at the edges, thinning out towards the middle
  for (let n = 0; n < 520; n++) {
    const edge = Math.floor(rnd() * 4);
    const along = rnd();
    const depth = Math.pow(rnd(), 2.4) * 190;
    const x = edge === 0 ? depth : edge === 1 ? w - depth : along * w;
    const y = edge === 2 ? depth : edge === 3 ? h - depth : along * h;
    ctx.globalAlpha = 0.75 + rnd() * 0.25;
    confettiPiece(ctx, rnd, x, y, 1.1);
  }
  ctx.globalAlpha = 1;
  // stickers around the face, never on it
  const stickers = [
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

function vhsOverlay(ctx, w, h, info) {
  const pad = 72;
  ctx.textBaseline = 'alphabetic';
  const vcr = (text, x, y, align = 'left') => {
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

const RETRO_CELL = 15; // = 1080 / 72, the Retro-Pixel grid

function retroHud(ctx, w, h, info) {
  const c = RETRO_CELL;
  const ink = '#fff1e8';
  const shade = '#1d2b53';
  const hud = (text, x, y, align) => {
    pixelText(ctx, text, x + c, y + c, c / 1.5, shade, { align, px: 9 });
    pixelText(ctx, text, x, y, c / 1.5, ink, { align, px: 9 });
  };
  hud('1UP', c * 3, c * 2, 'left');
  for (let i = 0; i < 3; i++) {
    pixelSprite(ctx, HEART, c * 3 + i * c * 8 + c, c * 7 + c, c, shade);
    pixelSprite(ctx, HEART, c * 3 + i * c * 8, c * 7, c, '#ff004d');
  }
  hud(`HI ${String(info.date.getFullYear()).padStart(6, '0')}`, w - c * 3, c * 2, 'right');
  const name = info.partyName.toUpperCase().slice(0, 18);
  hud(name, w / 2, h - c * 9, 'center');
}

function comicOverlay(ctx, w) {
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
  ctx.font = `900 italic 74px ${FONT}`;
  outlinedText(ctx, 'WOW!', 0, 4, { fill: '#ffffff', stroke: '#1a0526', width: 12, shadow: 'transparent' });
  ctx.restore();
}

// ----------------------------------------------------------------- filters

export const FILTERS = [
  {
    id: 'normal',
    glsl: `vec3 effect(vec2 uv) { return video(uv); }`,
    cpu: null, // nothing to do; still available in the fallback
    fallback: true,
  },

  {
    id: 'bw',
    glsl: `
vec3 effect(vec2 uv) {
  float l = scurve(luma(video(uv)), 0.75);   // deep blacks, bright whites
  return vec3(l * vignette(uv, 0.35));
}`,
    cpu: pixelOp((d, i, x, y, w, h) => {
      let l = lum(d, i) / 255;
      l = l + (smooth(l) - l) * 0.75;
      d[i] = d[i + 1] = d[i + 2] = 255 * l * vignette2d(x, y, w, h, 0.35);
    }),
  },

  {
    id: 'sepia',
    glsl: `
vec3 effect(vec2 uv) {
  float l = scurve(luma(video(uv)), 0.4);
  vec3 shadow = vec3(0.16, 0.09, 0.05);
  vec3 mid = vec3(0.66, 0.47, 0.30);
  vec3 light = vec3(1.0, 0.95, 0.85);
  vec3 c = l < 0.5 ? mix(shadow, mid, l * 2.0) : mix(mid, light, l * 2.0 - 1.0);
  c += (hash(floor(uv * OUT / 2.0)) - 0.5) * 0.035;  // a little film grain
  return c * vignette(uv, 0.45);
}`,
    cpu: pixelOp((d, i, x, y, w, h) => {
      let l = lum(d, i) / 255;
      l = l + (smooth(l) - l) * 0.4;
      const v = vignette2d(x, y, w, h, 0.45) * 255;
      const t = l < 0.5 ? l * 2 : l * 2 - 1;
      const a = l < 0.5 ? [0.16, 0.09, 0.05] : [0.66, 0.47, 0.3];
      const b = l < 0.5 ? [0.66, 0.47, 0.3] : [1.0, 0.95, 0.85];
      d[i] = (a[0] + (b[0] - a[0]) * t) * v;
      d[i + 1] = (a[1] + (b[1] - a[1]) * t) * v;
      d[i + 2] = (a[2] + (b[2] - a[2]) * t) * v;
    }),
  },

  {
    id: 'colorpop',
    glsl: `
vec3 effect(vec2 uv) {
  vec3 c = video(uv);
  vec3 hsv = rgb2hsv(c);
  float hue = hsv.x * 360.0;
  float dist = min(abs(hue - 8.0), 360.0 - abs(hue - 8.0));    // distance to red
  float keep = (1.0 - smoothstep(22.0, 40.0, dist))
             * smoothstep(0.38, 0.55, hsv.y)                  // only strong colours (no skin)
             * smoothstep(0.12, 0.25, hsv.z);
  vec3 grey = vec3(scurve(luma(c), 0.5));
  return mix(grey, saturation(c, 1.35), keep);
}`,
    cpu: pixelOp((d, i) => {
      const r = d[i] / 255;
      const g = d[i + 1] / 255;
      const b = d[i + 2] / 255;
      const max = Math.max(r, g, b);
      const min = Math.min(r, g, b);
      const s = max ? (max - min) / max : 0;
      let hue = 0;
      if (max !== min) {
        if (max === r) hue = 60 * (((g - b) / (max - min)) % 6);
        else if (max === g) hue = 60 * ((b - r) / (max - min) + 2);
        else hue = 60 * ((r - g) / (max - min) + 4);
      }
      if (hue < 0) hue += 360;
      const dist = Math.min(Math.abs(hue - 8), 360 - Math.abs(hue - 8));
      const step = (a, z, v) => smooth(Math.min(1, Math.max(0, (v - a) / (z - a))));
      const keep = (1 - step(22, 40, dist)) * step(0.38, 0.55, s) * step(0.12, 0.25, max);
      let l = lum(d, i) / 255;
      l = (l + (smooth(l) - l) * 0.5) * 255;
      d[i] = l + (d[i] - l) * keep;
      d[i + 1] = l + (d[i + 1] - l) * keep;
      d[i + 2] = l + (d[i + 2] - l) * keep;
    }),
  },

  {
    id: 'party',
    glsl: `vec3 effect(vec2 uv) { return contrast(saturation(video(uv), 1.2), 1.05); }`,
    overlay: partyFrame,
    fallback: true,
  },

  {
    id: 'emoji',
    glsl: `vec3 effect(vec2 uv) { return contrast(saturation(video(uv), 1.15), 1.04); }`,
    overlay: emojiProps,
    fallback: true,
  },

  {
    id: 'neon',
    glsl: `
vec3 effect(vec2 uv) {
  float l = smoothstep(0.04, 0.96, luma(video(uv)));
  vec3 night = vec3(0.09, 0.0, 0.22);
  vec3 pink = vec3(1.0, 0.18, 0.55);
  vec3 cyan = vec3(0.35, 0.95, 1.0);
  vec3 c = l < 0.55 ? mix(night, pink, l / 0.55) : mix(pink, cyan, (l - 0.55) / 0.45);
  return c * vignette(uv, 0.3);
}`,
    cpu: (() => {
      const night = [0.09, 0, 0.22];
      const pink = [1, 0.18, 0.55];
      const cyan = [0.35, 0.95, 1];
      const lut = new Uint8ClampedArray(256 * 3);
      for (let v = 0; v < 256; v++) {
        const l = smooth(Math.min(1, Math.max(0, (v / 255 - 0.04) / 0.92)));
        const [a, b, t] = l < 0.55 ? [night, pink, l / 0.55] : [pink, cyan, (l - 0.55) / 0.45];
        for (let k = 0; k < 3; k++) lut[v * 3 + k] = 255 * (a[k] + (b[k] - a[k]) * t);
      }
      return pixelOp((d, i) => {
        const v = Math.round(lum(d, i)) * 3;
        d[i] = lut[v];
        d[i + 1] = lut[v + 1];
        d[i + 2] = lut[v + 2];
      });
    })(),
  },

  {
    id: 'vhs',
    glsl: `
vec3 effect(vec2 uv) {
  float line = floor(uv.y * 360.0);
  float frame = floor(u_time * 15.0);
  float wobble = (hash(vec2(line, frame)) - 0.5) * 0.0016;   // tape jitter
  vec2 p = uv + vec2(wobble, 0.0);
  float shift = 0.0035;                                     // colour bleed
  vec3 c = vec3(video(p + vec2(shift, 0.0)).r, video(p).g, video(p - vec2(shift, 0.0)).b);
  c = saturation(c, 0.8);
  c = c * vec3(1.05, 0.98, 0.86) * 0.9 + vec3(0.07, 0.05, 0.08);   // warm, faded blacks
  c *= 0.965 + 0.035 * sin(uv.y * 360.0 * 3.14159);                  // soft scanlines
  c += (hash(floor(uv * OUT / 2.0) + frame) - 0.5) * 0.07;           // grain
  return c * vignette(uv, 0.5);
}`,
    overlay: vhsOverlay,
  },

  {
    id: 'retro',
    uniforms: { u_palette: PICO8.flat() },
    glsl: `
uniform vec3 u_palette[16];
vec3 effect(vec2 uv) {
  vec2 cells = vec2(72.0, 96.0);
  vec2 cell = floor(uv * cells);
  vec2 q = 0.25 / cells;
  vec2 m = (cell + 0.5) / cells;
  vec3 c = (video(m + vec2(-q.x, -q.y)) + video(m + vec2(q.x, -q.y)) +
            video(m + vec2(-q.x, q.y)) + video(m + vec2(q.x, q.y))) * 0.25;
  c = contrast(saturation(c, 1.25), 1.1);
  // 2x2 ordered dithering
  float b = mod(cell.x, 2.0) + mod(cell.y, 2.0) * 2.0;
  float bayer = b < 0.5 ? 0.0 : b < 1.5 ? 0.5 : b < 2.5 ? 0.75 : 0.25;
  c += (bayer - 0.375) * 0.14;
  vec3 best = u_palette[0];
  float bestD = 100.0;
  for (int i = 0; i < 16; i++) {
    vec3 d = (c - u_palette[i]) * vec3(0.55, 0.77, 0.33);
    float dd = dot(d, d);
    if (dd < bestD) { bestD = dd; best = u_palette[i]; }
  }
  return best;
}`,
    overlay: retroHud,
  },

  {
    id: 'comic',
    glsl: `
vec3 effect(vec2 uv) {
  vec2 o = u_px * 1.5;
  float tl = luma(video(uv + vec2(-o.x, -o.y))), t = luma(video(uv + vec2(0.0, -o.y)));
  float tr = luma(video(uv + vec2(o.x, -o.y))), l = luma(video(uv + vec2(-o.x, 0.0)));
  float r = luma(video(uv + vec2(o.x, 0.0))), bl = luma(video(uv + vec2(-o.x, o.y)));
  float b = luma(video(uv + vec2(0.0, o.y))), br = luma(video(uv + vec2(o.x, o.y)));
  float gx = tr + 2.0 * r + br - tl - 2.0 * l - bl;
  float gy = bl + 2.0 * b + br - tl - 2.0 * t - tr;
  float edge = smoothstep(0.35, 0.7, length(vec2(gx, gy)));

  vec3 c = saturation(video(uv), 1.6);
  c = floor(c * 4.0 + 0.5) / 4.0;                       // posterize
  // halftone dots, rotated 45°, bigger where it is darker
  vec2 p = uv * OUT / 12.0;
  p = vec2(p.x + p.y, p.y - p.x) * 0.7071;
  float dark = 1.0 - luma(c);
  float dotMask = 1.0 - smoothstep(0.0, 0.08, length(fract(p) - 0.5) - dark * 0.55);
  c *= 1.0 - dotMask * 0.35;
  return mix(c, vec3(0.06, 0.02, 0.1), edge);
}`,
    overlay: comicOverlay,
  },
];

/** Merge the catalogue (filters.json) with the implementations above. */
export function buildFilterList(catalogue, mode) {
  const byId = new Map(FILTERS.map((f) => [f.id, f]));
  const list = [];
  for (const entry of catalogue) {
    const impl = byId.get(entry.id);
    if (!impl) {
      console.warn(`Fotobox: filter "${entry.id}" has no implementation in filters.js`);
      continue;
    }
    if (mode === 'canvas2d' && !impl.cpu && !impl.fallback) continue;
    list.push({ ...impl, name: entry.name, icon: entry.icon || '✨' });
  }
  return list;
}

/** Draw a filter's overlay onto a fresh transparent canvas (null if none). */
export function drawOverlay(filter, width, height, info) {
  if (!filter.overlay) return null;
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  filter.overlay(ctx, width, height, info);
  return canvas;
}

