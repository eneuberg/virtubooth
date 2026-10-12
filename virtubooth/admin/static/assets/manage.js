// Management screen: photos (filters, bulk, delete), guests, Instagram
// handles, bans, audit log. Everything heavier than "take it down" lives here.

import {
  aapi, absTime, confirmAndDelete, connectEvents, copyText, debounce, describeUA, field, h,
  instagramUrl, Lightbox, loadExtensions, managementActions, mountHeader, PhotoCollection, photoTile,
  photoTitle, qs, relTime, runToggle, segmented, showError, throttle, toast, userLink, userUrl,
} from './admin.js';

const TABS = ['fotos', 'gaeste', 'instagram', 'sperren', 'protokoll'];
const PAGE = 48;

const params = new URLSearchParams(location.search);
const state = {
  tab: TABS.includes(params.get('tab')) ? params.get('tab') : 'fotos',
  ext: /^[a-z][a-z0-9-]{1,30}$/.test(params.get('ext') || '') ? params.get('ext') : '',
  status: ['visible', 'hidden'].includes(params.get('status')) ? params.get('status') : 'all',
  user: /^[1-9]\d{0,15}$/.test(params.get('user') || '') ? params.get('user') : '',
};

function syncUrl() {
  const q = qs({
    tab: state.tab === 'fotos' ? '' : state.tab,
    ext: state.ext,
    status: state.status === 'all' ? '' : state.status,
    user: state.user,
  });
  history.replaceState(history.state, '', `/admin/manage${q}`);
}

const pill = document.getElementById('new-pill');
const spinner = () => h('div', { class: 'adm-loading' }, h('div', { class: 'vb-spinner' }));

// ------------------------------------------------------------- lightbox

// the lightbox shows whatever list the opener points it at
let lightboxSource = () => [];
const lightbox = new Lightbox({
  list: () => lightboxSource(),
  actions: (photo) => managementActions(photo, { onToggle, onDelete: (p) => deletePhotos([p]) }),
});

function openLightbox(source, photo) {
  lightboxSource = source;
  lightbox.open(photo.id);
}

// ------------------------------------------------- photo state everywhere

/** a newer version of a photo: update every place that shows it */
function patchPhoto(photo) {
  if (photosCol.has(photo.id)) photosCol.upsert(photo);
  for (const entry of insta.data) {
    entry.recent = entry.recent.map((p) => (p.id === photo.id ? photo : p));
  }
  if (insta.loaded && state.tab === 'instagram') renderInsta();
  lightbox.refresh();
}

/** a photo is gone for good (deleted here, elsewhere, or missing) */
function dropPhoto(id, photo = null) {
  const known = photo || photosCol.get(id);
  if (!fotos.gone.has(id)) {
    // the API answer and the SSE event both report a deletion: count it once
    fotos.gone.add(id);
    if (photosCol.has(id) || (known && matchesFilter(known))) {
      fotos.total = Math.max(0, fotos.total - 1);
      syncTotal();
    }
  }
  photosCol.remove(id);
  fotos.selected.delete(id);
  for (const entry of insta.data) entry.recent = entry.recent.filter((p) => p.id !== id);
  if (insta.loaded && state.tab === 'instagram') renderInsta();
  syncBulkbar();
  syncFotosEmpty();
  lightbox.refresh();
}

function onToggle(photo, button) {
  runToggle(photo, button, (updated) => {
    patchPhoto(updated);
    refreshStats();
  });
}

async function deletePhotos(list) {
  const byId = new Map(list.map((p) => [p.id, p]));
  const gone = await confirmAndDelete(list);
  for (const id of gone) dropPhoto(id, byId.get(id));
  if (gone.length) refreshStats();
}

// ================================================================ FOTOS

const fotos = {
  el: document.getElementById('panel-fotos'),
  next: null,
  total: 0,
  loading: false,
  reqId: 0,
  pending: 0,
  selected: new Set(),
  gone: new Set(),
  lastClicked: null,
  userIds: new Set(),
};

const extSelect = h('select', { class: 'adm-select', 'data-testid': 'filter-ext' }, h('option', { value: '' }, 'Alle Aktivitäten'));
const userSelect = h('select', { class: 'adm-select', 'data-testid': 'filter-user' }, h('option', { value: '' }, 'Alle Gäste'));
const statusSeg = segmented([['all', 'Alle'], ['visible', 'Sichtbar'], ['hidden', 'Versteckt']], state.status,
  (v) => { state.status = v; reloadPhotos(); }, { label: 'Status', testid: 'filter-status' });
