/**
 * Fotobox filters: WebGL1 shaders (GLSL ES 1.0) plus Canvas2D fallbacks. OWNER: wave 2 "AC".
 * Port of booth/static/filters.js. Never CSS filters or ctx.filter: the photo is the
 * shader's output, so the preview and the saved JPEG are the same pixels.
 *
 * The catalogue (ids, German names, icons, strip order) comes from the backend,
 * `GET /api/x/booth/filters` (backend/src/virtubooth/extensions/booth/filters.json);
 * the server only accepts ids listed there. Adding a filter: add the catalogue entry,
 * then an implementation with the same id below.
 *
 * A filter snippet defines `vec3 effect(vec2 uv)` (uv = output position, (0,0) top
 * left) and may declare its own uniforms. Helpers from the renderer's PRELUDE:
 * video(uv), luma(c), saturation(c, s), contrast(c, k), scurve(x, k), vignette(uv, a),
 * hash(p), rgb2hsv(c), hsv2rgb(c), OUT (1080×1440), u_time (s), u_px (one camera pixel
 * in uv). Keep patterns in output space (uv * OUT), never screen pixels, so the small
 * preview and the 1080×1440 photo look the same.
 */
import type { BoothFilter } from '@/api/types';

/** A catalogue entry (the server's). */
export type FilterDef = BoothFilter;

export interface RenderState {
  mirror: boolean;
  /** seconds, for animated grain and tape jitter */
  time: number;
}

/** A uniform value: number, vec2/3/4, or a vec3 array (length a multiple of 3). */
export type UniformValue = number | readonly number[];

export interface FilterImpl {
  id: string;
  glsl: string;
  uniforms?: Readonly<Record<string, UniformValue | ((state: RenderState) => UniformValue)>>;
  /** Canvas2D fallback on the picture already drawn into ctx (w×h) */
  cpu?: (ctx: CanvasRenderingContext2D, w: number, h: number) => void;
  /** without `cpu`, still offer it in Canvas2D mode (plain picture + overlay) */
  fallback?: boolean;
}

export type Filter = FilterDef & FilterImpl;

// ------------------------------------------------------- Canvas2D helpers

type PixelFn = (d: Uint8ClampedArray, i: number, x: number, y: number, w: number, h: number) => void;

/** cpu fallback from a per-pixel function on RGBA data. */
function pixelOp(fn: PixelFn): NonNullable<FilterImpl['cpu']> {
  return (ctx, w, h) => {
    const img = ctx.getImageData(0, 0, w, h);
    const d = img.data;
    for (let y = 0, i = 0; y < h; y++) {
      for (let x = 0; x < w; x++, i += 4) fn(d, i, x, y, w, h);
    }
    ctx.putImageData(img, 0, 0);
  };
}

const at = (d: Uint8ClampedArray, i: number): number => d[i] ?? 0;
const lum = (d: Uint8ClampedArray, i: number): number =>
  0.299 * at(d, i) + 0.587 * at(d, i + 1) + 0.114 * at(d, i + 2);
const smooth = (t: number): number => t * t * (3 - 2 * t);

function vignette2d(x: number, y: number, w: number, h: number, amount: number): number {
  const dx = (x / w - 0.5) * 0.75;
  const dy = y / h - 0.5;
  const t = Math.min(1, Math.max(0, (Math.sqrt(dx * dx + dy * dy) - 0.25) / 0.45));
  return 1 - amount * smooth(t);
}

const hex = (s: string): [number, number, number] => [
  Number.parseInt(s.slice(1, 3), 16) / 255,
  Number.parseInt(s.slice(3, 5), 16) / 255,
  Number.parseInt(s.slice(5, 7), 16) / 255,
];

/** PICO-8: a friendly 16 colour palette; skin tones survive it. */
export const PICO8: ReadonlyArray<[number, number, number]> = [
  '#000000',
  '#1d2b53',
  '#7e2553',
  '#008751',
  '#ab5236',
  '#5f574f',
  '#c2c3c7',
  '#fff1e8',
  '#ff004d',
  '#ffa300',
  '#ffec27',
  '#00e436',
  '#29adff',
  '#83769c',
  '#ff77a8',
  '#ffccaa',
].map(hex);

