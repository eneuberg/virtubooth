// virtubooth core SDK for extension pages.
//
//   import { boot, fatal, uploadJpeg, toast, confetti } from '/static/core/vb.js';
//   async function main() {
//     const { user } = await boot();        // join dialog, device identity
//     const res = await uploadJpeg('beer', blob, { meta: { vessel: 'bottle' } });
//   }
//   main().catch(fatal);                    // error notice with a "Neu laden" button
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

// The log sits at the top and lets taps through (pointer-events: none), so the
// page stays usable; the 🐞 tab on the left edge folds it away.
let debugEl = null;
let debugLog = null;
function debugPanel() {
  const folded = (() => { try { return sessionStorage.getItem('vb_debug_folded') === '1'; } catch (_) { return false; } })();
  debugLog = h('pre', { class: 'vb-debug-log' });
  const toggle = h('button', {
    class: 'vb-debug-toggle', type: 'button', 'data-testid': 'debug-toggle',
    'aria-label': 'Debug-Log ein- oder ausblenden', 'aria-expanded': String(!folded),
  }, '🐞');
  debugEl = h('div', { class: 'vb-debug', 'data-testid': 'debug' }, debugLog, toggle);
  debugEl.classList.toggle('vb-debug--folded', folded);
  toggle.addEventListener('click', () => {
    const nowFolded = debugEl.classList.toggle('vb-debug--folded');
    toggle.setAttribute('aria-expanded', String(!nowFolded));
    try { sessionStorage.setItem('vb_debug_folded', nowFolded ? '1' : ''); } catch (_) { /* private mode */ }
    debugLog.scrollTop = debugLog.scrollHeight;
  });
  document.body.append(debugEl);
}

export function debug(...args) {
  if (!debugOn) return;
  if (!debugEl) debugPanel();
  const line = args.map((a) => (typeof a === 'string' ? a : JSON.stringify(a))).join(' ');
  debugLog.textContent += `${new Date().toISOString().slice(11, 19)} ${line}\n`;
  debugLog.scrollTop = debugLog.scrollHeight;
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
    // seconds the server asked us to wait (429), else null
    this.retryAfter = null;
    // code 'network': true when the device says it is offline. A request a content
    // blocker dropped looks exactly like a dead network otherwise, so false means "unknown".
    this.offline = false;
  }
}

function errorFromResponse(status, data, retryHeader, fallback) {
  const err = new ApiError(status, (data && data.error) || `http_${status}`,
    (data && data.message) || fallback, data);
  const wait = parseInt(retryHeader || '', 10);
  if ((status === 429 || status === 503) && wait > 0) {
    err.retryAfter = wait;
    const when = wait < 90 ? `${wait} s` : `${Math.ceil(wait / 60)} min`;
    err.message = `${err.message.replace(/\.\s*$/, '')} (in ${when} nochmal).`;
  }
  if (err.code === 'scan_qr') handleNoAccess();
  return err;
}

function unreachable(offlineText, unknownText = offlineText) {
  const offline = navigator.onLine === false;
  const err = new ApiError(0, 'network', offline ? offlineText : unknownText);
  err.offline = offline;
  return err;
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
    // offline, or dropped by a content blocker: the browser doesn't tell which
    throw unreachable('Keine Verbindung. Bist du noch im Netz?',
      'Keine Antwort vom Server. Prüf dein Netz und versuch es nochmal.');
  }
  let data = null;
  try { data = await res.json(); } catch (_) { /* empty or non-JSON body */ }
  if (!res.ok) {
    throw errorFromResponse(res.status, data, res.headers.get('Retry-After'), 'Da ist etwas schiefgelaufen.');
  }
  return data;
}

function handleNoAccess() {
  // the server renders the "scan the QR code" page for any page without access
  location.reload();
}

// ---------------------------------------------------------------- dialogs

// A dialog is a .vb-sheet (role="dialog") in a .vb-scrim. With the split layout
// (.vb-sheet--split > form.vb-sheet-form > .vb-sheet-body + .vb-sheet-foot) the
// text scrolls and the buttons in the footer stay on screen, however short it is.

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), '
  + 'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