const totalEl = h('span', { class: 'adm-num', 'data-testid': 'photo-total' });
const grid = h('div', { class: 'adm-grid', 'data-testid': 'grid' });
const fotosEmpty = h('div', { class: 'adm-empty vb-hidden', 'data-testid': 'grid-empty' }, h('strong', {}, 'Keine Fotos.'), 'Für diesen Filter gibt es (noch) nichts.');
const fotosMore = h('button', { class: 'vb-btn vb-btn--ghost vb-btn--block adm-more vb-hidden', type: 'button' }, 'Mehr laden');
const fotosLoading = spinner();
const bulkCount = h('strong', { 'data-testid': 'bulk-count' });
const bulkbar = h('div', { class: 'adm-bulkbar vb-hidden', 'data-testid': 'bulkbar', role: 'toolbar', 'aria-label': 'Auswahl' },
  bulkCount,
  h('button', { class: 'vb-btn adm-toggle--hide', type: 'button', 'data-testid': 'bulk-hide', onclick: () => bulk('hide') }, '🙈 Runternehmen'),
  h('button', { class: 'vb-btn adm-toggle--show', type: 'button', 'data-testid': 'bulk-unhide', onclick: () => bulk('unhide') }, '👁 Zeigen'),
  h('button', { class: 'vb-btn vb-btn--danger', type: 'button', 'data-testid': 'bulk-delete', onclick: () => bulk('delete') }, '🗑 Löschen'),
  h('button', { class: 'vb-btn vb-btn--ghost', type: 'button', 'data-testid': 'bulk-clear', onclick: () => clearSelection() }, 'Abbrechen'),
);

const photosCol = new PhotoCollection(grid, (photo) => photoTile(photo, {
  selected: fotos.selected.has(photo.id),
  onSelect: onSelectClick,
  onOpen: (p) => openLightbox(() => photosCol.photos, p),
  onToggle,
  onDelete: (p) => deletePhotos([p]),
}));

function buildFotos() {
  extSelect.addEventListener('change', () => { state.ext = extSelect.value; reloadPhotos(); });
  userSelect.addEventListener('change', () => { state.user = userSelect.value; reloadPhotos(); });
  fotosMore.addEventListener('click', loadMorePhotos);
  fotos.el.append(
    h('div', { class: 'adm-toolbar adm-toolbar--filters' },
      field('Aktivität', extSelect),
      field('Gast', userSelect),
      h('div', { class: 'adm-field adm-field--wide' }, h('span', {}, 'Status'), statusSeg),
    ),
    h('div', { class: 'adm-selectline' },
      totalEl,
      h('button', { class: 'vb-btn vb-btn--ghost adm-btn-sm', type: 'button', 'data-testid': 'select-all', onclick: selectAllLoaded }, '☑ Alle auswählen'),
      h('span', { class: 'adm-muted adm-hover-only' }, 'Tipp: Shift-Klick auf die Häkchen wählt einen Bereich.'),
    ),
    grid, fotosLoading, fotosEmpty, fotosMore, bulkbar,
  );
  new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) loadMorePhotos();
  }, { rootMargin: '600px' }).observe(fotosMore);
}

function fillExtSelect(extensions) {
  for (const e of extensions) extSelect.append(h('option', { value: e.id }, `${e.emoji} ${e.title}`));
  if (state.ext && !extensions.some((e) => e.id === state.ext)) extSelect.append(h('option', { value: state.ext }, state.ext));
  extSelect.value = state.ext;
}

async function fillUserSelect() {
  try {
    const data = await aapi(`/api/admin/users${qs({ limit: 500 })}`);
    const users = data.users.filter((u) => u.photo_count > 0 || String(u.id) === state.user);
    users.sort((a, b) => a.name.localeCompare(b.name, 'de'));
    fotos.userIds = new Set(users.map((u) => u.id));
    userSelect.replaceChildren(
      h('option', { value: '' }, 'Alle Gäste'),
      ...users.map((u) => h('option', { value: String(u.id) },
        `${u.banned ? '🚫 ' : ''}${u.name}${u.instagram ? ` · @${u.instagram}` : ''} (${u.photo_count})`)),
    );
    if (state.user && !users.some((u) => String(u.id) === state.user)) {
      userSelect.append(h('option', { value: state.user }, `Gast #${state.user}`));
    }
    userSelect.value = state.user;
  } catch (err) {
    showError(err);
  }
}
const refreshUserSelect = throttle(fillUserSelect, 1500);

function filterParams(extra = {}) {
  return {
    extension: state.ext,
    hidden: state.status === 'all' ? '' : state.status,
    user_id: state.user,
    ...extra,
  };
}

