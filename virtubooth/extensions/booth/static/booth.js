// Fotobox page: live filtered camera preview, swipe/tap filters, optional
// 3-2-1 countdown, capture at 1080×1440, save to the phone + background upload.

import {
  CameraError, api, boot, cameraErrorMessage, canvasToJpeg, confetti, debug, flash, h, mountUserChip,
  openCamera, saveImage, showNotice, toast, uploadJpeg, vibrate,
} from '/static/core/vb.js';
import { FILTERS, buildFilterList, drawOverlay } from './filters.js';
import { OUTPUT_H, OUTPUT_W, createRenderer } from './renderer.js';

const EXT_ID = 'booth';
const COUNTDOWN_KEY = 'vb_booth_countdown';
const COUNTDOWN_SECONDS = 3;
const JPEG_QUALITY = 0.9;
const RESULT_TITLES = ['Wie schön! 😍', 'Hammer! 🤩', 'Legendär! 🏆', 'Cover-Material! ✨', 'Zum Einrahmen! 🖼️', 'Party-Ikone! 💃'];

const $ = (id) => document.getElementById(id);
const els = {
  booth: $('booth'),
  frame: $('frame'),
  video: $('video'),
  slot: $('canvas-slot'),
  name: $('filter-name'),
  countdown: $('countdown'),
  loading: $('loading'),
  strip: $('strip'),
  shutter: $('shutter'),
  switchCam: $('switch-camera'),
  countdownToggle: $('countdown-toggle'),
  outbox: $('outbox'),
  result: $('result'),
  resultTitle: $('result-title'),
  photo: $('result-photo'),
  upload: $('upload'),
  uploadText: $('upload-text'),
  uploadProgress: $('upload-progress'),
  uploadBar: $('upload-bar'),
  retry: $('upload-retry'),
  save: $('save'),
  saveLabel: $('save-label'),
  again: $('again'),
};

const state = {
  filters: [],
  index: 0,
  cam: null,
  renderer: null,
  canvas: null,
  overlayInfo: null,
  overlayCanvas: null,
  running: false,
  rafId: 0,
  ready: false,
  busy: false,
  countdown: storageGet(COUNTDOWN_KEY) === '1',
  shot: null, // the photo on the result screen
  outbox: [], // photos whose upload failed after the guest moved on
  t0: performance.now(),
  playTried: 0,
  wakeLock: null,
};

function storageGet(key) {
  try { return localStorage.getItem(key); } catch (_) { return null; }
}
function storageSet(key, value) {
  try { localStorage.setItem(key, value); } catch (_) { /* private mode */ }
}

// ------------------------------------------------------------- renderer

function setupRenderer(prefer) {
  const canvas = h('canvas', { class: 'booth-canvas', 'data-testid': 'preview-canvas' });
  els.slot.append(canvas);
  const base = FILTERS.find((f) => f.id === 'normal');
  const created = createRenderer(canvas, { prefer, baseFilter: base });
  state.renderer = created.renderer;
  state.canvas = created.canvas;
  els.booth.dataset.renderer = state.renderer.mode;
  debug('renderer', state.renderer.mode);
  sizeCanvas();
  const onResize = () => {
    sizeCanvas();
    const chip = els.strip.querySelector('[aria-selected="true"]');
    if (chip) centerChip(chip, 'auto');
  };
  if (window.ResizeObserver) new ResizeObserver(onResize).observe(els.frame);
  else window.addEventListener('resize', onResize);
}

/** Backing store = on-screen size (DPR ≤ 2), never more than the photo. */
function sizeCanvas() {
  const rect = els.frame.getBoundingClientRect();
  if (!rect.width) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const maxW = state.renderer.mode === 'webgl' ? OUTPUT_W : 480; // pixel ops are CPU work
  const w = Math.max(60, Math.min(maxW, Math.round(rect.width * dpr)));
  const hgt = Math.round((w * OUTPUT_H) / OUTPUT_W);
  if (state.canvas.width !== w || state.canvas.height !== hgt) {
    state.canvas.width = w;
    state.canvas.height = hgt;
  }
}

function frame(now) {
  state.rafId = 0;
  if (!state.running) return;
  // iOS can leave the camera video paused (power saving, after a call): nudge it
  if (els.video.paused && state.cam.live && now - state.playTried > 1000) {
    state.playTried = now;
    els.video.play().catch(() => {});
  }
  const drawn = state.renderer.render(els.video, {
    mirror: state.cam.mirrored,
    time: ((now - state.t0) / 1000) % 1000,
  });
  if (drawn && !state.ready) {
    state.ready = true;
    els.booth.dataset.ready = '1';
    els.loading.classList.add('vb-hidden');
    updateButtons();
  }
  state.rafId = requestAnimationFrame(frame);
}