const openDialogs = [];

/** True while a dialog (.vb-scrim) is open. Ignore page keyboard shortcuts then. */
export function sheetOpen() {
  return !!document.querySelector('.vb-scrim');
}

function tabbable(root) {
  return [...root.querySelectorAll(FOCUSABLE)].filter((el) => el.getClientRects().length > 0);
}

function onDialogKey(event) {
  const top = openDialogs[openDialogs.length - 1];
  if (!top) return;
  if (event.key === 'Escape' || event.key === 'Esc') {
    event.preventDefault();
    event.stopPropagation();
    if (top.dismiss) top.dismiss();
    return;
  }
  if (event.key !== 'Tab') return;
  // move focus ourselves: browsers differ in what Tab reaches (Safari skips buttons)
  event.preventDefault();
  const items = tabbable(top.dialog);
  if (!items.length) {
    top.dialog.focus();
    return;
  }
  const i = items.indexOf(document.activeElement);
  const next = event.shiftKey
    ? (i <= 0 ? items.length - 1 : i - 1)
    : (i < 0 || i === items.length - 1 ? 0 : i + 1);
  items[next].focus();
}

function onDialogFocus(event) {
  const top = openDialogs[openDialogs.length - 1];
  if (top && !top.dialog.contains(event.target)) top.dialog.focus();
}

/**
 * Make an appended scrim + dialog behave: focus moves in (`focus`, else the
 * dialog itself), Tab and Shift+Tab stay inside, Escape and a tap on the scrim
 * call `dismiss` (leave it out for a dialog that can't be dismissed). Returns
 * close(): removes the scrim and gives focus back to where it was.
 */
function holdFocus(backdrop, dialog, { dismiss, focus } = {}) {
  const opener = document.activeElement;
  const entry = { dialog, dismiss };
  openDialogs.push(entry);
  if (openDialogs.length === 1) {
    window.addEventListener('keydown', onDialogKey, true);
    document.addEventListener('focusin', onDialogFocus, true);
  }
  if (!dialog.hasAttribute('tabindex')) dialog.setAttribute('tabindex', '-1');
  if (dismiss) {
    // a tap that starts in the sheet and ends on the scrim (selecting text) is not a dismiss
    let fromScrim = false;
    backdrop.addEventListener('pointerdown', (e) => { fromScrim = e.target === backdrop; });
    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop && fromScrim) dismiss();
      fromScrim = false;
    });
  }
  const unwatch = watchOverflow(dialog);
  (focus || dialog).focus();
  let closed = false;
  return function close() {
    if (closed) return;
    closed = true;
    unwatch();
    const i = openDialogs.indexOf(entry);
    if (i >= 0) openDialogs.splice(i, 1);
    if (!openDialogs.length) {
      window.removeEventListener('keydown', onDialogKey, true);
      document.removeEventListener('focusin', onDialogFocus, true);
    }
    backdrop.remove();
    if (opener && opener !== document.body && opener.isConnected && typeof opener.focus === 'function') {
      opener.focus();
    }
  };
}

/** .vb-sheet--more while the text above the footer has more to scroll to. */
function watchOverflow(sheet) {
  const body = sheet.querySelector('.vb-sheet-body');
  if (!body) return () => {};
  const update = () => {
    sheet.classList.toggle('vb-sheet--more', body.scrollHeight - body.clientHeight - body.scrollTop > 4);
  };
  body.addEventListener('scroll', update, { passive: true });
  let observer = null;
  if (window.ResizeObserver) {
    observer = new ResizeObserver(update);
    observer.observe(body);
  } else {
    window.addEventListener('resize', update);
  }
  update();
  return () => {
    body.removeEventListener('scroll', update);
    if (observer) observer.disconnect();
    else window.removeEventListener('resize', update);
  };
}