function matchesFilter(photo) {
  if (state.ext && photo.extension !== state.ext) return false;
  if (state.status === 'hidden' && !photo.hidden) return false;
  if (state.status === 'visible' && photo.hidden) return false;
  if (state.user && String(photo.user.id) !== state.user) return false;
  return true;
}

function syncTotal() {
  totalEl.textContent = `${fotos.total} ${fotos.total === 1 ? 'Foto' : 'Fotos'}`;
}

function syncFotosEmpty() {
  fotosEmpty.classList.toggle('vb-hidden', fotos.loading || photosCol.size > 0);
  fotosMore.classList.toggle('vb-hidden', !fotos.next);
}

async function reloadPhotos() {
  syncUrl();
  const req = ++fotos.reqId;
  fotos.loading = true;
  fotos.next = null;
  hidePill();
  clearSelection();
  photosCol.clear();
  fotosLoading.classList.remove('vb-hidden');
  syncFotosEmpty();
  try {
    const data = await aapi(`/api/admin/photos${qs(filterParams({ limit: PAGE }))}`);
    if (req !== fotos.reqId) return;
    for (const p of data.photos) photosCol.upsert(p, { append: true });
    fotos.next = data.next;
    fotos.total = data.total;
    fotos.gone.clear();
    syncTotal();
  } catch (err) {
    if (req === fotos.reqId) showError(err);
  } finally {
    if (req === fotos.reqId) {
      fotos.loading = false;
      fotosLoading.classList.add('vb-hidden');
      syncFotosEmpty();
    }
  }
}

async function loadMorePhotos() {
  if (!fotos.next || fotos.loading) return;
  const req = fotos.reqId;
  fotos.loading = true;
  fotosMore.disabled = true;
  try {
    const data = await aapi(`/api/admin/photos${qs(filterParams({ limit: PAGE, before: fotos.next }))}`);
    if (req !== fotos.reqId) return;
    for (const p of data.photos) photosCol.upsert(p, { append: true });
    fotos.next = data.next;
  } catch (err) {
    showError(err);
  } finally {
    fotos.loading = false;
    fotosMore.disabled = false;
    syncFotosEmpty();
  }
}

