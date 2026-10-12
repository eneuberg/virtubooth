// virtubooth core SDK for extension pages.
//
//   import { boot, uploadJpeg, toast, confetti } from '/static/core/vb.js';
//   const { user } = await boot();          // consent banner, device identity
//   const res = await uploadJpeg('beer', blob, { meta: { vessel: 'bottle' } });
//
// Rules for pages (CSP): no inline <script>/<style>, no style="" attributes,
// no on*="" handlers. Build DOM with h() or textContent, never innerHTML with data.
//
// Keep static imports to what the page can't run without, and keep file names
// neutral: content blockers drop URLs that look like tracking ("fingerprint",
// "analytics", ...), and one failed static import stops every module on the page.

export { openCamera, captureFrame, CameraError, cameraErrorMessage, isIOS, isInAppBrowser } from './camera.js';

// tells loader.js that the page's modules started
window.__vbReady = true;

const UID_KEY = 'vb_uid';

/**
 * Device traits for moderation (see device.js). Loaded on demand so a blocked
 * or failing optional module can never stop the page; falls back to a coarse
 * hash of what every browser exposes.
 */
export async function getFingerprint() {
  try {
    const mod = await import('./device.js');
    return await mod.getFingerprint();
  } catch (err) {
    debug('device traits unavailable', String(err));
    const s = window.screen || {};
    const ua = navigator.userAgent;
    const basic = [ua, navigator.language, `${s.width}x${s.height}@${window.devicePixelRatio || 1}`,
      Intl.DateTimeFormat().resolvedOptions().timeZone || ''].join('|');
    return { hash: await sha256Hex(basic), components: { ua, fallback: true } };
  }
}

async function sha256Hex(text) {
  if (window.crypto && crypto.subtle) {
    const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
  }
  let h1 = 0x811c9dc5, h2 = 0x5bd1e995;
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 0x01000193) >>> 0;
    h2 = Math.imul(h2 ^ c, 0x5bd1e995) >>> 0;
  }
  return (h1.toString(16).padStart(8, '0') + h2.toString(16).padStart(8, '0')).repeat(4);
}

// ------------------------------------------------------------------ DOM

/** h('button', { class: 'vb-btn', onclick: fn }, 'Text', childNode) */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith('on') && typeof value === 'function') {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === 'class') {
      el.className = value;
    } else if (key === 'dataset') {
      Object.assign(el.dataset, value);
    } else if (value === true) {
      el.setAttribute(key, '');
    } else {
      el.setAttribute(key, String(value));
    }
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

function storageGet(key) {
  try { return localStorage.getItem(key); } catch (_) { return null; }
}
function storageSet(key, value) {
  try { localStorage.setItem(key, value); } catch (_) { /* private mode */ }
}

// ------------------------------------------------------------------ debug

const debugOn = (() => {
  try {
    if (new URLSearchParams(location.search).has('debug')) sessionStorage.setItem('vb_debug', '1');
    return sessionStorage.getItem('vb_debug') === '1';
  } catch (_) {
    return false;
  }
})();

let debugEl = null;
export function debug(...args) {
  if (!debugOn) return;
  if (!debugEl) {
    debugEl = h('pre', { class: 'vb-debug' });
    document.body.append(debugEl);
  }
  const line = args.map((a) => (typeof a === 'string' ? a : JSON.stringify(a))).join(' ');
  debugEl.textContent += `${new Date().toISOString().slice(11, 19)} ${line}\n`;
  debugEl.scrollTop = debugEl.scrollHeight;
}

if (debugOn) {
  window.addEventListener('error', (e) => debug('ERROR', e.message, `${e.filename}:${e.lineno}`));
  window.addEventListener('unhandledrejection', (e) => debug('REJECTION', String(e.reason && (e.reason.stack || e.reason))));
  debug('debug on', navigator.userAgent);
}

// -------------------------------------------------------------------- api

export class ApiError extends Error {
  constructor(status, code, message, data) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.data = data;
  }
}

