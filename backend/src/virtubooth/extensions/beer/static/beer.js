// Beer Cam: one photo per drink, every photo is one frame of the timelapse.
//
// The 3:4 box on screen is exactly the saved photo: the video is cover-fitted
// into it and captureFrame() crops the same centred 3:4 region, so the
// outline drawn on top lines up with the stored 1080x1440 JPEG.

import {
  ApiError, api, boot, canvasToJpeg, captureFrame, confetti, debug, flash, h, isInAppBrowser,
  mountUserChip, openCamera, showNotice, toast, uploadJpeg, vibrate,
} from '/static/core/vb.js';
import { SHAPES, VESSELS, guideOverlay, vesselIcon } from './shapes.js';

const EXT = 'beer';
const OUT_W = 1080;
const OUT_H = 1440;
const JPEG_QUALITY = 0.9; // the server re-encodes anyway
const VESSEL_KEY = 'vb_beer_vessel';
const INAPP_KEY = 'vb_beer_inapp_dismissed';
const STATS_EVERY_MS = 30000;
const BANNED_TEXT = 'Dieses Gerät wurde für Uploads gesperrt. Sprich die Gastgeber an, wenn das ein Versehen ist.';

const CHEERS = [
  'Prost! 🍻',
  'Zum Wohl!',
  'Auf die Million!',
  'Der Zeitraffer dankt dir.',
  'Läuft bei dir!',
  'Ein Frame für die Ewigkeit.',
  'Hopfen und Malz, Gott erhalt’s!',
];

const fmt = new Intl.NumberFormat('de-DE');
const fmtShort = (() => {
  try { return new Intl.NumberFormat('de-DE', { notation: 'compact' }); } catch (_) { return fmt; }
})();
const $ = (id) => document.getElementById(id);

const els = {
  app: $('app'),
  frame: $('frame'),
  video: $('video'),
  loading: $('loading'),
  hint: $('hint'),
  shutter: $('shutter'),
  switchBtn: $('switch'),
  count: $('count'),
  goalLong: $('goal-long'),
  goalShort: $('goal-short'),
  upload: $('upload'),
  uploadText: $('upload-text'),
  uploadBar: $('upload-bar'),
  uploadActions: $('upload-actions'),
  retry: $('retry'),
  uploadHome: $('upload-home'),
  success: $('success'),
};

const state = {
  cam: null,
  vessel: 'bottle',
  total: null,
  goal: 1000000,
  busy: false,
  uploads: 0, // finished uploads, so stale stats polls can be ignored
  pending: null, // { blob, meta, canvas } of the shot being uploaded
  waitUntil: 0, // rate limited: no retry before this (ms)
  retryTimer: 0,
  successUrl: null,
};

const overlay = guideOverlay();

// ------------------------------------------------------------ storage

function storageGet(key) {
  try { return localStorage.getItem(key); } catch (_) { return null; }
}
function storageSet(key, value) {
  try { localStorage.setItem(key, value); } catch (_) { /* private mode */ }
}

// ------------------------------------------------------------------ UI

function setState(name) {
  els.app.dataset.state = name;
  els.loading.hidden = name !== 'loading';
  els.shutter.disabled = name !== 'camera' || !state.cam;
  els.switchBtn.disabled = name !== 'camera' || !state.cam;
  els.switchBtn.hidden = !!state.cam && !state.cam.canSwitch; // laptop/PC: one webcam
}

function setVessel(vessel, { save = true } = {}) {
  if (!SHAPES[vessel]) vessel = 'bottle';
  state.vessel = vessel;
  overlay.dataset.vessel = vessel;
  els.app.dataset.vessel = vessel;
  for (const btn of document.querySelectorAll('.beer-vessel')) {
    btn.setAttribute('aria-checked', String(btn.dataset.vessel === vessel));
  }
  els.hint.textContent = SHAPES[vessel].hint;
  if (save) storageSet(VESSEL_KEY, vessel);
}

function renderTotal() {
  if (state.total === null) return;
  const text = fmt.format(state.total);
  if (els.count.textContent !== text) {
    const counter = els.count.parentElement;
    counter.classList.remove('is-bumped');
    void counter.offsetWidth; // restart the animation
    counter.classList.add('is-bumped');
  }
  els.count.textContent = text;
  els.goalLong.textContent = `/ ${fmt.format(state.goal)}`;
  els.goalShort.textContent = `/ ${fmtShort.format(state.goal)}`; // "/ 1 Mio.": leaves the name chip room on phones
}