/** pill "N neue Fotos": fetch what arrived since the newest one shown */
async function showNewPhotos() {
  hidePill();
  const newest = photosCol.newest();
  if (!newest) {
    reloadPhotos();
    return;
  }
  try {
    const data = await aapi(`/api/admin/photos${qs(filterParams({ limit: 200, after: newest.id }))}`);
    let added = 0;
    for (const p of data.photos) if (photosCol.upsert(p) === 'inserted') added += 1;
    fotos.total += added;
    syncTotal();
    syncFotosEmpty();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (err) {
    showError(err);
  }
}

function hidePill() {
  fotos.pending = 0;
  pill.classList.add('vb-hidden');
}

function syncPill() {
  const show = state.tab === 'fotos' && fotos.pending > 0;
  pill.classList.toggle('vb-hidden', !show);
  pill.textContent = `⬆ ${fotos.pending} ${fotos.pending === 1 ? 'neues Foto' : 'neue Fotos'} anzeigen`;
}
pill.addEventListener('click', showNewPhotos);

// --- selection

function markSelected(id) {
  const item = photosCol.items.get(id);
  if (!item) return;
  const on = fotos.selected.has(id);
  item.el.classList.toggle('is-selected', on);
  const box = item.el.querySelector('input[type="checkbox"]');
  if (box) box.checked = on;
}

function onSelectClick(photo, checked, shift) {
  const ids = photosCol.photos.map((p) => p.id);
  const from = ids.indexOf(fotos.lastClicked);
  const to = ids.indexOf(photo.id);
  const range = shift && from >= 0 && to >= 0 ? ids.slice(Math.min(from, to), Math.max(from, to) + 1) : [photo.id];
  for (const id of range) {
    if (checked) fotos.selected.add(id);
    else fotos.selected.delete(id);
    markSelected(id);
  }
  fotos.lastClicked = photo.id;
  syncBulkbar();
}

function selectAllLoaded() {
  for (const p of photosCol.photos) {
    fotos.selected.add(p.id);
    markSelected(p.id);
  }
  syncBulkbar();
}

function clearSelection() {
  const ids = [...fotos.selected];
  fotos.selected.clear();
  for (const id of ids) markSelected(id);
  fotos.lastClicked = null;
  syncBulkbar();
}

function syncBulkbar() {
  const n = fotos.selected.size;
  bulkbar.classList.toggle('vb-hidden', n === 0);
  bulkCount.textContent = `${n} ausgewählt`;
}

async function bulk(action) {
  const ids = [...fotos.selected].filter((id) => photosCol.has(id));
  if (!ids.length) return;
  if (action === 'delete') {
    // cancelled → the selection stays; deleted ones leave it via dropPhoto()
    await deletePhotos(ids.map((id) => photosCol.get(id)));
    return;
  }
  const hide = action === 'hide';
  let changed = 0;
  try {
    for (let i = 0; i < ids.length; i += 200) {
      const res = await aapi('/api/admin/photos/bulk', { method: 'POST', json: { ids: ids.slice(i, i + 200), action } });
      changed += res.changed.length;
      for (const id of res.missing) dropPhoto(id);
      for (const id of res.changed) {
        const p = photosCol.get(id);
        if (p) patchPhoto({ ...p, hidden: hide, hidden_reason: hide ? 'admin' : null, hidden_at: hide ? new Date().toISOString() : null });
      }
    }
    toast(hide ? `${changed} Fotos runtergenommen` : `${changed} Fotos wieder sichtbar`, { type: 'success' });
    clearSelection();
    refreshStats();
  } catch (err) {
    showError(err);
  }
}

// ================================================================ GÄSTE

const gaeste = { el: document.getElementById('panel-gaeste'), search: '', banned: 'all', next: null, reqId: 0 };
const guestSearch = h('input', {
  class: 'adm-search', type: 'search', placeholder: 'Name, @instagram oder #Nummer', 'aria-label': 'Gäste suchen',
  autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false', maxlength: '100', 'data-testid': 'guest-search',
});
const guestList = h('div', { class: 'adm-list', 'data-testid': 'guest-list' });
const guestMore = h('button', { class: 'vb-btn vb-btn--ghost vb-btn--block adm-more vb-hidden', type: 'button' }, 'Mehr laden');
const guestCount = h('span', { class: 'adm-num' });

function buildGaeste() {
  guestSearch.addEventListener('input', debounce(() => { gaeste.search = guestSearch.value.trim(); loadGaeste(); }, 250));
  guestMore.addEventListener('click', () => loadGaeste({ more: true }));
  gaeste.el.append(
    h('div', { class: 'adm-toolbar' },
      field('Suche', guestSearch),
      field('Zeigen', segmented([['all', 'Alle'], ['banned', 'Gesperrte'], ['ok', 'Nicht gesperrt']], gaeste.banned,
        (v) => { gaeste.banned = v; loadGaeste(); }, { label: 'Filter' }), 'div'),
      h('div', { class: 'adm-toolbar-end' }, guestCount),
    ),
    guestList, guestMore,
  );
}

function guestRow(u) {
  const sub = [
    u.instagram ? `@${u.instagram}` : 'kein Instagram',
    `zuletzt ${relTime(u.last_seen_at)}`,
    describeUA(u.user_agent),
  ].join(' · ');
  return h('a', { class: `adm-row${u.banned ? ' is-banned' : ''}`, href: userUrl(u.id), 'data-testid': 'guest-row' },
    h('div', { class: 'adm-row-main' },
      h('div', { class: 'adm-row-title' }, `🙂 ${u.name}`, u.banned ? h('span', { class: 'adm-badge adm-badge--ban adm-badge--xs' }, 'GESPERRT') : null),
      h('div', { class: 'adm-row-sub' }, sub),
    ),
    h('div', { class: 'adm-row-side' }, h('span', { class: 'adm-num', title: 'Fotos' }, `📸 ${u.photo_count}`), h('span', { 'aria-hidden': 'true' }, '›')),
  );
}

async function loadGaeste({ more = false } = {}) {
  const req = ++gaeste.reqId;
  const banned = { all: '', banned: 'true', ok: 'false' }[gaeste.banned];
  const offset = more ? gaeste.next || 0 : 0;
  if (!more && !guestList.children.length) guestList.replaceChildren(spinner());
  try {
    const data = await aapi(`/api/admin/users${qs({ search: gaeste.search, banned, limit: 100, offset })}`);
    if (req !== gaeste.reqId) return;
    if (!more) guestList.replaceChildren();
    guestList.append(...data.users.map(guestRow));
    if (!guestList.children.length) {
      guestList.append(h('div', { class: 'adm-empty' }, gaeste.search ? `Niemand passt zu „${gaeste.search}“.` : 'Noch keine Gäste.'));
    }
    gaeste.next = data.next_offset;
    guestMore.classList.toggle('vb-hidden', data.next_offset === null);
    guestCount.textContent = gaeste.search || banned ? `${guestList.querySelectorAll('.adm-row').length}${data.next_offset !== null ? '+' : ''} Treffer` : '';
  } catch (err) {
    if (req === gaeste.reqId) showError(err);
  }
}

// ============================================================ INSTAGRAM

const insta = { el: document.getElementById('panel-instagram'), data: [], loaded: false };
const instaBody = h('div', { class: 'adm-list' });
const instaCopyAll = h('button', { class: 'vb-btn vb-btn--primary adm-btn-sm', type: 'button', 'data-testid': 'copy-all-handles' }, '📋 Alle Handles kopieren');
const instaCount = h('span', { class: 'adm-num' });

function buildInsta() {
  instaCopyAll.addEventListener('click', () => {
    const handles = taggableHandles();
    if (!handles.length) {
      toast('Noch keine Instagram-Handles.');
      return;
    }
    copyText(handles.map((x) => `@${x}`).join(' '), `${handles.length} Handles`);
  });
  insta.el.append(
    h('div', { class: 'adm-section' },
      h('h2', {}, 'Instagram-Handles', instaCount),
      h('p', { class: 'adm-muted' }, 'Zum Markieren beim Posten. Tippe ein Foto an, um es herunterzuladen und den Handle zu kopieren. Handles gesperrter Gäste werden beim Kopieren aller Handles ausgelassen.'),
      h('div', { class: 'adm-toolbar' }, instaCopyAll),
      instaBody,
    ),
  );
}

function taggableHandles() {
  return insta.data.filter((e) => e.users.some((u) => !u.banned)).map((e) => e.handle);
}

function renderInsta() {
  instaCount.textContent = `(${insta.data.length})`;
  instaCopyAll.textContent = `📋 Alle ${taggableHandles().length} Handles kopieren`;
  if (!insta.data.length) {
    instaBody.replaceChildren(h('div', { class: 'adm-empty' }, h('strong', {}, 'Noch keine Handles.'), 'Gäste können ihren Instagram-Namen beim Start oder über den Namens-Chip angeben.'));
    return;
  }
  instaBody.replaceChildren(...insta.data.map((entry) => {
    const allBanned = entry.users.every((u) => u.banned);
    const recent = () => (insta.data.find((e) => e.handle === entry.handle) || { recent: [] }).recent;
    const facts = [`${entry.photos} ${entry.photos === 1 ? 'Foto' : 'Fotos'}`];
    if (entry.hidden) facts.push(`${entry.hidden} versteckt`);
    if (entry.last_upload_at) facts.push(`zuletzt ${relTime(entry.last_upload_at)}`);
    return h('article', { class: 'adm-insta', 'data-testid': 'insta-row', 'data-handle': entry.handle },
      h('div', { class: 'adm-insta-head' },
        h('span', { class: 'adm-insta-handle' }, `@${entry.handle}`),
        allBanned ? h('span', { class: 'adm-badge adm-badge--ban' }, 'GESPERRT') : null,
        h('span', { class: 'adm-muted' }, facts.join(' · ')),
        h('div', { class: 'adm-toolbar-end' },
          h('button', { class: 'vb-btn vb-btn--cool adm-btn-sm', type: 'button', 'data-testid': 'copy-handle', onclick: () => copyText(`@${entry.handle}`) }, '📋 Kopieren'),
          h('a', { class: 'vb-btn adm-btn-sm', href: instagramUrl(entry.handle), target: '_blank', rel: 'noopener noreferrer' }, 'Profil ↗'),
        ),
      ),
      h('div', { class: 'adm-chips' },
        ...entry.users.map((u) => h('a', { class: 'adm-chip-link', href: userUrl(u.id) }, `🙂 ${u.name}`, u.banned ? ' 🚫' : '')),
        ...entry.users.filter((u) => u.photos > 0).map((u) => h('button', {
          class: 'adm-chip-link', type: 'button', onclick: () => showUserPhotos(u.id),
        }, entry.users.length > 1 ? `📸 Alle ${u.photos} Fotos von #${u.id}` : `📸 Alle ${u.photos} Fotos`)),
      ),
      entry.recent.length
        ? h('div', { class: 'adm-strip' }, ...entry.recent.map((p) => h('button', {
          class: 'adm-thumb', type: 'button', 'aria-label': `${photoTitle(p)} ansehen`, onclick: () => openLightbox(recent, p),
        }, h('img', { src: p.thumb_url, alt: '', loading: 'lazy', decoding: 'async' }))))
        : null,
    );
  }));
}

async function loadInsta() {
  if (!insta.loaded) instaBody.replaceChildren(spinner());
  try {
    const data = await aapi('/api/admin/instagram');
    insta.data = data.handles;
    insta.loaded = true;
    renderInsta();
    lightbox.refresh();
  } catch (err) {
    showError(err);
  }
}

function showUserPhotos(userId) {
  state.user = String(userId);
  state.status = 'all';
  state.ext = '';
  statusSeg.setValue('all');
  extSelect.value = '';
  if (![...userSelect.options].some((o) => o.value === state.user)) {
    userSelect.append(h('option', { value: state.user }, `Gast #${state.user}`));
  }
  userSelect.value = state.user;
  panels.fotos.loaded = false;
  showTab('fotos');
}

// ============================================================== SPERREN

const sperren = { el: document.getElementById('panel-sperren') };
const bannedUsersBody = h('div', { class: 'adm-list', 'data-testid': 'banned-users' });
const fpBansBody = h('div', { class: 'adm-list', 'data-testid': 'fp-bans' });
const bannedUsersCount = h('span', { class: 'adm-muted' });
const fpBansCount = h('span', { class: 'adm-muted' });

function buildSperren() {
  sperren.el.append(
    h('div', { class: 'adm-section' },
      h('h2', {}, '🚫 Gesperrte Gäste', bannedUsersCount),
      h('p', { class: 'adm-muted' }, 'Gesperrte Gäste können nichts mehr hochladen; ihre Fotos sind versteckt. Entsperren holt nur die Fotos zurück, die durch die Sperre versteckt wurden.'),
      bannedUsersBody,
    ),
    h('div', { class: 'adm-section' },
      h('h2', {}, '🧬 Gesperrte Fingerprints', fpBansCount),
      h('p', { class: 'adm-warn' }, '⚠️ Neue Geräte mit einem gesperrten Fingerprint starten direkt gesperrt. Gleiche Handymodelle (z. B. zwei gleiche iPhones) können denselben Fingerprint haben, dann trifft es auch Unbeteiligte. Bereits bekannte Gäste sind davon nicht betroffen.'),
      fpBansBody,
    ),
  );
}

async function loadSperren() {
  try {
    const [users, fps] = await Promise.all([
      aapi(`/api/admin/users${qs({ banned: 'true', limit: 500 })}`),
      aapi('/api/admin/device-bans'),
    ]);
    bannedUsersCount.textContent = `(${users.users.length})`;
    fpBansCount.textContent = `(${fps.bans.length})`;
    bannedUsersBody.replaceChildren(...(users.users.length ? users.users.map(bannedUserRow) : [h('div', { class: 'adm-empty' }, 'Niemand gesperrt. 🎉')]));
    fpBansBody.replaceChildren(...(fps.bans.length ? fps.bans.map(fpBanRow) : [h('div', { class: 'adm-empty' }, 'Keine Fingerprint-Sperren.')]));
  } catch (err) {
    showError(err);
  }
}

function bannedUserRow(u) {
  const btn = h('button', { class: 'vb-btn adm-toggle--show adm-btn-sm', type: 'button', 'data-testid': 'unban-user' }, '✅ Entsperren');
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    try {
      await aapi(`/api/admin/users/${u.id}/unban`, { method: 'POST', json: { fingerprint: false } });
      toast(`${u.name} ist entsperrt`, { type: 'success' });
      loadSperren();
      refreshStats();
    } catch (err) {
      btn.disabled = false;
      showError(err);
    }
  });
  return h('div', { class: 'adm-row is-banned', 'data-testid': 'banned-user-row' },
    h('div', { class: 'adm-row-main' },
      userLink(u),
      h('div', { class: 'adm-row-sub' }, `Grund: ${u.ban_reason || '–'} · gesperrt ${relTime(u.banned_at)} · ${u.photo_count} Fotos`),
    ),
    h('div', { class: 'adm-row-side' }, btn),
  );
}

