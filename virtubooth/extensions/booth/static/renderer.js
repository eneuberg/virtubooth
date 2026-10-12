// Fotobox renderer: draws the camera video through the current filter.
//
//   const r = createRenderer(canvas);          // WebGL1, or Canvas2D fallback
//   r.mode                                      // 'webgl' | 'canvas2d'
//   r.setFilter(filter, overlayCanvas | null)   // overlay: OUTPUT_W×OUTPUT_H, transparent
//   r.render(video, { mirror, time })           // one preview frame onto `canvas`
//   r.capture()                                 // → 2D canvas OUTPUT_W×OUTPUT_H
//
// Preview and capture run the same shader with the same video frame, time and
// overlay texture, only at different sizes, so the photo is what the guest saw.
// All filter patterns (grain, pixels, dots) are defined in output space, never
// in screen pixels, so they look the same at both sizes.

export const OUTPUT_W = 1080;
export const OUTPUT_H = 1440;
const ASPECT = OUTPUT_W / OUTPUT_H;

/** Cover-crop the video to 3:4 → visible area in texture coords {x, y, w, h}. */
export function coverCrop(vw, vh) {
  if (!vw || !vh) return { x: 0, y: 0, w: 1, h: 1 };
  const a = vw / vh;
  if (a > ASPECT) {
    const w = ASPECT / a;
    return { x: (1 - w) / 2, y: 0, w, h: 1 };
  }
  const h = a / ASPECT;
  return { x: 0, y: (1 - h) / 2, w: 1, h };
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

// Shared by every filter snippet (GLSL ES 1.0). A snippet defines
//   vec3 effect(vec2 uv)   // uv: output position, (0,0) top left, (1,1) bottom right
// and may declare its own uniforms.
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
const vec2 OUT = vec2(${OUTPUT_W}.0, ${OUTPUT_H}.0); // output size: use for patterns

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
  vec2 d = (uv - 0.5) * vec2(${ASPECT}, 1.0);
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

export function fragmentSource(filter) {
  return `${PRELUDE}\n// ---- filter: ${filter.id}\n${filter.glsl}\n${MAIN}`;
}

// One reused canvas for captured photos (iOS Safari caps total canvas memory).
// It is only valid until the next capture.
let captured = null;
function captureCanvas() {
  if (!captured) {
    captured = document.createElement('canvas');
    captured.width = OUTPUT_W;
    captured.height = OUTPUT_H;
  }
  return captured;
}

// ------------------------------------------------------------------ WebGL

function compileShader(gl, type, source, label) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS) && !gl.isContextLost()) {
    const log = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(`Shader ${label}: ${log}`);
  }
  return shader;
}

function setUniform(gl, loc, value) {
  if (typeof value === 'number') gl.uniform1f(loc, value);
  else if (value.length === 2) gl.uniform2fv(loc, value);
  else if (value.length === 3) gl.uniform3fv(loc, value);
  else if (value.length === 4) gl.uniform4fv(loc, value);
  else if (value.length % 3 === 0) gl.uniform3fv(loc, value); // vec3 array
  else throw new Error(`unsupported uniform value (length ${value.length})`);
}

class GLRenderer {
  constructor(canvas, gl) {
    this.mode = 'webgl';
    this.canvas = canvas;
    this.gl = gl;
    this.filter = null;
    this.overlay = null;
    this.state = { mirror: false, time: 0 };
    this.videoSize = [0, 0];
    this.lost = false;
    this.setup();
    canvas.addEventListener('webglcontextlost', (e) => {
      e.preventDefault(); // allows the browser to restore it
      this.lost = true;
    });
    canvas.addEventListener('webglcontextrestored', () => {
      this.lost = false;
      this.setup();
      if (this.filter) this.setFilter(this.filter, this.overlay);
    });
  }

  setup() {
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
  texture() {
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

  program(filter) {
    let p = this.programs.get(filter.id);
    if (p) return p;
    const gl = this.gl;
    const fs = compileShader(gl, gl.FRAGMENT_SHADER, fragmentSource(filter), filter.id);
    const prog = gl.createProgram();
    gl.attachShader(prog, this.vertexShader);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS) && !gl.isContextLost()) {
      throw new Error(`Program ${filter.id}: ${gl.getProgramInfoLog(prog)}`);
    }
    const loc = (name) => gl.getUniformLocation(prog, name);
    p = {
      prog,
      aPos: gl.getAttribLocation(prog, 'a_pos'),
      u: {
        video: loc('u_video'), overlay: loc('u_overlay'), crop: loc('u_crop'), mirror: loc('u_mirror'),
        time: loc('u_time'), px: loc('u_px'), flipY: loc('u_flipY'),
      },
      custom: Object.keys(filter.uniforms || {}).map((name) => [name, loc(name)]),
    };
    this.programs.set(filter.id, p);
    return p;
  }

