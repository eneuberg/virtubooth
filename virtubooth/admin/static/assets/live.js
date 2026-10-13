// Live screen: newest uploads in real time. Only take down / show again here;
// deleting lives in the management screen on purpose.

import {
  aapi, connectEvents, h, Lightbox, loadExtensions, mountHeader, PhotoCollection,
  photoTitle, qs, runToggle, showError, statusBadge, thumbFlag, throttle, timeEl, toggleButton, userLink,
} from './admin.js';
import { mountUploadControls } from './uploadcontrols.js';

const PAGE = 30;
const feed = document.getElementById('feed');
const emptyEl = document.getElementById('empty');
const loadingEl = document.getElementById('loading');
const moreBtn = document.getElementById('more');
const pill = document.getElementById('new-pill');

let nextCursor = null;
let loadingMore = false;
let unseen = 0;

const photos = new PhotoCollection(feed, renderCard);
const lightbox = new Lightbox({
  list: () => photos.photos,
  actions: (photo) => [toggleButton(photo, onToggle, { cls: 'vb-btn--big' })],
});

function renderCard(photo) {
  return h('article', { class: `adm-card${photo.hidden ? ' is-hidden' : ''}`, 'data-testid': 'photo-card' },
    h('button', {
      class: 'adm-thumb', type: 'button', 'aria-label': `${photoTitle(photo)} groß anzeigen`,
      'data-testid': 'thumb', 'data-thumb-for': photo.id, onclick: () => lightbox.open(photo.id),
    },
      h('img', { src: photo.thumb_url, alt: '', loading: 'lazy', decoding: 'async' }),
      thumbFlag(photo),
    ),
    h('div', { class: 'adm-card-body' },
      h('span', { class: 'adm-card-title' }, photoTitle(photo)),
      h('div', { class: 'adm-meta' }, timeEl(photo.created_at), statusBadge(photo)),
      userLink(photo.user),
      toggleButton(photo, onToggle),
    ),
  );
}

function onToggle(photo, button) {
  runToggle(photo, button, (updated) => update(updated));
}

function syncEmpty() {
  emptyEl.classList.toggle('vb-hidden', photos.size > 0);
  moreBtn.classList.toggle('vb-hidden', !nextCursor);
}

/** state change of a photo we may show */
function update(photo) {
  if (!photos.has(photo.id)) return;
  photos.upsert(photo);
  lightbox.refresh();
  refreshStats();
}

/** a photo we may not know yet: insert without moving what the thumb is on */
function add(photo) {
  if (photos.has(photo.id)) {
    update(photo);
    return;
  }
  const atTop = window.scrollY < 60;
  const before = document.documentElement.scrollHeight;
  photos.upsert(photo);
  photos.items.get(photo.id).el.classList.add('is-new');
  if (!atTop) {
    window.scrollBy(0, document.documentElement.scrollHeight - before);
    unseen += 1;
    pill.textContent = `⬆ ${unseen} ${unseen === 1 ? 'neues Foto' : 'neue Fotos'}`;
    pill.classList.remove('vb-hidden');
  }
  syncEmpty();
  lightbox.refresh();
}

function remove(id) {
  if (photos.remove(id)) {
    syncEmpty();
    lightbox.refresh();
  }
}

function hidePill() {
  unseen = 0;
  pill.classList.add('vb-hidden');
}

pill.addEventListener('click', () => {
  hidePill();
  window.scrollTo({ top: 0, behavior: 'smooth' });
});
window.addEventListener('scroll', () => { if (window.scrollY < 60 && unseen) hidePill(); }, { passive: true });

async function loadMore() {
  if (!nextCursor || loadingMore) return;
  loadingMore = true;
  moreBtn.disabled = true;
  try {
    const data = await aapi(`/api/admin/photos${qs({ limit: PAGE, before: nextCursor })}`);
    for (const p of data.photos) photos.upsert(p, { append: true });
    nextCursor = data.next;
  } catch (err) {
    showError(err);
  } finally {
    loadingMore = false;
    moreBtn.disabled = false;
    syncEmpty();
  }
}

/** after a reconnect or while polling: newest page from the server wins */
async function resync() {
  try {
    const data = await aapi(`/api/admin/photos${qs({ limit: PAGE })}`);
    const fresh = new Set(data.photos.map((p) => p.id));
    const oldest = data.photos[data.photos.length - 1];
    for (const p of photos.photos) {
      // inside the window the server sent, anything missing was deleted
      if (!oldest || (p.created_at >= oldest.created_at && !fresh.has(p.id))) remove(p.id);
    }
    for (const p of [...data.photos].reverse()) add(p);
    if (!photos.size) nextCursor = data.next;
    syncEmpty();
    refreshStats();
  } catch (err) {
    if (err.code !== 'network') showError(err);
  }
}

function setStat(id, value) {
  document.getElementById(id).textContent = String(value);
}

async function loadStats() {
  try {
    const s = await aapi('/api/admin/stats');
    setStat('stat-photos', s.photos);
    setStat('stat-guests', s.guests);
    setStat('stat-hidden', s.hidden);
  } catch (_) { /* next event or poll tries again */ }
}
const refreshStats = throttle(loadStats, 800);

function onEvent(type, data) {
  if (type === 'photo.created') add(data.photo);
  else if (type === 'photo.hidden' || type === 'photo.unhidden') update(data.photo);
  else if (type === 'photo.deleted') remove(data.id);
  else if (type === 'user.banned' || type === 'user.unbanned') {
    for (const p of data.photos || []) update(p);
  }
  refreshStats();
}

async function main() {
  mountHeader();
  mountUploadControls(document.getElementById('upload-controls'));
  await loadExtensions();
  const data = await aapi(`/api/admin/photos${qs({ limit: PAGE })}`);
  for (const p of data.photos) photos.upsert(p, { append: true });
  nextCursor = data.next;
  loadingEl.remove();
  syncEmpty();
  loadStats(); // right away: the throttled refresh would show "–" for a moment
  connectEvents({ onEvent, onResync: resync });
  moreBtn.addEventListener('click', loadMore);
  new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) loadMore();
  }, { rootMargin: '400px' }).observe(moreBtn);
  setInterval(refreshStats, 60000);
}

main().catch((err) => {
  loadingEl.remove();
  showError(err);
});