function fpBanRow(b) {
  const btn = h('button', { class: 'vb-btn adm-toggle--show adm-btn-sm', type: 'button', 'data-testid': 'unban-fp' }, '✅ Entsperren');
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    try {
      await aapi(`/api/admin/device-bans/${encodeURIComponent(b.fp_hash)}`, { method: 'DELETE' });
      toast('Fingerprint entsperrt', { type: 'success' });
      loadSperren();
      refreshStats();
    } catch (err) {
      btn.disabled = false;
      showError(err);
    }
  });
  return h('div', { class: 'adm-row is-banned', 'data-testid': 'fp-ban-row' },
    h('div', { class: 'adm-row-main' },
      h('div', { class: 'adm-row-title adm-mono', title: b.fp_hash }, `🧬 ${b.fp_hash.slice(0, 16)}…`),
      h('div', { class: 'adm-row-sub' }, `Grund: ${b.reason || '–'} · seit ${relTime(b.created_at)}`,
        b.source_user_id ? [' · gesperrt über ', h('a', { href: userUrl(b.source_user_id) }, b.source_user_name || `#${b.source_user_id}`)] : null),
      b.users.length
        ? h('div', { class: 'adm-chips' }, h('span', { class: 'adm-muted' }, `${b.users.length} ${b.users.length === 1 ? 'Gerät' : 'Geräte'}:`),
          ...b.users.map((u) => h('a', { class: 'adm-chip-link', href: userUrl(u.id) }, `🙂 ${u.name}`, u.banned ? ' 🚫' : '')))
        : null,
    ),
    h('div', { class: 'adm-row-side' }, btn),
  );
}

