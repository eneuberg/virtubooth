// Beer Cam: one photo per drink, every photo is one frame of the timelapse.
//
// The 3:4 box on screen is exactly the saved photo: the video is cover-fitted
// into it and captureFrame() crops the same centred 3:4 region, so the
// outline drawn on top lines up with the stored 1080x1440 JPEG.

import {
  api, boot, canvasToJpeg, captureFrame, confetti, debug, flash, h, isInAppBrowser,
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
  goal: $('goal'),
  upload: $('upload'),
  uploadText: $('upload-text'),
  uploadBar: $('upload-bar'),
  uploadActions: $('upload-actions'),
  success: $('success'),
};

const state = {
  cam: null,
  vessel: 'bottle',
  total: null,
  goal: 1000000,
  busy: false,
  pending: null, // { blob, meta, canvas } of the shot being uploaded
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
  els.shutter.disabled = name !== 'camera' || !state.cam;
  els.switchBtn.disabled = name !== 'camera' || !state.cam;
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
  els.goal.textContent = `/ ${fmt.format(state.goal)}`;
}

async function refreshStats() {
  try {
    const stats = await api(`/api/x/${EXT}/stats`);
    // never let a slow poll roll the counter back below a number we already showed
    state.total = Math.max(stats.total, state.total || 0);
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

function homeLink() {
  return h('a', { class: 'vb-btn vb-btn--ghost vb-btn--block beer-notice-home', href: '/' }, 'Zur Startseite');
}

// -------------------------------------------------------------- camera

async function startCamera() {
  setState('loading');
  try {
    // ask for a 4:3 stream: phone sensors are 4:3, so the 3:4 crop keeps the whole field of view
    state.cam = await openCamera(els.video, { facing: 'environment', width: 1920, height: 1440 });
  } catch (err) {
    debug('camera failed', err.name, err.code, err.message);
    els.loading.hidden = true;
    setState('off');
    showNotice('📷', 'Kamera geht nicht', err.message || 'Die Kamera konnte nicht gestartet werden.',
      reloadButton(), homeLink());
    return;
  }
  els.loading.hidden = true;
  setMirrored();
  setState('camera');
  debug('camera', state.cam.facing, `${state.cam.width}x${state.cam.height}`);
}

async function switchCamera() {
  const cam = state.cam;
  if (!cam || state.busy) return;
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

async function uploadFailed(err) {
  debug('upload failed', err.status, err.code, err.message);
  if (err.code === 'banned') {
    setState('off');
    showNotice('🚫', 'Gesperrt', err.message, homeLink());
    return;
  }
  if (err.code === 'needs_consent') {
    // the device lost its identity (cookies cleared): show the banner again, then retry
    try { await boot(); } catch (_) { /* the retry button still works */ }
  }
  setState('error');
  els.upload.classList.add('is-error');
  els.uploadText.textContent = err.message || 'Upload fehlgeschlagen.';
  els.uploadActions.hidden = false;
  toast(err.message || 'Upload fehlgeschlagen.', { type: 'error', ms: 5000 });
}

function discardShot() {
  if (state.pending && state.pending.canvas) state.pending.canvas.remove();
  for (const still of els.frame.querySelectorAll('.beer-still')) still.remove();
  state.pending = null;
  els.upload.hidden = true;
  els.uploadActions.hidden = true;
  setState(state.cam ? 'camera' : 'off');
}

// ------------------------------------------------------------- success

function showSuccess(res, shot) {
  const number = res.beer_number ?? (res.photo && res.photo.seq);
  state.total = Math.max(res.total ?? number ?? 0, state.total || 0);
  renderTotal();

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
  // hardware/keyboard shutter: space or enter while the camera is up
  document.addEventListener('keydown', (e) => {
    if ((e.key === ' ' || e.key === 'Enter') && els.app.dataset.state === 'camera'
        && document.activeElement === document.body) {
      e.preventDefault();
      shoot();
    }
  });
  setInterval(() => {
    if (document.visibilityState === 'visible') refreshStats();
  }, STATS_EVERY_MS);
}

async function main() {
  wireUi();
  setupInAppHint();
  const { banned } = await boot();
  mountUserChip($('user-chip'));
  refreshStats();
  if (banned) {
    // boot() already shows the "Gesperrt" notice
    els.loading.hidden = true;
    setState('off');
    return;
  }
  await startCamera();
}

main().catch((err) => {
  debug('main failed', err && (err.stack || err.message));
  showNotice('😵', 'Ups', (err && err.message) || 'Da ist etwas schiefgelaufen.', reloadButton());
});
