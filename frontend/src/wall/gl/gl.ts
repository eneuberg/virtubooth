/**
 * A tiny WebGL 1 helper for the shader transitions: one shared canvas, one program
 * (a full-canvas quad), two textures from decoded images, a few uniforms.
 * No WebGL (old TV, blocked, context lost) → `sharedGl()` returns null and the
 * transitions fall back to a crossfade.
 */

const VERTEX = `
attribute vec2 a_pos;
varying vec2 v_uv;
void main() {
  v_uv = vec2(a_pos.x * 0.5 + 0.5, 0.5 - a_pos.y * 0.5);
  gl_Position = vec4(a_pos, 0.0, 1.0);
}`;

// u_mode 0: pixelate (blocks grow on the old photo, shrink on the new one)
// u_mode 1: ordered dither (Bayer 8×8) dissolve with a posterised middle
const FRAGMENT = `
precision mediump float;
varying vec2 v_uv;
uniform sampler2D u_from;
uniform sampler2D u_to;
uniform vec4 u_fromMap;
uniform vec4 u_toMap;
uniform float u_hasFrom;
uniform float u_progress;
uniform vec2 u_res;
uniform int u_mode;

float bayer2(vec2 a) { a = floor(a); return fract(a.x / 2.0 + a.y * a.y * 0.75); }
float bayer4(vec2 a) { return bayer2(0.5 * a) * 0.25 + bayer2(a); }
float bayer8(vec2 a) { return bayer4(0.5 * a) * 0.25 + bayer2(a); }

vec4 fromAt(vec2 uv) {
  return u_hasFrom > 0.5 ? texture2D(u_from, uv * u_fromMap.xy + u_fromMap.zw) : vec4(0.0);
}
vec4 toAt(vec2 uv) { return texture2D(u_to, uv * u_toMap.xy + u_toMap.zw); }

void main() {
  float p = clamp(u_progress, 0.0, 1.0);
  float peak = 1.0 - abs(2.0 * p - 1.0);
  if (u_mode == 0) {
    float block = max(1.0, floor(peak * peak * u_res.y / 14.0));
    vec2 cell = (floor(v_uv * u_res / block) + 0.5) * block / u_res;
    gl_FragColor = mix(fromAt(cell), toAt(cell), smoothstep(0.4, 0.6, p));
  } else {
    float scale = max(2.0, floor(u_res.y / 220.0));
    vec2 px = floor(v_uv * u_res / scale);
    float threshold = bayer8(px);
    float sweep = clamp(p * 1.5 - 0.25 + (0.5 - v_uv.y) * 0.5, 0.0, 1.0);
    vec4 c = threshold < sweep ? toAt(v_uv) : fromAt(v_uv);
    float levels = mix(24.0, 2.0, peak);
    c.rgb = min(c.rgb, vec3(c.a));
    c.rgb = floor(c.rgb * levels + threshold) / levels;
    c.rgb = min(c.rgb, vec3(c.a));
    gl_FragColor = c;
  }
}`;

export type GlMode = 0 | 1;

export interface GlRenderer {
  readonly canvas: HTMLCanvasElement;
  /** Sets the canvas size (device pixels) and both images; false when an upload failed. */
  prepare(width: number, height: number, from: HTMLImageElement | null, to: HTMLImageElement): boolean;
  draw(mode: GlMode, progress: number): void;
}

/** uv scale + offset that maps the canvas onto an image like `object-fit: cover` */
export function coverMap(canvasAspect: number, imageAspect: number): [number, number, number, number] {
  if (!(canvasAspect > 0) || !(imageAspect > 0)) return [1, 1, 0, 0];
  if (imageAspect > canvasAspect) {
    const sx = canvasAspect / imageAspect;
    return [sx, 1, (1 - sx) / 2, 0];
  }
  const sy = imageAspect / canvasAspect;
  return [1, sy, 0, (1 - sy) / 2];
}

function compile(gl: WebGLRenderingContext, type: number, source: string): WebGLShader | null {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

function createRenderer(): GlRenderer | null {
  const canvas = document.createElement('canvas');
  canvas.className = 'wall-gl';
  let gl: WebGLRenderingContext | null = null;
  try {
    gl = canvas.getContext('webgl', { premultipliedAlpha: true, antialias: false, alpha: true });
  } catch {
    gl = null;
  }
  if (!gl) return null;
  const vs = compile(gl, gl.VERTEX_SHADER, VERTEX);
  const fs = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT);
  const program = gl.createProgram();
  if (!vs || !fs || !program) return null;
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return null;
  gl.useProgram(program);

  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const pos = gl.getAttribLocation(program, 'a_pos');
  gl.enableVertexAttribArray(pos);
  gl.vertexAttribPointer(pos, 2, gl.FLOAT, false, 0, 0);

  const textures = [gl.createTexture(), gl.createTexture()];
  textures.forEach((tex, unit) => {
    gl.activeTexture(gl.TEXTURE0 + unit);
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  });
  const u = (name: string) => gl.getUniformLocation(program, name);
  const loc = {
    from: u('u_from'),
    to: u('u_to'),
    fromMap: u('u_fromMap'),
    toMap: u('u_toMap'),
    hasFrom: u('u_hasFrom'),
    progress: u('u_progress'),
    res: u('u_res'),
    mode: u('u_mode'),
  };
  gl.uniform1i(loc.from, 0);
  gl.uniform1i(loc.to, 1);
  gl.clearColor(0, 0, 0, 0);

  const upload = (unit: number, img: HTMLImageElement): boolean => {
    gl.activeTexture(gl.TEXTURE0 + unit);
    gl.bindTexture(gl.TEXTURE_2D, textures[unit] ?? null);
    try {
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
    } catch {
      return false;
    }
    return gl.getError() === gl.NO_ERROR;
  };

  return {
    canvas,
    prepare(width, height, from, to) {
      if (gl.isContextLost()) return false;
      canvas.width = Math.max(1, Math.round(width));
      canvas.height = Math.max(1, Math.round(height));
      gl.viewport(0, 0, canvas.width, canvas.height);
      const aspect = canvas.width / canvas.height;
      if (!upload(1, to)) return false;
      gl.uniform4fv(loc.toMap, coverMap(aspect, to.naturalWidth / to.naturalHeight));
      const withFrom = from !== null && from.complete && from.naturalWidth > 0 && upload(0, from);
      gl.uniform1f(loc.hasFrom, withFrom ? 1 : 0);
      if (from && withFrom)
        gl.uniform4fv(loc.fromMap, coverMap(aspect, from.naturalWidth / from.naturalHeight));
      gl.uniform2f(loc.res, canvas.width, canvas.height);
      return true;
    },
    draw(mode, progress) {
      gl.uniform1i(loc.mode, mode);
      gl.uniform1f(loc.progress, progress);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    },
  };
}

let shared: GlRenderer | null | undefined;

/** The one WebGL canvas of the page (created on first use), or null without WebGL. */
export function sharedGl(): GlRenderer | null {
  if (shared === undefined) shared = createRenderer();
  return shared;
}

/** Whether WebGL transitions can run (creates the shared canvas once). */
export function webglAvailable(): boolean {
  return sharedGl() !== null;
}