/** fetch JSON from our API. Throws ApiError with a German message. */
export async function api(path, { method = 'GET', json, body, headers = {}, signal } = {}) {
  const init = { method, headers: { Accept: 'application/json', ...headers }, credentials: 'same-origin', signal };
  if (json !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(json);
  } else if (body !== undefined) {
    init.body = body;
  }
  let res;
  try {
    res = await fetch(path, init);
  } catch (err) {
    throw new ApiError(0, 'network', 'Keine Verbindung. Bist du noch im Netz?');
  }
  let data = null;
  try { data = await res.json(); } catch (_) { /* empty or non-JSON body */ }
  if (!res.ok) {
    const err = new ApiError(res.status, (data && data.error) || `http_${res.status}`,
      (data && data.message) || 'Da ist etwas schiefgelaufen.', data);
    if (err.code === 'scan_qr') handleNoAccess();
    throw err;
  }
  return data;
}

function handleNoAccess() {
  // the server renders the "scan the QR code" page for any page without access
  location.reload();
}

// ------------------------------------------------------- identity/consent

let currentUser = null;
const userListeners = new Set();

export function getUser() { return currentUser; }
export function onUserChange(fn) { userListeners.add(fn); return () => userListeners.delete(fn); }
function setUser(user) {
  currentUser = user;
  for (const fn of userListeners) fn(user);
}

/**
 * Call once per page before anything else. Shows the consent banner to
 * unknown devices and waits until it is accepted.
 * Resolves { user, banned }. A banned device sees a notice; uploads will fail.
 */
export async function boot({ showBannedNotice = true } = {}) {
  const fp = await getFingerprint();
  debug('fp', fp && fp.hash.slice(0, 12));
  let res = await api('/api/identify', { method: 'POST', json: { fp, uid: storageGet(UID_KEY) } });
  if (res.state === 'needs_consent') {
    res = await askConsent(res.consent, fp);
  }
  if (res.uid_token) storageSet(UID_KEY, res.uid_token);
  setUser(res.user);
  const banned = res.state === 'banned';
  if (banned && showBannedNotice) {
    showNotice('🚫', 'Gesperrt', 'Dieses Gerät wurde für Uploads gesperrt. Sprich die Gastgeber an, wenn das ein Versehen ist.');
  }
  return { user: res.user, banned };
}

function askConsent(consent, fp) {
  return new Promise((resolve) => {
    const input = h('input', {
      class: 'vb-input', id: 'vb-join-insta', type: 'text', inputmode: 'text',
      autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false', placeholder: '@deinname', maxlength: '60',
    });
    const errorEl = h('div', { class: 'vb-field-error', role: 'alert' });
    const accept = h('button', { class: 'vb-btn vb-btn--primary vb-btn--big', type: 'submit' }, consent.accept_label);
    const form = h('form', { class: 'vb-sheet', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'vb-join-title' },
      h('h2', { id: 'vb-join-title' }, consent.title),
      ...consent.paragraphs.map((p) => h('p', { class: 'vb-muted' }, p)),
      h('label', { class: 'vb-label', for: 'vb-join-insta' }, consent.instagram_prompt),
      input,
      errorEl,
      h('div', { class: 'vb-actions' }, accept),
    );
    const backdrop = h('div', { class: 'vb-scrim', 'data-testid': 'join' }, form);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      accept.disabled = true;
      errorEl.textContent = '';
      try {
        const res = await api('/api/join', {
          method: 'POST',
          json: { accept: true, version: consent.version, instagram: input.value.trim() || null, fp },
        });
        backdrop.remove();
        if (res.state === 'ok') confetti();
        resolve(res);
      } catch (err) {
        errorEl.textContent = err.message;
        accept.disabled = false;
        if (err.code === 'consent_outdated') setTimeout(() => location.reload(), 1500);
      }
    });
    document.body.append(backdrop);
  });
}

