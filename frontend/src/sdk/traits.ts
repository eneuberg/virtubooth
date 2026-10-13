/**
 * The device-trait collector, loaded on demand by ./device.ts (its own chunk, so a
 * content blocker that drops it can never stop the page). Port of the pre-overhaul
 * core/device.js, unchanged in what it collects:
 *
 *   ua, platform, languages, timezone, screen "{max}x{min}@{dpr}", color_depth,
 *   cores, memory, touch, gl_vendor / gl_renderer / gl_max_texture, canvas (16 hex)
 *
 * hash = sha256 of the sorted "k=v" pairs joined by "|". A moderation hint only:
 * identical phone models often share it, so it never identifies a person.
 * The file name stays neutral on purpose (blockers drop /fingerprint.js).
 */
import type { DeviceTraits } from './device';
import { sha256Hex } from './hash';

type Value = string | number | boolean | null;

function canvasTrait(): string {
  try {
    const c = document.createElement('canvas');
    c.width = 240;
    c.height = 60;
    const ctx = c.getContext('2d');
    if (!ctx) return '';
    ctx.textBaseline = 'top';
    ctx.font = "16px 'Arial'";
    ctx.fillStyle = '#f60';
    ctx.fillRect(100, 1, 62, 20);
    ctx.fillStyle = '#069';
    ctx.fillText('virtubooth 🍺 Ωß', 2, 15);
    ctx.fillStyle = 'rgba(102, 204, 0, 0.7)';
    ctx.fillText('virtubooth 🍺 Ωß', 4, 17);
    ctx.beginPath();
    ctx.arc(50, 30, 20, 0, Math.PI * 2);
    ctx.stroke();
    return c.toDataURL();
  } catch {
    return '';
  }
}

function glValue(value: unknown): Value {
  return typeof value === 'string' || typeof value === 'number' ? value : null;
}

function webglTrait(): Record<string, Value> {
  try {
    const gl = document.createElement('canvas').getContext('webgl');
    if (!gl) return {};
    const ext = gl.getExtension('WEBGL_debug_renderer_info');
    const traits = {
      gl_vendor: glValue(ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR)),
      gl_renderer: glValue(ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER)),
      gl_max_texture: glValue(gl.getParameter(gl.MAX_TEXTURE_SIZE)),
    };
    // give the context back right away (browsers cap live WebGL contexts per page)
    gl.getExtension('WEBGL_lose_context')?.loseContext();
    return traits;
  } catch {
    return {};
  }
}

interface NavigatorExtras {
  deviceMemory?: number;
}

async function compute(): Promise<DeviceTraits> {
  const s = window.screen;
  const nav: Navigator & NavigatorExtras = navigator;
  const components: Record<string, Value> = {
    ua: nav.userAgent,
    // oxlint-disable-next-line typescript/no-deprecated -- same trait as before the overhaul
    platform: nav.platform || '',
    languages: (nav.languages.length ? nav.languages : [nav.language]).join(','),
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || '',
    screen: `${Math.max(s.width, s.height)}x${Math.min(s.width, s.height)}@${window.devicePixelRatio || 1}`,
    color_depth: s.colorDepth || 0,
    cores: nav.hardwareConcurrency || 0,
    memory: nav.deviceMemory ?? 0,
    touch: nav.maxTouchPoints || 0,
    ...webglTrait(),
  };
  const canvasHash = await sha256Hex(canvasTrait());
  components['canvas'] = canvasHash.slice(0, 16);
  const stable = Object.keys(components)
    // oxlint-disable-next-line unicorn/no-array-sort -- toSorted needs Firefox 115, the build targets 114
    .sort()
    .map((k) => `${k}=${String(components[k])}`)
    .join('|');
  return { hash: await sha256Hex(stable), components };
}

/** Never rejects: joining needs a value. */
export async function collectTraits(): Promise<DeviceTraits> {
  try {
    return await compute();
  } catch {
    const ua = navigator.userAgent;
    return { hash: await sha256Hex(`fallback|${ua}`), components: { ua, fallback: true } };
  }
}