// ============================================================ PROTOKOLL

const protokoll = { el: document.getElementById('panel-protokoll'), next: null };
const auditBody = h('tbody', {});
const auditMore = h('button', { class: 'vb-btn vb-btn--ghost vb-btn--block adm-more vb-hidden', type: 'button' }, 'Ältere Einträge');

const ACTIONS = {
  'photo.hide': '🙈 Foto runtergenommen',
  'photo.unhide': '👁 Foto wieder gezeigt',
  'photo.delete': '🗑 Foto gelöscht',
  'user.ban': '🚫 Gast gesperrt',
  'user.unban': '✅ Gast entsperrt',
  'fingerprint.ban': '🧬 Fingerprint gesperrt',
  'fingerprint.unban': '🧬 Fingerprint entsperrt',
  'admin.login': '🔐 Admin angemeldet',
  'admin.logout': '🚪 Admin abgemeldet',
  'admin.login_failed': '⚠️ Falsches Admin-Passwort',
};

function buildProtokoll() {
  auditMore.addEventListener('click', () => loadProtokoll({ more: true }));
  protokoll.el.append(
    h('div', { class: 'adm-section' },
      h('h2', {}, '📜 Protokoll'),
      h('p', { class: 'adm-muted' }, 'Wer hat wann was gemacht. „admin:…“ ist die Kennung der jeweiligen Admin-Sitzung.'),
      h('div', { class: 'adm-table-wrap' },
        h('table', { class: 'adm-table', 'data-testid': 'audit' },
          h('thead', {}, h('tr', {}, h('th', {}, 'Zeit'), h('th', {}, 'Aktion'), h('th', {}, 'Ziel'), h('th', {}, 'Details'), h('th', {}, 'Wer'))),
          auditBody,
        ),
      ),
      auditMore,
    ),
  );
}

