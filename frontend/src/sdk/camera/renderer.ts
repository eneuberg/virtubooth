/**
 * The preview/capture renderer: WebGL1, with a Canvas2D fallback. OWNER: wave 2 "AC".
 * Port of booth/static/renderer.js.
 *
 * Preview and capture run the same shader with the same video frame (the last one
 * uploaded), the same time and the same overlay texture, only at different sizes, so
 * the photo is what the guest saw. Capture renders into a 1080×1440 framebuffer and
 * reads it back into ONE reused 2D canvas (iOS caps the total canvas memory).
 */
import { coverCrop, PHOTO_ASPECT, PHOTO_H, PHOTO_W } from './capture';
import type { FilterImpl, RenderState, UniformValue } from './filters';

export type RendererKind = 'webgl' | 'canvas2d';

/** Another filter and overlay for one snapshot, leaving the preview's as they are. */
export interface Look {
  filter: FilterImpl;
  overlay: HTMLCanvasElement | null;
}

export interface Renderer {
  readonly kind: RendererKind;
  readonly canvas: HTMLCanvasElement;
  /** a video frame has been drawn */
  readonly hasFrame: boolean;
  /** compiles now, so errors surface here and not mid-frame; throws when it can't run */
  setFilter(filter: FilterImpl, overlay: HTMLCanvasElement | null): void;
  /** one preview frame onto the canvas; false until the video has a frame */
  render(video: HTMLVideoElement, state: RenderState): boolean;
  /** draws the last frame again (a new filter on a frozen preview); no new video frame */
  redraw(): void;
  /** the last rendered frame at 1080×1440 in the shared capture canvas (valid until the next capture) */
  capture(): HTMLCanvasElement;
  /**
   * the last rendered frame at any 3:4 size, in a fresh canvas (filter swatches); with
   * `look`, through that filter and overlay instead of the preview's (which stay set)
   */
  snapshot(width: number, height: number, look?: Look): HTMLCanvasElement;
  /**
   * sets the backing store from the on-screen width (DPR ≤ 2, capped); the picture on
   * it stays the same frame (a frozen preview never picks up a newer video frame)
   */
  resize(cssWidth: number, dpr: number): void;
  destroy(): void;
}

const VERTEX = `
attribute vec2 a_pos;
uniform float u_flipY;
varying vec2 v_uv;
void main() {
  v_uv = vec2(a_pos.x * 0.5 + 0.5, 0.5 - a_pos.y * 0.5);
  gl_Position = vec4(a_pos.x, a_pos.y * u_flipY, 0.0, 1.0);
}
`;

/** Shared by every filter snippet (GLSL ES 1.0). */
export const PRELUDE = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
varying vec2 v_uv;
uniform sampler2D u_video;
uniform sampler2D u_overlay;
uniform vec4 u_crop;     // visible video area in texture coords: xy offset, zw size
uniform float u_mirror;  // 1.0: mirror the video (front camera), never the overlay
uniform float u_time;    // seconds, for animated grain etc.
uniform vec2 u_px;       // one camera pixel in uv units (for edge detection & co.)
const vec2 OUT = vec2(${PHOTO_W}.0, ${PHOTO_H}.0); // output size: use for patterns

// the camera image at output position uv
vec3 video(vec2 uv) {
  uv = clamp(uv, 0.0, 1.0);
  if (u_mirror > 0.5) uv.x = 1.0 - uv.x;
  return texture2D(u_video, u_crop.xy + uv * u_crop.zw).rgb;
}
float luma(vec3 c) { return dot(c, vec3(0.299, 0.587, 0.114)); }
vec3 saturation(vec3 c, float s) { return mix(vec3(luma(c)), c, s); }
vec3 contrast(vec3 c, float k) { return (c - 0.5) * k + 0.5; }
float scurve(float x, float k) { return mix(x, x * x * (3.0 - 2.0 * x), k); }
// 1.0 in the middle, darker towards the corners
float vignette(vec2 uv, float amount) {
  vec2 d = (uv - 0.5) * vec2(${PHOTO_ASPECT}, 1.0);
  return 1.0 - amount * smoothstep(0.25, 0.7, length(d));
}
// stable pseudo random 0..1 (no sin(): precise on mobile GPUs)
float hash(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}
vec3 rgb2hsv(vec3 c) {
  vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
  vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
  vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
  float d = q.x - min(q.w, q.y);
  float e = 1.0e-10;
  return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}