  setFilter(filter, overlayCanvas) {
    if (this.lost) {
      this.filter = filter;
      this.overlay = overlayCanvas;
      return;
    }
    this.program(filter); // compile now: errors surface here, not mid-frame
    this.filter = filter;
    this.overlay = overlayCanvas;
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.overlayTex);
    if (overlayCanvas) {
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, overlayCanvas);
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    } else {
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4));
    }
  }

  /** Upload the current video frame. iOS: only once the video is really playing. */
  uploadVideo(video) {
    if (video.readyState < 2 || !video.videoWidth) return false;
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.videoTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, video);
    this.videoSize = [video.videoWidth, video.videoHeight];
    return true;
  }

  get hasFrame() { return this.videoSize[0] > 0; }

  draw(width, height, flipY) {
    const gl = this.gl;
    const p = this.program(this.filter);
    gl.useProgram(p.prog);
    gl.viewport(0, 0, width, height);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.enableVertexAttribArray(p.aPos);
    gl.vertexAttribPointer(p.aPos, 2, gl.FLOAT, false, 0, 0);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.videoTex);
    gl.uniform1i(p.u.video, 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.overlayTex);
    gl.uniform1i(p.u.overlay, 1);
    gl.activeTexture(gl.TEXTURE0);
    const [vw, vh] = this.videoSize;
    const crop = coverCrop(vw, vh);
    gl.uniform4f(p.u.crop, crop.x, crop.y, crop.w, crop.h);
    gl.uniform1f(p.u.mirror, this.state.mirror ? 1 : 0);
    gl.uniform1f(p.u.time, this.state.time);
    gl.uniform2f(p.u.px, 1 / Math.max(1, crop.w * vw), 1 / Math.max(1, crop.h * vh));
    gl.uniform1f(p.u.flipY, flipY);
    for (const [name, loc] of p.custom) {
      const value = this.filter.uniforms[name];
      setUniform(gl, loc, typeof value === 'function' ? value(this.state) : value);
    }
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }

  render(video, { mirror, time }) {
    if (this.lost || !this.filter) return false;
    this.uploadVideo(video);
    if (!this.hasFrame) return false;
    this.state = { mirror: !!mirror, time };
    this.draw(this.canvas.width, this.canvas.height, 1);
    return true;
  }

  /** Render the last previewed frame at full size into a new 2D canvas. */
  capture() {
    if (this.lost) throw new Error('WebGL context lost');
    const gl = this.gl;
    const W = OUTPUT_W;
    const H = OUTPUT_H;
    const target = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, target);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, W, H, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    const fb = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, target, 0);
    const pixels = new Uint8Array(W * H * 4);
    try {
      if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) {
        throw new Error('framebuffer incomplete');
      }
      // flipY = -1: readPixels returns rows bottom-up, so draw upside down
      this.draw(W, H, -1);
      gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    } finally {
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      gl.deleteFramebuffer(fb);
      gl.deleteTexture(target);
      gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    }
    const out = captureCanvas();
    out.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(pixels.buffer), W, H), 0, 0);
    return out;
  }
}

// --------------------------------------------------------------- Canvas2D

/** Fallback without WebGL: drawImage + per-pixel ops (filter.cpu). */
class CanvasRenderer {
  constructor(canvas) {
    this.mode = 'canvas2d';
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d', { willReadFrequently: true });
    this.filter = null;
    this.overlay = null;
    this.video = null;
    this.state = { mirror: false, time: 0 };
  }

  setFilter(filter, overlayCanvas) {
    this.filter = filter;
    this.overlay = overlayCanvas;
  }

  get hasFrame() { return !!this.video; }

  paint(ctx, width, height) {
    const video = this.video;
    const crop = coverCrop(video.videoWidth, video.videoHeight);
    ctx.save();
    if (this.state.mirror) {
      ctx.translate(width, 0);
      ctx.scale(-1, 1);
    }
    ctx.drawImage(video, crop.x * video.videoWidth, crop.y * video.videoHeight,
      crop.w * video.videoWidth, crop.h * video.videoHeight, 0, 0, width, height);
    ctx.restore();
    if (this.filter.cpu) this.filter.cpu(ctx, width, height, this.state);
    if (this.overlay) ctx.drawImage(this.overlay, 0, 0, width, height);
  }

  render(video, { mirror, time }) {
    if (!this.filter || video.readyState < 2 || !video.videoWidth) return false;
    this.video = video;
    this.state = { mirror: !!mirror, time };
    this.paint(this.ctx, this.canvas.width, this.canvas.height);
    return true;
  }

  capture() {
    const out = captureCanvas();
    this.paint(out.getContext('2d', { willReadFrequently: true }), OUTPUT_W, OUTPUT_H);
    return out;
  }
}

// ----------------------------------------------------------------- factory

/**
 * WebGL1 if available and the base shader compiles, else Canvas2D.
 * `prefer: 'canvas2d'` forces the fallback (testing, ?renderer=canvas2d).
 * Returns { renderer, canvas } (the fallback may need a fresh canvas).
 */
export function createRenderer(canvas, { prefer, baseFilter } = {}) {
  if (prefer !== 'canvas2d') {
    const opts = {
      alpha: false, antialias: false, depth: false, stencil: false,
      premultipliedAlpha: false, preserveDrawingBuffer: false,
    };
    const gl = canvas.getContext('webgl', opts) || canvas.getContext('experimental-webgl', opts);
    if (gl) {
      try {
        const r = new GLRenderer(canvas, gl);
        if (baseFilter) r.setFilter(baseFilter, null);
        return { renderer: r, canvas };
      } catch (err) {
        console.warn('WebGL unusable, using Canvas2D', err);
      }
      // a canvas keeps its first context type: start over with a fresh one
      const fresh = document.createElement('canvas');
      fresh.className = canvas.className;
      canvas.replaceWith(fresh);
      canvas = fresh;
    }
  }
  return { renderer: new CanvasRenderer(canvas), canvas };
}