/** Pasting a profile link into a handle field keeps just the handle (maxlength would cut the link). */
function takeProfileLinks(input) {
  input.addEventListener('paste', (event) => {
    const text = (event.clipboardData && event.clipboardData.getData('text')) || '';
    const m = /instagram\.com\/([A-Za-z0-9._]+)/i.exec(text);
    if (!m) return;
    event.preventDefault();
    input.value = `@${m[1]}`.slice(0, input.maxLength > 0 ? input.maxLength : undefined);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
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

const shortName = (name) => String(name || '').replace(/ #\d+$/, '');

/**
 * Call once per page before anything else. Shows the join dialog to unknown
 * devices and waits until it is accepted.
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
      autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false', placeholder: '@deinname', maxlength: '31',
    });
    takeProfileLinks(input);
    const errorEl = h('div', { class: 'vb-field-error', role: 'alert' });
    const accept = h('button', { class: 'vb-btn vb-btn--primary vb-btn--big', type: 'submit' }, consent.accept_label);
    const form = h('form', { class: 'vb-sheet-form' },
      h('div', { class: 'vb-sheet-body' },
        h('h2', { id: 'vb-join-title' }, consent.title),
        ...consent.paragraphs.map((p) => h('p', { class: 'vb-muted' }, p)),
        h('label', { class: 'vb-label', for: 'vb-join-insta' }, consent.instagram_prompt),
        input,
        errorEl,
      ),
      h('div', { class: 'vb-sheet-foot' }, h('div', { class: 'vb-actions' }, accept)),
    );
    const sheet = h('div', {
      class: 'vb-sheet vb-sheet--split', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'vb-join-title', tabindex: '-1',
    }, form);
    const backdrop = h('div', { class: 'vb-scrim', 'data-testid': 'join' }, sheet);
    document.body.append(backdrop);
    // no dismiss: declining means not using the site. Focus the dialog, not the
    // field: on a phone that would pop up the keyboard over the text.
    const close = holdFocus(backdrop, sheet);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (accept.disabled) return;
      accept.disabled = true;
      errorEl.textContent = '';
      try {
        const res = await api('/api/join', {
          method: 'POST',
          json: { accept: true, version: consent.version, instagram: input.value.trim() || null, fp },
        });
        close();
        if (res.already_joined) {
          // another tab joined first: same guest, say who
          const insta = res.user.instagram ? ` (@${res.user.instagram})` : '';
          const hint = res.instagram_kept ? ' Tipp auf deinen Namen, um Instagram zu ändern.' : '';
          toast(`Du bist schon dabei als „${shortName(res.user.name)}“${insta}.${hint}`, { ms: 6000 });
        } else if (res.state === 'ok') {
          confetti();
        }
        resolve(res);
      } catch (err) {
        errorEl.textContent = err.message;
        errorEl.scrollIntoView({ block: 'nearest' });
        accept.disabled = false;
        if (err.code === 'invalid_instagram') input.focus();
        if (err.code === 'consent_outdated') setTimeout(() => location.reload(), 1500);
      }
    });
  });
}

/** Update the guest's Instagram handle (null clears it). */
export async function setInstagram(handle) {
  const res = await api('/api/me', { method: 'PATCH', json: { instagram: handle || null } });
  setUser({ ...currentUser, ...res.user });
  return res.user;
}

/**
 * A small chip for the guest: their Instagram handle once set (that's what they
 * care about), else their pseudonym. Tap to edit the handle. Long text ellipsizes.
 */
export function mountUserChip(container) {
  const label = h('span', { class: 'vb-chip-text' });
  const chip = h('button', { class: 'vb-chip', type: 'button', 'data-testid': 'user-chip' },
    h('span', { class: 'vb-chip-icon', 'aria-hidden': 'true' }, '🙂'), ' ', label);
  const render = (user) => {
    chip.hidden = !user;
    if (!user) return;
    label.textContent = user.instagram ? `@${user.instagram}` : `${shortName(user.name)} · Insta?`;
    chip.title = `${user.name}${user.instagram ? ` · @${user.instagram}` : ''}`;
  };
  render(currentUser);
  onUserChange(render);
  chip.addEventListener('click', () => editInstagram());
  container.append(chip);
  return chip;
}

export function editInstagram() {
  const user = currentUser;
  if (!user || sheetOpen()) return;
  const input = h('input', {
    class: 'vb-input', id: 'vb-insta-edit', type: 'text', autocomplete: 'off', autocapitalize: 'none',
    spellcheck: 'false', placeholder: '@deinname', maxlength: '31', value: user.instagram ? `@${user.instagram}` : '',
  });
  takeProfileLinks(input);
  const errorEl = h('div', { class: 'vb-field-error', role: 'alert' });
  const save = h('button', { class: 'vb-btn vb-btn--primary vb-btn--block', type: 'submit' }, 'Speichern');
  const cancel = h('button', { class: 'vb-btn vb-btn--ghost vb-btn--block', type: 'button' }, 'Abbrechen');
  const form = h('form', { class: 'vb-sheet-form' },
    h('div', { class: 'vb-sheet-body' },
      h('h2', { id: 'vb-insta-title' }, 'Dein Instagram'),
      h('p', { class: 'vb-muted' }, `Du bist hier „${user.name}“. Wenn du magst, markieren wir dich auf Instagram.`),
      h('label', { class: 'vb-label', for: 'vb-insta-edit' }, 'Instagram-Name (freiwillig)'),
      input,
      errorEl,
    ),
    h('div', { class: 'vb-sheet-foot' }, h('div', { class: 'vb-actions' }, save, cancel)),
  );
  const sheet = h('div', {
    class: 'vb-sheet vb-sheet--split', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'vb-insta-title', tabindex: '-1',
  }, form);
  const backdrop = h('div', { class: 'vb-scrim', 'data-testid': 'handle-edit' }, sheet);
  document.body.append(backdrop);
  const close = holdFocus(backdrop, sheet, { dismiss: () => close(), focus: input });
  cancel.addEventListener('click', () => close());
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (save.disabled) return;
    save.disabled = true;
    try {
      await setInstagram(input.value.trim());
      close();
      toast('Gespeichert ✨', { type: 'success' });
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.scrollIntoView({ block: 'nearest' });
      input.focus();
    } finally {
      save.disabled = false;
    }
  });
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
        reject(errorFromResponse(xhr.status, data, xhr.getResponseHeader('Retry-After'), 'Upload fehlgeschlagen.'));
      }
    });
    // uploads go to /api/x/<ext>/upload, which blockers leave alone: a failure here is the network
    xhr.addEventListener('error', () => reject(unreachable('Keine Verbindung. Nochmal versuchen?')));
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