async function refreshStats() {
  const epoch = state.uploads;
  try {
    const stats = await api(`/api/x/${EXT}/stats`);
    // a poll that started before our last upload finished may be stale: skip it
    if (epoch !== state.uploads) return;
    state.total = stats.total;
    state.goal = stats.goal || state.goal;
    renderTotal();
  } catch (err) {
    debug('stats failed', err.message);
  }
}

function setMirrored() {
  els.video.classList.toggle('is-mirrored', !!(state.cam && state.cam.mirrored));
}

function reloadButton() {
  return h('button', { class: 'vb-btn vb-btn--primary vb-btn--big', type: 'button', onclick: () => location.reload() },
    'Neu laden');
}

function homeLink({ primary = false } = {}) {
  return h('a', {
    class: `vb-btn ${primary ? 'vb-btn--primary vb-btn--big' : 'vb-btn--ghost vb-btn--block beer-notice-home'}`,
    href: '/',
  }, 'Zur Startseite');
}

/** Every boot failure (identify, chip, camera setup) ends here: a way out, never an endless spinner. */
function fatal(err) {
  debug('main failed', err && (err.stack || err.message));
  console.warn(err);
  setState('off');
  const text = err instanceof ApiError ? err.message : 'Die Beer Cam konnte nicht starten.';
  showNotice('😵', 'Ups', text, reloadButton(), homeLink());
}

function showBanned() {
  setState('off');
  if (state.cam) state.cam.stop();
  if (document.querySelector('[data-testid="banned"]')) return;
  showNotice('🚫', 'Gesperrt', BANNED_TEXT, homeLink({ primary: true })).dataset.testid = 'banned';
}

/** A dialog or full-screen notice is up: page shortcuts must not act behind it. */
function dialogOpen() {
  return !!document.querySelector('.vb-scrim, .vb-notice');
}

function isTyping(target) {
  return !!(target && (target.isContentEditable || (target.closest && target.closest('input, textarea, select'))));
}

// -------------------------------------------------------------- camera

async function startCamera() {
  setState('loading');
  try {
    // ask for a 4:3 stream: phone sensors are 4:3, so the 3:4 crop keeps the whole field of view
    state.cam = await openCamera(els.video, { facing: 'environment', width: 1920, height: 1440 });
  } catch (err) {
    debug('camera failed', err.name, err.code, err.message);
    setState('off');
    showNotice('📷', 'Kamera geht nicht', err.message || 'Die Kamera konnte nicht gestartet werden.',
      reloadButton(), homeLink());
    return;
  }
  setMirrored();
  setState('camera');
  debug('camera', state.cam.facing, `${state.cam.width}x${state.cam.height}`);
}

async function switchCamera() {
  const cam = state.cam;
  if (!cam || state.busy || !cam.canSwitch) return;
  state.busy = true;
  setState('loading');
  try {
    await cam.switchFacing();
  } catch (err) {
    toast(err.message || 'Kamera wechseln hat nicht geklappt.', { type: 'error' });
    // go back to the camera that worked
    cam.facing = cam.facing === 'user' ? 'environment' : 'user';
    try {
      await cam.start();
    } catch (err2) {
      state.busy = false;
      setState('off');
      showNotice('📷', 'Kamera geht nicht', err2.message, reloadButton(), homeLink());
      return;
    }
  } finally {
    state.busy = false;
  }
  setMirrored();
  setState('camera');
}

// ------------------------------------------------------------- capture

async function shoot() {
  const cam = state.cam;
  if (!cam || state.busy || els.app.dataset.state !== 'camera') return;
  state.busy = true;
  flash();
  vibrate(40);
  try {
    if (!cam.live) await cam.start(); // iOS drops the stream in background tabs
    const canvas = captureFrame(els.video, OUT_W, OUT_H, { mirror: cam.mirrored });
    canvas.className = 'beer-still';
    canvas.dataset.testid = 'still';
    els.frame.insertBefore(canvas, overlay);
    const blob = await canvasToJpeg(canvas, JPEG_QUALITY);
    state.pending = { blob, canvas, meta: { vessel: state.vessel, facing: cam.facing } };
  } catch (err) {
    state.busy = false;
    discardShot();
    toast(err.message || 'Foto hat nicht geklappt.', { type: 'error' });
    return;
  }
  await sendShot();
}