vec3 hsv2rgb(vec3 c) {
  vec3 p = abs(fract(c.xxx + vec3(1.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
  return c.z * mix(vec3(1.0), clamp(p - 1.0, 0.0, 1.0), c.y);
}
`;

const MAIN = `
void main() {
  vec3 c = clamp(effect(v_uv), 0.0, 1.0);
  vec4 o = texture2D(u_overlay, v_uv);      // premultiplied alpha
  gl_FragColor = vec4(c * (1.0 - o.a) + o.rgb, 1.0);
}
`;

export function fragmentSource(filter: FilterImpl): string {
  return `${PRELUDE}\n// ---- filter: ${filter.id}\n${filter.glsl}\n${MAIN}`;
}

/** Preview backing-store caps: WebGL up to the photo width, Canvas2D pixel ops are CPU work. */
export const PREVIEW_MAX_W: Record<RendererKind, number> = { webgl: PHOTO_W, canvas2d: 480 };

/** The backing store for an on-screen width (DPR ≤ 2, never more than the cap). */
export function previewSize(cssWidth: number, dpr: number, kind: RendererKind): { w: number; h: number } {
  const ratio = Math.min(Math.max(dpr || 1, 1), 2);
  const w = Math.max(60, Math.min(PREVIEW_MAX_W[kind], Math.round(cssWidth * ratio)));
  return { w, h: Math.round((w * PHOTO_H) / PHOTO_W) };
}

// One reused canvas for captured photos (iOS Safari caps total canvas memory).
let captured: HTMLCanvasElement | null = null;
function captureCanvas(): HTMLCanvasElement {
  if (!captured) {
    captured = document.createElement('canvas');
    captured.width = PHOTO_W;
    captured.height = PHOTO_H;
  }
  return captured;
}

function context2d(canvas: HTMLCanvasElement, readBack = false): CanvasRenderingContext2D {
  const ctx = canvas.getContext('2d', readBack ? { willReadFrequently: true } : undefined);
  if (!ctx) throw new Error('Canvas2D unavailable');
  return ctx;
}

function resizeCanvas(canvas: HTMLCanvasElement, w: number, h: number): void {
  if (canvas.width !== w) canvas.width = w;
  if (canvas.height !== h) canvas.height = h;
}

// ------------------------------------------------------------------ WebGL

function compileShader(gl: WebGLRenderingContext, type: number, source: string, label: string): WebGLShader {
  const shader = gl.createShader(type);
  if (!shader) throw new Error(`Shader ${label}: no shader`);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS) && !gl.isContextLost()) {
    const log = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(`Shader ${label}: ${log ?? ''}`);
  }
  return shader;
}

function setUniform(gl: WebGLRenderingContext, loc: WebGLUniformLocation | null, value: UniformValue): void {
  if (typeof value === 'number') gl.uniform1f(loc, value);
  else if (value.length === 2) gl.uniform2fv(loc, value);
  else if (value.length === 3) gl.uniform3fv(loc, value);
  else if (value.length === 4) gl.uniform4fv(loc, value);
  else if (value.length % 3 === 0)
    gl.uniform3fv(loc, value); // vec3 array
  else throw new Error(`unsupported uniform value (length ${value.length})`);
}

interface Program {
  prog: WebGLProgram;
  aPos: number;
  u: Record<'video' | 'overlay' | 'crop' | 'mirror' | 'time' | 'px' | 'flipY', WebGLUniformLocation | null>;
  custom: Array<[string, WebGLUniformLocation | null]>;
}

const GL_OPTIONS: WebGLContextAttributes = {
  alpha: false,
  antialias: false,
  depth: false,
  stencil: false,
  premultipliedAlpha: false,
  preserveDrawingBuffer: false,
};

class GLRenderer implements Renderer {
  readonly kind = 'webgl';
  readonly canvas: HTMLCanvasElement;
  private readonly gl: WebGLRenderingContext;
  private filter: FilterImpl | null = null;
  private overlay: HTMLCanvasElement | null = null;
  private state: RenderState = { mirror: false, time: 0 };
  private videoSize: [number, number] = [0, 0];
  private lost = false;
  private programs = new Map<string, Program>();
  private vertexShader!: WebGLShader;
  private quad!: WebGLBuffer | null;
  private videoTex!: WebGLTexture | null;
  private overlayTex!: WebGLTexture | null;