function auditTarget(target) {
  const [kind, ...rest] = String(target || '').split(':');
  const value = rest.join(':');
  if (kind === 'user' && /^\d+$/.test(value)) return h('a', { href: userUrl(value) }, `Gast #${value}`);
  if (kind === 'photo' && value) {
    return h('a', {
      href: '#', onclick: async (event) => {
        event.preventDefault();
        try {
          const { photo } = await aapi(`/api/admin/photos/${encodeURIComponent(value)}`);
          openLightbox(() => [photo], photo);
        } catch (err) {
          toast(err.status === 404 ? 'Das Foto wurde gelöscht.' : err.message, { type: 'error' });
        }
      },
    }, `Foto ${value.slice(0, 8)}…`);
  }
  if (kind === 'fp') return h('span', { class: 'adm-mono' }, `🧬 ${value}`);
  if (kind === 'ip') return h('span', { class: 'adm-mono' }, value);
  return target || '–';
}

function auditRow(e) {
  const details = Object.entries(e.details || {}).map(([k, v]) => (k === 'reason' ? `Grund: ${v || '–'}` : `${k}: ${v}`)).join(' · ');
  return h('tr', {},
    h('td', { class: 'adm-nowrap', title: absTime(e.at) }, absTime(e.at).replace(/^\w+\.,\s*/, '')),
    h('td', {}, ACTIONS[e.action] || e.action),
    h('td', {}, auditTarget(e.target)),
    h('td', {}, details || ''),
    h('td', { class: 'adm-mono' }, e.actor),
  );
}

async function loadProtokoll({ more = false } = {}) {
  try {
    const data = await aapi(`/api/admin/audit${qs({ limit: 100, before: more ? protokoll.next : '' })}`);
    if (!more) auditBody.replaceChildren();
    auditBody.append(...data.entries.map(auditRow));
    protokoll.next = data.next;
    auditMore.classList.toggle('vb-hidden', !data.next);
  } catch (err) {
    showError(err);
  }
}

// ================================================================= tabs