function startLoop() {
  if (state.running || !state.cam || document.hidden || state.shot) return;
  state.running = true;
  state.rafId = requestAnimationFrame(frame);
  keepScreenOn();
}

/** A phone on a stand should not go dark mid-party (Android Chrome, iOS 16.4+). */
async function keepScreenOn() {
  if (!navigator.wakeLock || (state.wakeLock && !state.wakeLock.released)) return;
  try {
    state.wakeLock = await navigator.wakeLock.request('screen');
  } catch (_) { /* not allowed (battery saver, iframe): fine */ }
}

function stopLoop() {
  state.running = false;
  if (state.rafId) cancelAnimationFrame(state.rafId);
  state.rafId = 0;
}

// --------------------------------------------------------------- filters

function buildStrip() {
  els.strip.replaceChildren(...state.filters.map((f, i) => h('button', {
    class: 'booth-chip', type: 'button', role: 'option', 'aria-selected': 'false',
    'data-filter': f.id, 'data-testid': `filter-${f.id}`, onclick: () => selectFilter(i),
  },
  h('span', { class: 'booth-chip-icon', 'aria-hidden': 'true' }, f.icon),
  h('span', { class: 'booth-chip-name' }, f.name))));
}

function selectFilter(index, { announce = true } = {}) {
  const n = state.filters.length;
  const i = ((index % n) + n) % n;
  const filter = state.filters[i];
  try {
    state.renderer.setFilter(filter, drawOverlay(filter, state.overlayCanvas, state.overlayInfo));
  } catch (err) {
    console.error(err);
    toast('Dieser Filter klappt auf deinem Handy leider nicht.', { type: 'error' });
    const current = state.filters[state.index];
    if (current !== filter) drawOverlay(current, state.overlayCanvas, state.overlayInfo); // shared canvas
    return;
  }
  state.index = i;
  els.booth.dataset.filter = filter.id;
  els.strip.querySelectorAll('.booth-chip').forEach((chip, k) => {
    chip.setAttribute('aria-selected', k === i ? 'true' : 'false');
    if (k === i) centerChip(chip, announce ? 'smooth' : 'auto');
  });
  if (announce) showFilterName(filter);
}

function centerChip(chip, behavior) {
  const strip = els.strip.getBoundingClientRect();
  const box = chip.getBoundingClientRect();
  const left = els.strip.scrollLeft + (box.left - strip.left) - (strip.width - box.width) / 2;
  els.strip.scrollTo({ left, behavior });
}

function showFilterName(filter) {
  const label = h('span', { class: 'booth-filter-name-text' }, `${filter.icon} ${filter.name}`);
  els.name.replaceChildren(label); // a fresh node restarts the animation
}

/** Swipe left/right on the preview = next/previous filter; double tap = flip camera. */
function bindGestures() {
  let start = null;
  let lastTap = 0;
  els.frame.addEventListener('pointerdown', (e) => {
    if (!e.isPrimary) return;
    start = { x: e.clientX, y: e.clientY, id: e.pointerId };
  });
  els.frame.addEventListener('pointerup', (e) => {
    if (!start || e.pointerId !== start.id) return;
    const dx = e.clientX - start.x;
    const dy = e.clientY - start.y;
    start = null;
    if (state.busy || state.shot) return;
    if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy) * 1.3) {
      lastTap = 0;
      selectFilter(state.index + (dx < 0 ? 1 : -1));
      vibrate(8);
    } else if (Math.abs(dx) < 12 && Math.abs(dy) < 12) {
      const now = performance.now();
      if (now - lastTap < 320) {
        lastTap = 0;
        switchCamera();
      } else {
        lastTap = now;
      }
    }
  });
  els.frame.addEventListener('pointercancel', () => { start = null; });
}

// ---------------------------------------------------------------- camera

async function startCamera() {
  try {
    state.cam = await openCamera(els.video, { facing: 'user', width: 1440, height: 1080 });
  } catch (err) {
    showCameraError(err);
    return;
  }
  cameraReady();
}

function cameraReady() {
  const { cam } = state;
  els.booth.dataset.facing = cam.facing;
  els.booth.dataset.mirror = cam.mirrored ? '1' : '0';
  els.video.classList.toggle('is-mirrored', cam.mirrored);
  debug('camera', cam.facing, `${cam.width}x${cam.height}`);
  startLoop();
}

function showCameraError(err) {
  console.warn('camera', err);
  stopLoop();
  const message = err instanceof CameraError ? err.message : cameraErrorMessage(err);
  showNotice('📷', 'Die Kamera geht nicht', message,
    h('div', { class: 'booth-notice-actions' },
      h('button', { class: 'vb-btn vb-btn--primary vb-btn--block', type: 'button', onclick: () => location.reload() },
        'Nochmal versuchen'),
      h('a', { class: 'vb-btn vb-btn--ghost vb-btn--block', href: '/' }, 'Zur Übersicht')));
}