  private readonly onLost = (e: Event) => {
    e.preventDefault(); // allows the browser to restore it
    this.lost = true;
  };

  private readonly onRestored = () => {
    this.lost = false;
    this.setup();
    if (this.filter) this.setFilter(this.filter, this.overlay);
  };

  constructor(canvas: HTMLCanvasElement, gl: WebGLRenderingContext) {
    this.canvas = canvas;
    this.gl = gl;
    this.setup();
    canvas.addEventListener('webglcontextlost', this.onLost);
    canvas.addEventListener('webglcontextrestored', this.onRestored);
  }

  private setup(): void {
    const gl = this.gl;
    this.programs = new Map();
    this.vertexShader = compileShader(gl, gl.VERTEX_SHADER, VERTEX, 'vertex');
    this.quad = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    this.videoTex = this.texture();
    this.overlayTex = this.texture();
    this.videoSize = [0, 0];
  }

  // NPOT textures in WebGL1: CLAMP_TO_EDGE + LINEAR, no mipmaps
  private texture(): WebGLTexture | null {
    const gl = this.gl;
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4));
    return tex;
  }

  private program(filter: FilterImpl): Program {
    const cached = this.programs.get(filter.id);
    if (cached) return cached;
    const gl = this.gl;
    const fs = compileShader(gl, gl.FRAGMENT_SHADER, fragmentSource(filter), filter.id);
    const prog = gl.createProgram();
    if (!prog) throw new Error(`Program ${filter.id}: no program`);
    gl.attachShader(prog, this.vertexShader);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS) && !gl.isContextLost()) {
      throw new Error(`Program ${filter.id}: ${gl.getProgramInfoLog(prog) ?? ''}`);
    }
    const loc = (name: string) => gl.getUniformLocation(prog, name);
    const p: Program = {
      prog,
      aPos: gl.getAttribLocation(prog, 'a_pos'),
      u: {
        video: loc('u_video'),
        overlay: loc('u_overlay'),
        crop: loc('u_crop'),
        mirror: loc('u_mirror'),
        time: loc('u_time'),
        px: loc('u_px'),
        flipY: loc('u_flipY'),
      },
      custom: Object.keys(filter.uniforms ?? {}).map((name) => [name, loc(name)]),
    };
    this.programs.set(filter.id, p);
    return p;
  }

  setFilter(filter: FilterImpl, overlay: HTMLCanvasElement | null): void {
    if (this.lost) {
      this.filter = filter;
      this.overlay = overlay;
      return;
    }
    this.program(filter); // compile now: errors surface here, not mid-frame
    this.filter = filter;
    this.overlay = overlay;
    this.uploadOverlay(this.overlayTex, overlay);
  }

  private uploadOverlay(texture: WebGLTexture | null, overlay: HTMLCanvasElement | null): void {
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, texture);
    if (overlay) {
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, overlay);
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    } else {
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4));
    }
  }

  /** Upload the current video frame. iOS: only once the video is really playing. */
  private uploadVideo(video: HTMLVideoElement): void {
    if (video.readyState < 2 || !video.videoWidth) return;
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.videoTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, video);
    this.videoSize = [video.videoWidth, video.videoHeight];
  }

  get hasFrame(): boolean {
    return this.videoSize[0] > 0;
  }

  private draw(
    width: number,
    height: number,
    flipY: number,
    look?: { filter: FilterImpl; overlayTex: WebGLTexture | null },
  ): void {
    const gl = this.gl;
    const filter = look ? look.filter : this.filter;
    if (!filter) return;
    const p = this.program(filter);
    gl.useProgram(p.prog);
    gl.viewport(0, 0, width, height);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.enableVertexAttribArray(p.aPos);
    gl.vertexAttribPointer(p.aPos, 2, gl.FLOAT, false, 0, 0);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.videoTex);
    gl.uniform1i(p.u.video, 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, look ? look.overlayTex : this.overlayTex);
    gl.uniform1i(p.u.overlay, 1);
    gl.activeTexture(gl.TEXTURE0);
    const [vw, vh] = this.videoSize;
    const crop = coverCrop(vw, vh);
    gl.uniform4f(p.u.crop, crop.x, crop.y, crop.w, crop.h);
    gl.uniform1f(p.u.mirror, this.state.mirror ? 1 : 0);
    gl.uniform1f(p.u.time, this.state.time);
    gl.uniform2f(p.u.px, 1 / Math.max(1, crop.w * vw), 1 / Math.max(1, crop.h * vh));
    gl.uniform1f(p.u.flipY, flipY);
    const uniforms = filter.uniforms ?? {};
    for (const [name, location] of p.custom) {
      const value = uniforms[name];
      if (value === undefined) continue;
      setUniform(gl, location, typeof value === 'function' ? value(this.state) : value);
    }
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }

  render(video: HTMLVideoElement, state: RenderState): boolean {
    if (this.lost || !this.filter) return false;
    this.uploadVideo(video);
    if (!this.hasFrame) return false;
    this.state = { mirror: state.mirror, time: state.time };
    this.draw(this.canvas.width, this.canvas.height, 1);
    return true;
  }

  redraw(): void {
    if (!this.lost && this.filter && this.hasFrame) this.draw(this.canvas.width, this.canvas.height, 1);
  }

  /**
   * Renders the last frame at w×h into a framebuffer and reads it back (rows top-down).
   * A `look` brings its own overlay texture for this one pass: the preview's stays, so
   * a row of swatches doesn't re-upload the 1080×1440 overlay after every one.
   */
  private readFrame(w: number, h: number, look?: Look): ImageData {
    if (this.lost) throw new Error('WebGL context lost');
    const gl = this.gl;
    let pass: { filter: FilterImpl; overlayTex: WebGLTexture | null } | undefined;
    if (look) {
      this.program(look.filter);
      const overlayTex = this.texture();
      this.uploadOverlay(overlayTex, look.overlay);
      pass = { filter: look.filter, overlayTex };
    }
    const target = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, target);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    const fb = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, target, 0);
    const pixels = new Uint8ClampedArray(w * h * 4);
    try {
      if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) {
        throw new Error('framebuffer incomplete');
      }
      // flipY = -1: readPixels returns rows bottom-up, so draw upside down
      this.draw(w, h, -1, pass);
      gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    } finally {
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      gl.deleteFramebuffer(fb);
      gl.deleteTexture(target);
      if (pass) gl.deleteTexture(pass.overlayTex);
      gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    }
    return new ImageData(pixels, w, h);
  }

  capture(): HTMLCanvasElement {
    const out = captureCanvas();
    context2d(out).putImageData(this.readFrame(PHOTO_W, PHOTO_H), 0, 0);
    return out;
  }

  snapshot(width: number, height: number, look?: Look): HTMLCanvasElement {
    const out = document.createElement('canvas');
    out.width = width;
    out.height = height;
    context2d(out).putImageData(this.readFrame(width, height, look), 0, 0);
    return out;
  }

  resize(cssWidth: number, dpr: number): void {
    const { w, h } = previewSize(cssWidth, dpr, this.kind);
    if (this.canvas.width === w && this.canvas.height === h) return;
    resizeCanvas(this.canvas, w, h);
    // the last uploaded video frame again, at the new size (no new frame)
    if (!this.lost && this.filter && this.hasFrame) this.draw(w, h, 1);
  }

  destroy(): void {
    this.canvas.removeEventListener('webglcontextlost', this.onLost);
    this.canvas.removeEventListener('webglcontextrestored', this.onRestored);
    if (this.lost) return;
    const gl = this.gl;
    for (const p of this.programs.values()) gl.deleteProgram(p.prog);
    this.programs.clear();
    gl.deleteTexture(this.videoTex);
    gl.deleteTexture(this.overlayTex);
    gl.deleteBuffer(this.quad);
    // free the context now: browsers allow only a few at a time
    gl.getExtension('WEBGL_lose_context')?.loseContext();
  }
}