const panels = {
  fotos: { el: fotos.el, load: reloadPhotos },
  gaeste: { el: gaeste.el, load: () => loadGaeste() },
  instagram: { el: insta.el, load: loadInsta },
  sperren: { el: sperren.el, load: loadSperren },
  protokoll: { el: protokoll.el, load: () => loadProtokoll() },
};

function showTab(tab) {
  state.tab = tab;
  for (const btn of document.querySelectorAll('.adm-tab')) {
    btn.setAttribute('aria-selected', String(btn.dataset.tab === tab));
  }
  for (const [name, panel] of Object.entries(panels)) panel.el.hidden = name !== tab;
  syncUrl();
  syncPill();
  const panel = panels[tab];
  if (!panel.loaded || panel.dirty) {
    panel.loaded = true;
    panel.dirty = false;
    panel.load();
  }
}

/** something changed on the server: reload this tab now if shown, else on next visit */
const reloadVisible = {};
function invalidate(tab, ms = 800) {
  const panel = panels[tab];
  if (!panel.loaded) return;
  if (state.tab !== tab) {
    panel.dirty = true;
    return;
  }
  if (!reloadVisible[tab]) reloadVisible[tab] = throttle(() => panel.load(), ms);
  reloadVisible[tab]();
}

// ================================================================ stats

const refreshStats = throttle(async () => {
  try {
    const s = await aapi('/api/admin/stats');
    document.getElementById('count-fotos').textContent = String(s.photos);
    document.getElementById('count-gaeste').textContent = String(s.guests);
    document.getElementById('count-instagram').textContent = String(s.instagram);
    document.getElementById('count-sperren').textContent = String(s.banned + s.fingerprint_bans);
  } catch (_) { /* try again on the next event */ }
}, 400);

// =============================================================== events

function onEvent(type, data) {
  switch (type) {
    case 'photo.created':
      if (matchesFilter(data.photo) && panels.fotos.loaded) {
        fotos.pending += 1;
        syncPill();
      }
      if (!fotos.userIds.has(data.photo.user.id)) refreshUserSelect();
      invalidate('instagram', 2000);
      invalidate('gaeste', 2000);
      break;
    case 'photo.hidden':
    case 'photo.unhidden':
      patchPhoto(data.photo);
      invalidate('instagram');
      break;
    case 'photo.deleted':
      dropPhoto(data.id, data.photo);
      invalidate('instagram');
      break;
    case 'user.created':
      invalidate('gaeste', 2000);
      break;
    case 'user.banned':
    case 'user.unbanned':
      for (const p of data.photos || []) patchPhoto(p);
      invalidate('gaeste');
      invalidate('sperren');
      invalidate('instagram');
      refreshUserSelect();
      break;
    case 'fingerprint.banned':
    case 'fingerprint.unbanned':
      invalidate('sperren');
      break;
    default:
      break;
  }
  invalidate('protokoll', 1500);
  refreshStats();
}

/** missed events (reconnect / polling): bring the first page up to date in place */
async function resyncPhotos() {
  if (!panels.fotos.loaded || fotos.loading) return;
  const req = fotos.reqId;
  try {
    const data = await aapi(`/api/admin/photos${qs(filterParams({ limit: PAGE }))}`);
    if (req !== fotos.reqId) return;
    const newest = photosCol.newest();
    const ids = new Set(data.photos.map((p) => p.id));
    const oldest = data.photos[data.photos.length - 1];
    let fresh = 0;
    for (const p of data.photos) {
      if (photosCol.has(p.id)) photosCol.upsert(p);
      else if (!newest || p.created_at > newest.created_at) fresh += 1;
      else photosCol.upsert(p);
    }
    for (const p of photosCol.photos) {
      if (!ids.has(p.id) && (!oldest || p.created_at >= oldest.created_at)) dropPhoto(p.id);
    }
    fotos.pending = fresh;
    syncPill();
    fotos.total = data.total;
    syncTotal();
    syncFotosEmpty();
    lightbox.refresh();
  } catch (_) { /* offline: the next poll tries again */ }
}

function onResync() {
  if (state.tab === 'fotos') resyncPhotos();
  else invalidate(state.tab, 100);
  refreshStats();
}

// ================================================================= main

async function main() {
  mountHeader();
  for (const btn of document.querySelectorAll('.adm-tab')) {
    btn.addEventListener('click', () => showTab(btn.dataset.tab));
  }
  buildFotos();
  buildGaeste();
  buildInsta();
  buildSperren();
  buildProtokoll();
  const extensions = await loadExtensions();
  fillExtSelect(extensions);
  await fillUserSelect();
  showTab(state.tab);
  refreshStats();
  connectEvents({ onEvent, onResync });
}

main().catch(showError);