async function switchCamera() {
  if (!state.cam || state.busy || state.shot || !state.cam.canSwitch) return;
  state.busy = true;
  stopLoop();
  state.ready = false;
  delete els.booth.dataset.ready;
  els.loading.classList.remove('vb-hidden');
  updateButtons();
  const before = state.cam.facing;
  try {
    await state.cam.switchFacing();
  } catch (err) {
    toast(err.message || 'Kamera-Wechsel hat nicht geklappt.', { type: 'error' });
    try {
      state.cam.facing = before;
      await state.cam.start();
    } catch (err2) {
      state.busy = false;
      showCameraError(err2);
      return;
    }
  }
  state.busy = false;
  cameraReady();
}

function updateButtons() {
  const idle = state.ready && !state.busy;
  els.shutter.disabled = !idle;
  els.switchCam.disabled = !idle;
  els.switchCam.classList.toggle('vb-hidden', !!state.cam && !state.cam.canSwitch); // laptop/PC: one webcam
  els.countdownToggle.setAttribute('aria-pressed', state.countdown ? 'true' : 'false');
}

// --------------------------------------------------------------- capture

function runCountdown(seconds) {
  return new Promise((resolve) => {
    els.booth.dataset.counting = '1';
    let left = seconds;
    const tick = () => {
      if (left === 0) {
        els.countdown.replaceChildren();
        delete els.booth.dataset.counting;
        resolve();
        return;
      }
      els.countdown.replaceChildren(h('span', { class: 'booth-countdown-num' }, String(left)));
      vibrate(12);
      left -= 1;
      setTimeout(tick, 1000);
    };
    tick();
  });
}

async function shoot() {
  if (state.busy || !state.ready || state.shot) return;
  state.busy = true;
  updateButtons();
  try {
    if (state.countdown) await runCountdown(COUNTDOWN_SECONDS);
    // freeze the preview: the frame on screen now is the photo, and the JPEG
    // encoder (an idle task in Chrome) gets the CPU instead of the render loop
    stopLoop();
    flash();
    vibrate(40);
    const t0 = performance.now();
    const canvas = state.renderer.capture(); // the last frame again, at 1080×1440
    const filter = state.filters[state.index];
    const blob = await canvasToJpeg(canvas, JPEG_QUALITY);
    debug('capture', `${Math.round(performance.now() - t0)} ms`, `${Math.round(blob.size / 1024)} KB`);
    showResult({ blob, meta: { filter: filter.id, facing: state.cam.facing } });
  } catch (err) {
    console.error(err);
    toast('Das Foto hat nicht geklappt. Nochmal?', { type: 'error' });
    startLoop();
  } finally {
    state.busy = false;
    updateButtons();
  }
}

// ---------------------------------------------------------------- result

function showResult({ blob, meta }) {
  stopLoop();
  const shot = { blob, meta, url: URL.createObjectURL(blob), status: 'idle', progress: 0, seq: null, error: '', attached: true };
  state.shot = shot;
  els.photo.src = shot.url;
  els.resultTitle.textContent = RESULT_TITLES[Math.floor(Math.random() * RESULT_TITLES.length)];
  els.save.dataset.saved = '';
  els.saveLabel.textContent = 'Speichern';
  els.result.classList.remove('vb-hidden');
  els.booth.dataset.screen = 'result';
  upload(shot);
  els.save.focus({ preventScroll: true });
}

function upload(shot) {
  shot.status = 'uploading';
  shot.progress = 0;
  shot.error = '';
  renderUpload(shot);
  uploadJpeg(EXT_ID, shot.blob, {
    meta: shot.meta,
    onProgress: (p) => { shot.progress = p; renderUpload(shot); },
  }).then((res) => {
    shot.status = 'done';
    shot.seq = res.booth_number ?? res.photo.seq;
    renderUpload(shot);
    if (shot.attached) confetti({ count: 90 });
    else toast(`Foto #${shot.seq} ist hochgeladen ✓`, { type: 'success' });
  }).catch((err) => {
    shot.status = 'error';
    shot.error = err.message || 'Upload fehlgeschlagen.';
    renderUpload(shot);
    if (!shot.attached) addToOutbox(shot);
  });
}