/**
 * The end of every page's main(): `main().catch(fatal)`. Shows a full-screen
 * notice with a "Neu laden" button instead of leaving a half-built page.
 * ApiError and CameraError messages are German and shown as they are; anything
 * else gets a generic text (the details go to the ?debug=1 log). `actions` are
 * extra buttons/links under "Neu laden". Returns the notice element.
 */
export function fatal(err, { title, actions = [] } = {}) {
  debug('fatal', String((err && (err.stack || err.message)) || err));
  if (err && err.code === 'scan_qr') return null; // api() already reloads to the "scan the QR code" page
  const shown = document.querySelector('.vb-notice[data-testid="fatal"]');
  if (shown) return shown;
  let emoji = '😵';
  let head = 'Ups';
  let text = 'Da ist etwas schiefgelaufen. Lade die Seite neu.';
  if (err && err.code === 'network') {
    emoji = '📡';
    if (err.offline) {
      head = 'Keine Verbindung';
      text = 'Dein Handy ist gerade offline. Sobald du wieder Netz hast, lade die Seite neu.';
    } else {
      // offline or blocked: the browser doesn't say which, so name both
      head = 'Keine Antwort';
      text = 'Die Seite erreicht den Server gerade nicht. Prüf dein Netz, und falls du einen '
        + 'Werbe- oder Tracking-Blocker nutzt, schalte ihn für diese Seite aus. Dann lade neu.';
    }
  } else if (err && (err.name === 'ApiError' || err.name === 'CameraError') && err.message) {
    text = err.message;
  }
  const reload = h('button', {
    class: 'vb-btn vb-btn--primary vb-btn--big', type: 'button', 'data-testid': 'reload', onclick: () => location.reload(),
  }, 'Neu laden');
  const el = showNotice(emoji, title || head, text, reload, ...actions);
  el.dataset.testid = 'fatal';
  reload.focus();
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