function neonLut(): Uint8ClampedArray {
  const night = [0.09, 0, 0.22];
  const pink = [1, 0.18, 0.55];
  const cyan = [0.35, 0.95, 1];
  const lut = new Uint8ClampedArray(256 * 3);
  for (let v = 0; v < 256; v++) {
    const l = smooth(Math.min(1, Math.max(0, (v / 255 - 0.04) / 0.92)));
    const [a, b, t] = l < 0.55 ? [night, pink, l / 0.55] : [pink, cyan, (l - 0.55) / 0.45];
    for (let k = 0; k < 3; k++) lut[v * 3 + k] = 255 * ((a[k] ?? 0) + ((b[k] ?? 0) - (a[k] ?? 0)) * t);
  }
  return lut;
}

// ----------------------------------------------------------------- filters

/** The plain camera picture: the Beer Cam and the base shader every renderer starts with. */
export const NORMAL: FilterImpl = {
  id: 'normal',
  glsl: `vec3 effect(vec2 uv) { return video(uv); }`,
  fallback: true,
};

const IMPLS: FilterImpl[] = [
  NORMAL,

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
      const v = 255 * l * vignette2d(x, y, w, h, 0.35);
      d[i] = v;
      d[i + 1] = v;
      d[i + 2] = v;
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
      for (let k = 0; k < 3; k++) d[i + k] = ((a[k] ?? 0) + ((b[k] ?? 0) - (a[k] ?? 0)) * t) * v;
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
             * smoothstep(0.45, 0.62, hsv.y)                  // only strong colours (no skin)
             * smoothstep(0.25, 0.4, hsv.z);                  // no dark browns (hair)
  vec3 grey = vec3(scurve(luma(c), 0.5));
  return mix(grey, saturation(c, 1.35), keep);
}`,
    cpu: pixelOp((d, i) => {
      const r = at(d, i) / 255;
      const g = at(d, i + 1) / 255;
      const b = at(d, i + 2) / 255;
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
      const step = (a: number, z: number, v: number) => smooth(Math.min(1, Math.max(0, (v - a) / (z - a))));
      const keep = (1 - step(22, 40, dist)) * step(0.45, 0.62, s) * step(0.25, 0.4, max);
      let l = lum(d, i) / 255;
      l = (l + (smooth(l) - l) * 0.5) * 255;
      for (let k = 0; k < 3; k++) d[i + k] = l + (at(d, i + k) - l) * keep;
    }),
  },

  {
    id: 'party',
    glsl: `vec3 effect(vec2 uv) { return contrast(saturation(video(uv), 1.2), 1.05); }`,
    fallback: true,
  },

  {
    id: 'emoji',
    glsl: `vec3 effect(vec2 uv) { return contrast(saturation(video(uv), 1.15), 1.04); }`,
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
      let lut: Uint8ClampedArray | null = null;
      return pixelOp((d, i) => {
        lut ??= neonLut();
        const v = Math.round(lum(d, i)) * 3;
        d[i] = lut[v] ?? 0;
        d[i + 1] = lut[v + 1] ?? 0;
        d[i + 2] = lut[v + 2] ?? 0;
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
  c += (bayer - 0.375) * 0.08;
  vec3 best = u_palette[0];
  float bestD = 100.0;
  for (int i = 0; i < 16; i++) {
    vec3 d = (c - u_palette[i]) * vec3(0.55, 0.77, 0.33);
    float dd = dot(d, d);
    if (dd < bestD) { bestD = dd; best = u_palette[i]; }
  }
  return best;
}`,
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
  },

  {
    id: 'thermal',
    glsl: `
vec3 heat(float t) {
  // cold → hot: night blue, violet, magenta, red, orange, yellow, white
  float s = clamp(t, 0.0, 1.0) * 5.0;
  vec3 c = mix(vec3(0.02, 0.0, 0.12), vec3(0.2, 0.0, 0.6), clamp(s, 0.0, 1.0));
  c = mix(c, vec3(0.78, 0.0, 0.55), clamp(s - 1.0, 0.0, 1.0));
  c = mix(c, vec3(1.0, 0.18, 0.08), clamp(s - 2.0, 0.0, 1.0));
  c = mix(c, vec3(1.0, 0.72, 0.0), clamp(s - 3.0, 0.0, 1.0));
  return mix(c, vec3(1.0, 1.0, 0.86), clamp(s - 4.0, 0.0, 1.0));
}
vec3 effect(vec2 uv) {
  vec2 o = u_px * 2.0;   // a little soft, like a thermal sensor
  vec3 c = video(uv) * 0.4 + (video(uv + vec2(o.x, 0.0)) + video(uv - vec2(o.x, 0.0)) +
                              video(uv + vec2(0.0, o.y)) + video(uv - vec2(0.0, o.y))) * 0.15;
  float warm = clamp(c.r - c.b, 0.0, 0.25);   // skin and lips glow hotter
  return heat(luma(c) * 0.7 + warm + 0.04);
}`,
    cpu: (() => {
      const stops = [
        [0.02, 0, 0.12],
        [0.2, 0, 0.6],
        [0.78, 0, 0.55],
        [1, 0.18, 0.08],
        [1, 0.72, 0],
        [1, 1, 0.86],
      ];
      return pixelOp((d, i) => {
        const r = at(d, i) / 255;
        const b = at(d, i + 2) / 255;
        const warm = Math.min(0.25, Math.max(0, r - b));
        const s = Math.min(1, Math.max(0, (lum(d, i) / 255) * 0.7 + warm + 0.04)) * 5;
        const k = Math.min(4, Math.floor(s));
        const a = stops[k] ?? [0, 0, 0];
        const z = stops[k + 1] ?? a;
        const t = s - k;
        for (let c = 0; c < 3; c++) d[i + c] = 255 * ((a[c] ?? 0) + ((z[c] ?? 0) - (a[c] ?? 0)) * t);
      });
    })(),
  },

  {
    id: 'disco',
    glsl: `
float spot(vec2 p, vec2 at, float size) {
  vec2 d = p - at;
  return exp(-dot(d, d) / (size * size));
}
vec3 effect(vec2 uv) {
  float t = u_time;
  vec2 p = (uv - 0.5) * vec2(0.75, 1.0);   // aspect-true, centred
  // chroma split: the colour channels drift apart, more towards the edges
  vec2 split = vec2(cos(t * 1.7), sin(t * 1.3)) * 0.006 + p * 0.03;
  vec3 c = vec3(video(uv + split).r, video(uv).g, video(uv - split).b);
  c = contrast(saturation(c, 1.4), 1.12);
  // three coloured spotlights sweeping over the dance floor
  vec3 light = vec3(1.0, 0.15, 0.6) * spot(p, vec2(sin(t * 0.7), cos(t * 0.5)) * 0.32, 0.26)
             + vec3(0.1, 0.75, 1.0) * spot(p, vec2(cos(t * 0.6 + 2.0), sin(t * 0.8)) * 0.34, 0.24)
             + vec3(1.0, 0.85, 0.1) * spot(p, vec2(sin(t * 0.9 + 4.0), sin(t * 0.4 + 1.0)) * 0.3, 0.22);
  c = c * (0.62 + light * 0.75) + light * 0.06;
  // mirror-ball sparkles: a star in some cells of a 54 px grid (output space), twinkling
  vec2 g = uv * OUT / 54.0;
  vec2 cell = floor(g);
  float h = hash(cell);
  vec2 q = abs(fract(g) - 0.5 - (vec2(hash(cell + 7.0), hash(cell + 13.0)) - 0.5) * 0.5);
  float star = max(0.0, 1.0 - length(q) * 7.0) + max(0.0, 1.0 - q.x * 40.0) * max(0.0, 1.0 - q.y * 4.0)
             + max(0.0, 1.0 - q.y * 40.0) * max(0.0, 1.0 - q.x * 4.0);
  float twinkle = step(0.93, h) * max(0.0, sin(t * 3.0 + h * 60.0));
  return c + vec3(star * twinkle);
}`,
  },

  {
    id: 'kaleido',
    glsl: `
// six copies of the face in a ring, every other one mirrored (seamless edges)
const float SEG = 3.14159265 / 3.0;
vec3 effect(vec2 uv) {
  vec2 p = (uv - 0.5) * OUT;
  float a = atan(p.y, p.x) + u_time * 0.1;           // the ring turns slowly
  a = abs(mod(a, 2.0 * SEG) - SEG) - SEG * 0.5;      // fold into one 60° wedge
  a -= 1.5707963;                                     // which points up
  vec2 local = vec2(cos(a), sin(a)) * length(p) + vec2(0.0, 330.0);
  // the wedge holds the camera's middle, where the face is: chins meet in the centre
  vec2 src = (vec2(0.5, 0.42) * OUT + local * 1.3) / OUT;
  src = 1.0 - abs(1.0 - mod(src, 2.0));               // mirrored at the picture's edges
  return saturation(video(src), 1.2) * vignette(uv, 0.35);
}`,
  },

  {
    id: 'glow',
    glsl: `
float edges(vec2 uv, vec2 o) {
  float tl = luma(video(uv + vec2(-o.x, -o.y))), t = luma(video(uv + vec2(0.0, -o.y)));
  float tr = luma(video(uv + vec2(o.x, -o.y))), l = luma(video(uv + vec2(-o.x, 0.0)));
  float r = luma(video(uv + vec2(o.x, 0.0))), bl = luma(video(uv + vec2(-o.x, o.y)));
  float b = luma(video(uv + vec2(0.0, o.y))), br = luma(video(uv + vec2(o.x, o.y)));
  return length(vec2(tr + 2.0 * r + br - tl - 2.0 * l - bl, bl + 2.0 * b + br - tl - 2.0 * t - tr));
}
vec3 effect(vec2 uv) {
  float line = smoothstep(0.22, 0.6, edges(uv, u_px * 1.5));   // the tube
  float halo = smoothstep(0.2, 1.0, edges(uv, u_px * 5.0)) * 0.5;   // its glow
  // a rainbow running diagonally over the picture, slowly cycling
  float hue = fract(uv.y * 0.7 + uv.x * 0.3 - u_time * 0.08);
  vec3 tube = hsv2rgb(vec3(hue, 0.8, 1.0));
  vec3 room = video(uv) * 0.16 + vec3(0.02, 0.0, 0.05);   // the dark room behind
  return room + tube * (line + halo) + vec3(line * line * 0.3);   // white-hot core
}`,
  },
];

/** Every implementation by id. */
export const FILTER_IMPLS: ReadonlyMap<string, FilterImpl> = new Map(IMPLS.map((f) => [f.id, f]));

/** Whether a filter can run on this renderer. */
export function runsOn(impl: FilterImpl, kind: 'webgl' | 'canvas2d'): boolean {
  return kind === 'webgl' || !!impl.cpu || !!impl.fallback;
}

/**
 * Merges the server's catalogue (order, name, icon) with the implementations by id.
 * Ids without an implementation are skipped (and reported in `missing`); in Canvas2D
 * mode filters with neither `cpu` nor `fallback` are left out.
 */
export function buildFilterList(
  catalogue: ReadonlyArray<FilterDef>,
  kind: 'webgl' | 'canvas2d',
): { filters: Filter[]; missing: string[] } {
  const filters: Filter[] = [];
  const missing: string[] = [];
  for (const entry of catalogue) {
    const impl = FILTER_IMPLS.get(entry.id);
    if (!impl) {
      missing.push(entry.id);
      continue;
    }
    if (!runsOn(impl, kind)) continue;
    filters.push({ ...impl, id: entry.id, name: entry.name, icon: entry.icon || '✨' });
  }
  return { filters, missing };
}