function renderUpload(shot) {
  if (!shot.attached) return;
  els.upload.dataset.state = shot.status;
  els.uploadProgress.classList.toggle('vb-hidden', shot.status !== 'uploading');
  els.retry.classList.toggle('vb-hidden', shot.status !== 'error');
  els.uploadBar.style.width = `${Math.round(shot.progress * 100)}%`;
  if (shot.status === 'uploading') {
    els.uploadText.textContent = `Wird hochgeladen … ${Math.round(shot.progress * 100)} %`;
  } else if (shot.status === 'done') {
    els.uploadText.textContent = `Hochgeladen ✓ · Foto #${shot.seq}`;
  } else if (shot.status === 'error') {
    els.uploadText.textContent = `Nicht hochgeladen: ${shot.error}`;
  }
}

function backToCamera() {
  const shot = state.shot;
  if (!shot) return;
  shot.attached = false;
  if (shot.status === 'error') addToOutbox(shot);
  URL.revokeObjectURL(shot.url);
  state.shot = null;
  els.result.classList.add('vb-hidden');
  els.photo.removeAttribute('src');
  els.booth.dataset.screen = 'camera';
  // keyboard: the focused button just disappeared; space/enter go to the shutter now
  els.shutter.focus({ preventScroll: true });
  startLoop();
}

async function savePhoto() {
  const shot = state.shot;
  if (!shot) return;
  const stamp = new Date().toTimeString().slice(0, 8).replaceAll(':', '');
  const name = `fotobox-${shot.seq ?? stamp}.jpg`;
  try {
    const how = await saveImage(shot.blob, name);
    if (how !== 'cancelled' && state.shot === shot) {
      els.save.dataset.saved = '1';
      els.saveLabel.textContent = 'Gespeichert ✓';
    }
  } catch (err) {
    console.warn('save', err);
    toast('Speichern hat nicht geklappt. Halte das Foto gedrückt und sichere es so.', { type: 'error', ms: 5000 });
  }
}

function addToOutbox(shot) {
  if (!state.outbox.includes(shot)) state.outbox.push(shot);
  renderOutbox();
}

function renderOutbox() {
  const n = state.outbox.length;
  els.outbox.classList.toggle('vb-hidden', n === 0);
  els.outbox.textContent = `⚠️ ${n} nicht hochgeladen · nochmal`;
}

function retryOutbox() {
  const shots = state.outbox.splice(0);
  renderOutbox();
  for (const shot of shots) upload(shot);
}

// ------------------------------------------------------------------ main

function bindControls() {
  els.shutter.addEventListener('click', shoot);
  els.switchCam.addEventListener('click', switchCamera);
  els.countdownToggle.addEventListener('click', () => {
    state.countdown = !state.countdown;
    storageSet(COUNTDOWN_KEY, state.countdown ? '1' : '0');
    updateButtons();
    toast(state.countdown ? 'Countdown an: 3 … 2 … 1 ⏱️' : 'Countdown aus', { ms: 1400 });
  });
  els.retry.addEventListener('click', () => state.shot && upload(state.shot));
  els.save.addEventListener('click', savePhoto);
  els.again.addEventListener('click', backToCamera);
  els.outbox.addEventListener('click', retryOutbox);
  bindGestures();
  // desktop: arrows switch filters (also while a chip or the shutter has focus),
  // space/enter shoots, escape leaves the result screen
  document.addEventListener('keydown', (e) => {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    if (state.shot) {
      if (e.key === 'Escape') backToCamera();
      return;
    }
    const onPage = e.target === document.body;
    const inStrip = els.strip.contains(e.target);
    if (!onPage && !inStrip && e.target !== els.shutter) return;
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault();
      selectFilter(state.index + (e.key === 'ArrowRight' ? 1 : -1));
      if (inStrip) els.strip.querySelector('[aria-selected="true"]').focus({ preventScroll: true });
    } else if (onPage && (e.key === ' ' || e.key === 'Enter')) {
      e.preventDefault();
      shoot();
    }
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopLoop();
    else startLoop();
  });
}

async function main() {
  updateButtons();
  const { banned } = await boot();
  mountUserChip($('user-chip'));
  if (banned) return; // boot() shows the notice
  const [catalogue, info] = await Promise.all([
    api('./filters.json'),
    api('/api/extensions').catch(() => null),
  ]);
  const partyName = (info && info.party_name) || 'Party';
  document.title = `Fotobox · ${partyName}`;
  state.overlayInfo = { partyName, title: `${partyName} 🎉`, date: new Date() };

  state.overlayCanvas = h('canvas', { width: OUTPUT_W, height: OUTPUT_H });
  setupRenderer(new URLSearchParams(location.search).get('renderer'));
  state.filters = buildFilterList(catalogue.filters, state.renderer.mode);
  buildStrip();
  bindControls();
  selectFilter(0, { announce: false });
  await startCamera();
}

main().catch((err) => {
  console.error(err);
  toast(err.message || 'Da ist etwas schiefgelaufen.', { type: 'error', ms: 6000 });
});