/** Update the guest's Instagram handle (null clears it). */
export async function setInstagram(handle) {
  const res = await api('/api/me', { method: 'PATCH', json: { instagram: handle || null } });
  setUser({ ...currentUser, ...res.user });
  return res.user;
}

/** A small chip showing the guest's pseudonym + Instagram; tap to edit the handle. */
export function mountUserChip(container) {
  const chip = h('button', { class: 'vb-chip', type: 'button', 'data-testid': 'user-chip' });
  const render = (user) => {
    chip.textContent = user
      ? `🙂 ${user.name.replace(/ #\d+$/, '')}${user.instagram ? ` · @${user.instagram}` : ' · Insta?'}`
      : '';
    chip.hidden = !user;
  };
  render(currentUser);
  onUserChange(render);
  chip.addEventListener('click', () => editInstagram());
  container.append(chip);
  return chip;
}

export function editInstagram() {
  const user = currentUser;
  if (!user) return;
  const input = h('input', {
    class: 'vb-input', id: 'vb-insta-edit', type: 'text', autocomplete: 'off', autocapitalize: 'none',
    spellcheck: 'false', placeholder: '@deinname', maxlength: '60', value: user.instagram ? `@${user.instagram}` : '',
  });
  const errorEl = h('div', { class: 'vb-field-error', role: 'alert' });
  const close = () => backdrop.remove();
  const form = h('form', { class: 'vb-sheet', role: 'dialog', 'aria-modal': 'true' },
    h('h2', {}, 'Dein Instagram'),
    h('p', { class: 'vb-muted' }, `Du bist hier „${user.name}“. Wenn du magst, markieren wir dich auf Instagram.`),
    h('label', { class: 'vb-label', for: 'vb-insta-edit' }, 'Instagram-Name (freiwillig)'),
    input,
    errorEl,
    h('div', { class: 'vb-actions' },
      h('button', { class: 'vb-btn vb-btn--primary vb-btn--block', type: 'submit' }, 'Speichern'),
      h('button', { class: 'vb-btn vb-btn--ghost vb-btn--block', type: 'button', onclick: close }, 'Abbrechen'),
    ),
  );
  const backdrop = h('div', { class: 'vb-scrim' }, form);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      await setInstagram(input.value.trim());
      close();
      toast('Gespeichert ✨', { type: 'success' });
    } catch (err) {
      errorEl.textContent = err.message;
    }
  });
  document.body.append(backdrop);
  input.focus();
}

// ---------------------------------------------------------------- uploads

/**
 * Upload a JPEG blob to the extension's upload endpoint.
 * onProgress(fraction 0..1). Resolves the server JSON ({ photo, ...extra }).
 */
export function uploadJpeg(extId, blob, { meta = {}, onProgress } = {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `/api/x/${encodeURIComponent(extId)}/upload`);
    xhr.setRequestHeader('Content-Type', 'image/jpeg');
    xhr.setRequestHeader('Accept', 'application/json');
    if (meta && Object.keys(meta).length) {
      xhr.setRequestHeader('X-VB-Meta', encodeURIComponent(JSON.stringify(meta)));
    }
    xhr.responseType = 'json';
    xhr.timeout = 60000;
    if (onProgress) {
      xhr.upload.addEventListener('progress', (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); });
    }
    xhr.addEventListener('load', () => {
      const data = xhr.response;
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress && onProgress(1);
        resolve(data);
      } else {
        const err = new ApiError(xhr.status, (data && data.error) || `http_${xhr.status}`,
          (data && data.message) || 'Upload fehlgeschlagen.', data);
        if (err.code === 'scan_qr') handleNoAccess();
        reject(err);
      }
    });
    xhr.addEventListener('error', () => reject(new ApiError(0, 'network', 'Keine Verbindung. Nochmal versuchen?')));
    xhr.addEventListener('timeout', () => reject(new ApiError(0, 'timeout', 'Der Upload hat zu lange gedauert. Nochmal versuchen?')));
    xhr.send(blob);
  });
}