function setProgress(fraction) {
  const pct = Math.round(Math.max(0, Math.min(1, fraction)) * 100);
  els.uploadBar.style.width = `${pct}%`;
  els.uploadText.textContent = pct < 100 ? `Wird geloggt… ${pct} %` : 'Fast geschafft…';
}

async function sendShot() {
  const shot = state.pending;
  if (!shot) return;
  state.busy = true;
  setState('uploading');
  els.upload.hidden = false;
  els.upload.classList.remove('is-error');
  els.uploadActions.hidden = true;
  els.retry.hidden = false;
  els.uploadHome.hidden = true;
  setProgress(0);
  let res;
  try {
    res = await uploadJpeg(EXT, shot.blob, { meta: shot.meta, onProgress: setProgress });
  } catch (err) {
    state.busy = false;
    await uploadFailed(err);
    return;
  }
  state.busy = false;
  showSuccess(res, shot);
}

/** Seconds the server asked us to wait (429 Retry-After), if it said. */
function retryAfter(err) {
  const raw = err.retryAfter ?? (err.data && err.data.retry_after);
  const seconds = Math.ceil(Number(raw));
  return Number.isFinite(seconds) && seconds > 0 ? seconds : 0;
}

async function uploadFailed(err) {
  debug('upload failed', err.status, err.code, err.message);
  if (err.code === 'banned') {
    discardShot();
    showBanned();
    return;
  }
  if (err.code === 'uploads_paused') {
    // the hosts paused this guest's uploads: no retry that can't work, the server's words, a way home
    state.pending = null; // nothing left to send: leaving loses nothing
    setState('error');
    els.upload.classList.add('is-error');
    els.uploadText.textContent = err.message || 'Uploads sind gerade pausiert.';
    els.retry.hidden = true;
    els.uploadHome.hidden = false;
    els.uploadActions.hidden = false;
    return;
  }
  if (err.code === 'needs_consent') {
    // the device lost its identity (cookies cleared): show the banner again, then retry
    try {
      const { banned } = await boot({ showBannedNotice: false });
      if (banned) {
        discardShot();
        showBanned();
        return;
      }
    } catch (_) { /* the retry button still works */ }
  }
  let text = err.message || 'Upload fehlgeschlagen.';
  const wait = err.code === 'rate_limited' ? retryAfter(err) : 0;
  if (err.code === 'rate_limited') {
    // the limit counts Beer Cam and Fotobox photos together
    text = wait
      ? `Langsam! Zu viele Fotos auf einmal. In ${wait} s nochmal.`
      : 'Langsam! Zu viele Fotos auf einmal. Warte kurz und versuch es nochmal.';
  }
  state.waitUntil = wait ? Date.now() + wait * 1000 : 0;
  setState('error');
  els.upload.classList.add('is-error');
  els.uploadText.textContent = text;
  els.uploadActions.hidden = false;
  renderRetry();
  toast(text, { type: 'error', ms: 5000 });
}

/** "⏳ 7 s" while the server wants us to wait, then "Nochmal". */
function renderRetry() {
  clearTimeout(state.retryTimer);
  const ms = els.app.dataset.state === 'error' ? state.waitUntil - Date.now() : 0;
  const left = Math.ceil(ms / 1000);
  els.retry.disabled = left > 0;
  els.retry.textContent = left > 0 ? `⏳ ${left} s` : 'Nochmal';
  if (left > 0) state.retryTimer = setTimeout(renderRetry, (ms % 1000) || 1000);
}

function discardShot() {
  if (state.pending && state.pending.canvas) state.pending.canvas.remove();
  for (const still of els.frame.querySelectorAll('.beer-still')) still.remove();
  state.pending = null;
  state.waitUntil = 0;
  clearTimeout(state.retryTimer);
  els.upload.hidden = true;
  els.uploadActions.hidden = true;
  setState(state.cam ? 'camera' : 'off');
}

// ------------------------------------------------------------- success