// --------------------------------------------------------------- Canvas2D

/** Fallback without WebGL: drawImage + per-pixel ops (filter.cpu). */
class CanvasRenderer implements Renderer {
  readonly kind = 'canvas2d';
  readonly canvas: HTMLCanvasElement;
  private readonly ctx: CanvasRenderingContext2D;
  private filter: FilterImpl | null = null;
  private overlay: HTMLCanvasElement | null = null;
  private video: HTMLVideoElement | null = null;
  private state: RenderState = { mirror: false, time: 0 };

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    this.ctx = context2d(canvas, true);
  }

  setFilter(filter: FilterImpl, overlay: HTMLCanvasElement | null): void {
    this.filter = filter;
    this.overlay = overlay;
  }

  get hasFrame(): boolean {
    return !!this.video;
  }

  private paint(ctx: CanvasRenderingContext2D, width: number, height: number, look?: Look): void {
    const video = this.video;
    const filter = look ? look.filter : this.filter;
    const overlay = look ? look.overlay : this.overlay;
    if (!video || !filter) return;
    const vw = video.videoWidth;
    const vh = video.videoHeight;
    const crop = coverCrop(vw, vh);
    ctx.save();
    if (this.state.mirror) {
      ctx.translate(width, 0);
      ctx.scale(-1, 1);
    }
    ctx.drawImage(video, crop.x * vw, crop.y * vh, crop.w * vw, crop.h * vh, 0, 0, width, height);
    ctx.restore();
    filter.cpu?.(ctx, width, height);
    if (overlay) ctx.drawImage(overlay, 0, 0, width, height);
  }

  render(video: HTMLVideoElement, state: RenderState): boolean {
    if (!this.filter || video.readyState < 2 || !video.videoWidth) return false;
    this.video = video;
    this.state = { mirror: state.mirror, time: state.time };
    this.paint(this.ctx, this.canvas.width, this.canvas.height);
    return true;
  }

  redraw(): void {
    // the video element moved on: keep what is on the canvas
  }

  capture(): HTMLCanvasElement {
    const out = captureCanvas();
    this.paint(context2d(out, true), PHOTO_W, PHOTO_H);
    return out;
  }

  snapshot(width: number, height: number, look?: Look): HTMLCanvasElement {
    const out = document.createElement('canvas');
    out.width = width;
    out.height = height;
    this.paint(context2d(out, true), width, height, look);
    return out;
  }

  resize(cssWidth: number, dpr: number): void {
    const { w, h } = previewSize(cssWidth, dpr, this.kind);
    if (this.canvas.width === w && this.canvas.height === h) return;
    // keep the picture: the video element already shows a newer frame
    const copy = document.createElement('canvas');
    copy.width = this.canvas.width;
    copy.height = this.canvas.height;
    copy.getContext('2d')?.drawImage(this.canvas, 0, 0);
    resizeCanvas(this.canvas, w, h);
    this.ctx.drawImage(copy, 0, 0, w, h);
  }

  destroy(): void {
    this.video = null;
  }
}