/** canvas -> JPEG Blob */
export function canvasToJpeg(canvas, quality = 0.88) {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('toBlob failed'))), 'image/jpeg', quality);
  });
}

/**
 * Save an image on the guest's phone. iOS: share sheet ("Bild sichern").
 * Elsewhere: download. Must be called from a tap handler.
 * Returns 'shared' | 'downloaded' | 'cancelled'.
 */
export async function saveImage(blob, filename = 'party.jpg', { preferShare } = {}) {
  const file = new File([blob], filename, { type: blob.type || 'image/jpeg' });
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const share = preferShare ?? ios;
  if (share && navigator.canShare && navigator.canShare({ files: [file] })) {
    try {
      await navigator.share({ files: [file] });
      return 'shared';
    } catch (err) {
      if (err && err.name === 'AbortError') return 'cancelled';
      // fall through to download
    }
  }
  const url = URL.createObjectURL(blob);
  const a = h('a', { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
  return 'downloaded';
}

// ------------------------------------------------------------- feedback

let toastHost = null;
/** toast('Text', { type: 'success' | 'error' | 'info', ms }) */
export function toast(message, { type = 'info', ms = 2800 } = {}) {
  if (!toastHost) {
    toastHost = h('div', { class: 'vb-toast-host', 'aria-live': 'polite' });
    document.body.append(toastHost);
  }
  const el = h('div', { class: `vb-toast vb-toast--${type}`, role: type === 'error' ? 'alert' : 'status' }, message);
  toastHost.append(el);
  setTimeout(() => el.remove(), ms);
  return el;
}

/** Fullscreen notice (errors, banned, wrong browser). Returns the element. */
export function showNotice(emoji, title, text, ...actions) {
  const el = h('div', { class: 'vb-notice', role: 'alert' },
    h('div', { class: 'vb-page' },
      h('div', { class: 'vb-notice-emoji' }, emoji),
      h('h2', {}, title),
      h('p', { class: 'vb-muted' }, text),
      ...actions,
    ),
  );
  document.body.append(el);
  return el;
}

export function flash() {
  const el = h('div', { class: 'vb-flash' });
  document.body.append(el);
  setTimeout(() => el.remove(), 400);
}

export function vibrate(pattern = 30) {
  try { navigator.vibrate && navigator.vibrate(pattern); } catch (_) { /* unsupported */ }
}

/** Party confetti burst. */
export function confetti({ count = 140, duration = 2200 } = {}) {
  if (window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const canvas = h('canvas', { class: 'vb-confetti' });
  document.body.append(canvas);
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = innerWidth * dpr;
  canvas.height = innerHeight * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const colors = ['#ff3d8b', '#ff8a00', '#ffd23f', '#2de2e6', '#7b2ff7', '#3ddc84'];
  const parts = Array.from({ length: count }, () => ({
    x: innerWidth / 2 + (Math.random() - 0.5) * innerWidth * 0.3,
    y: innerHeight * 0.35,
    vx: (Math.random() - 0.5) * 14,
    vy: -Math.random() * 14 - 4,
    size: 6 + Math.random() * 7,
    rot: Math.random() * Math.PI,
    vr: (Math.random() - 0.5) * 0.4,
    color: colors[(Math.random() * colors.length) | 0],
  }));
  const start = performance.now();
  const frame = (now) => {
    const t = now - start;
    ctx.clearRect(0, 0, innerWidth, innerHeight);
    for (const p of parts) {
      p.vy += 0.38;
      p.vx *= 0.99;
      p.x += p.vx;
      p.y += p.vy;
      p.rot += p.vr;
      ctx.save();
      ctx.globalAlpha = Math.max(0, 1 - t / duration);
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rot);
      ctx.fillStyle = p.color;
      ctx.fillRect(-p.size / 2, -p.size / 4, p.size, p.size / 2);
      ctx.restore();
    }
    if (t < duration) requestAnimationFrame(frame);
    else canvas.remove();
  };
  requestAnimationFrame(frame);
}