function showSuccess(res, shot) {
  const seq = res.beer_number ?? (res.photo && res.photo.seq);
  state.uploads += 1;
  state.total = res.total ?? Math.max(seq, state.total || 0);
  renderTotal();
  // The guest's beer is the newest one on the board, so its number is the board's
  // count: the same number the counter shows. (The photo's seq never shrinks, so it
  // runs ahead of the count once the hosts take beers down.)
  const number = state.total;

  if (state.successUrl) URL.revokeObjectURL(state.successUrl);
  state.successUrl = URL.createObjectURL(shot.blob);
  $('success-img').src = state.successUrl;
  $('success-caption').textContent = `Bier #${fmt.format(number)} · ${SHAPES[shot.meta.vessel].label}`;
  $('success-num').textContent = `#${fmt.format(number)}`;
  $('success-total').textContent = fmt.format(state.total);
  $('success-goal').textContent = `/ ${fmt.format(state.goal)}`;
  const togo = state.goal - state.total;
  $('success-togo').textContent = togo > 0
    ? `Noch ${fmt.format(togo)} bis zur Million – weiter so!`
    : 'Die Million ist voll! Ihr seid Legenden. 🏆';
  const milestone = number % 100 === 0;
  $('success-cheer').textContent = milestone
    ? `Jubiläumsbier! 🎉 #${fmt.format(number)}`
    : CHEERS[Math.floor(Math.random() * CHEERS.length)];

  state.pending = null;
  els.upload.hidden = true;
  setState('success');
  els.success.hidden = false;
  $('again').focus({ preventScroll: true });
  confetti(milestone ? { count: 260, duration: 3200 } : undefined);
  vibrate([30, 60, 30]);
}

async function again() {
  els.success.hidden = true;
  for (const still of els.frame.querySelectorAll('.beer-still')) still.remove();
  if (state.successUrl) {
    URL.revokeObjectURL(state.successUrl);
    state.successUrl = null;
  }
  if (state.cam && !state.cam.live) {
    setState('loading');
    try {
      await state.cam.start();
    } catch (err) {
      setState('off');
      showNotice('📷', 'Kamera geht nicht', err.message, reloadButton(), homeLink());
      return;
    }
  }
  setState(state.cam ? 'camera' : 'off');
  // keyboard: the focused "Noch eins!" button is gone; space/enter go to the shutter now
  if (!els.shutter.disabled) els.shutter.focus({ preventScroll: true });
  refreshStats();
}

// ---------------------------------------------------------------- setup

function setupInAppHint() {
  if (!isInAppBrowser() || storageGet(INAPP_KEY)) return;
  const el = $('inapp');
  el.hidden = false;
  $('inapp-close').addEventListener('click', () => {
    el.hidden = true;
    storageSet(INAPP_KEY, '1');
  });
}

function wireUi() {
  els.frame.append(overlay);
  for (const btn of document.querySelectorAll('.beer-vessel')) {
    btn.prepend(vesselIcon(btn.dataset.vessel));
    btn.addEventListener('click', () => setVessel(btn.dataset.vessel));
  }
  const saved = storageGet(VESSEL_KEY);
  setVessel(VESSELS.includes(saved) ? saved : 'bottle', { save: false });

  els.shutter.addEventListener('click', shoot);
  els.switchBtn.addEventListener('click', switchCamera);
  $('retry').addEventListener('click', () => { if (!state.busy) sendShot(); });
  $('discard').addEventListener('click', () => { if (!state.busy) discardShot(); });
  $('again').addEventListener('click', again);
  // hardware/keyboard shutter: space or enter while the camera is up. Never behind a dialog.
  document.addEventListener('keydown', (e) => {
    if (e.altKey || e.ctrlKey || e.metaKey || e.defaultPrevented) return;
    if (dialogOpen() || isTyping(e.target)) return;
    if ((e.key === ' ' || e.key === 'Enter') && els.app.dataset.state === 'camera'
        && document.activeElement === document.body) {
      e.preventDefault();
      shoot();
    } else if (e.key === 'Escape' && els.app.dataset.state === 'success') {
      again();
    }
  });
  setInterval(() => {
    if (document.visibilityState === 'visible') refreshStats();
  }, STATS_EVERY_MS);
  // a beer that is still uploading or failed to upload is lost when the page goes
  window.addEventListener('beforeunload', (e) => {
    if (!state.pending) return;
    e.preventDefault();
    e.returnValue = '';
  });
}

async function main() {
  wireUi();
  setupInAppHint();
  const { banned } = await boot({ showBannedNotice: false });
  mountUserChip($('user-chip'));
  refreshStats();
  if (banned) {
    showBanned();
    return;
  }
  await startCamera();
}

main().catch(fatal);