// ----------------------------------------------------------------- factory

/**
 * WebGL1 if available and the base shader compiles, else Canvas2D. `prefer:
 * 'canvas2d'` forces the fallback (testing, ?renderer=canvas2d). A canvas keeps its
 * first context type, so the fallback may get a fresh canvas: use the returned one.
 */
export function createRenderer(
  canvas: HTMLCanvasElement,
  options: { prefer?: RendererKind | null; baseFilter?: FilterImpl } = {},
): { renderer: Renderer; canvas: HTMLCanvasElement } {
  let target = canvas;
  if (options.prefer !== 'canvas2d') {
    const legacy = (): WebGLRenderingContext | null => {
      const ctx = target.getContext('experimental-webgl', GL_OPTIONS);
      return typeof WebGLRenderingContext !== 'undefined' && ctx instanceof WebGLRenderingContext
        ? ctx
        : null;
    };
    const gl = target.getContext('webgl', GL_OPTIONS) ?? legacy();
    if (gl) {
      try {
        const renderer = new GLRenderer(target, gl);
        if (options.baseFilter) renderer.setFilter(options.baseFilter, null);
        return { renderer, canvas: target };
      } catch {
        // WebGL is there but unusable: fall back below
      }
      const fresh = document.createElement('canvas');
      fresh.className = target.className;
      for (const [key, value] of Object.entries(target.dataset)) {
        if (value !== undefined) fresh.dataset[key] = value;
      }
      target.replaceWith(fresh);
      target = fresh;
    }
  }
  const renderer = new CanvasRenderer(target);
  if (options.baseFilter) renderer.setFilter(options.baseFilter, null);
  return { renderer, canvas: target };
}

/** JPEG from a canvas (toBlob only: toDataURL doubles the memory on iOS). */
export function canvasToJpeg(canvas: HTMLCanvasElement, quality = 0.9): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error('toBlob failed'))),
      'image/jpeg',
      quality,
    );
  });
}
