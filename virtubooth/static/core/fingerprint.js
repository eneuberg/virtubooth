// Browser fingerprint: a stable-ish hash of device traits.
// Used only as a moderation hint (recognise a device that lost its cookie).
// Identical phone models often share a fingerprint, so it never identifies
// a person on its own.

async function sha256Hex(text) {
  if (window.crypto && crypto.subtle) {
    const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
  }
  // insecure contexts (plain http on a LAN IP) have no crypto.subtle: two FNV-1a passes
  let h1 = 0x811c9dc5, h2 = 0x01000193 ^ 0x5bd1e995;
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 0x01000193) >>> 0;
    h2 = Math.imul(h2 ^ c, 0x5bd1e995) >>> 0;
  }
  return (h1.toString(16).padStart(8, '0') + h2.toString(16).padStart(8, '0')).repeat(4);
}

function canvasTrait() {
  try {
    const c = document.createElement('canvas');
    c.width = 240;
    c.height = 60;
    const ctx = c.getContext('2d');
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
  } catch (_) {
    return '';
  }
}

function webglTrait() {
  try {
    const gl = document.createElement('canvas').getContext('webgl');
    if (!gl) return {};
    const ext = gl.getExtension('WEBGL_debug_renderer_info');
    return {
      gl_vendor: ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR),
      gl_renderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER),
      gl_max_texture: gl.getParameter(gl.MAX_TEXTURE_SIZE),
    };
  } catch (_) {
    return {};
  }
}

let cached = null;

export function getFingerprint() {
  // never rejects: consent requires a fingerprint
  if (!cached) cached = compute().catch(() => sha256Hex(`fallback|${navigator.userAgent}`).then((hash) => ({ hash, components: { ua: navigator.userAgent, fallback: true } })));
  return cached;
}

async function compute() {
  const s = window.screen || {};
  const components = {
    ua: navigator.userAgent,
    platform: navigator.platform || '',
    languages: (navigator.languages || [navigator.language]).join(','),
    timezone: (Intl.DateTimeFormat().resolvedOptions().timeZone) || '',
    screen: `${Math.max(s.width, s.height)}x${Math.min(s.width, s.height)}@${window.devicePixelRatio || 1}`,
    color_depth: s.colorDepth || 0,
    cores: navigator.hardwareConcurrency || 0,
    memory: navigator.deviceMemory || 0,
    touch: navigator.maxTouchPoints || 0,
    ...webglTrait(),
  };
  const canvasHash = await sha256Hex(canvasTrait());
  components.canvas = canvasHash.slice(0, 16);
  const stable = Object.keys(components).sort().map((k) => `${k}=${components[k]}`).join('|');
  return { hash: await sha256Hex(stable), components };
}
