// Shared helpers for the admin screens (live, manage, user).
// CSP: no inline scripts/styles; build DOM with h(), never innerHTML with data.

import { api, ApiError, h, toast } from '/static/core/vb.js';

export { ApiError, h, toast };

// ------------------------------------------------------------------- api

let redirecting = false;

export function goLogin() {
  if (redirecting) return;
  redirecting = true;
  location.href = `/admin/login?next=${encodeURIComponent(location.pathname)}`;
}

/** api() that sends the browser to the login page when the session is gone. */
export async function aapi(path, opts) {
  try {
    return await api(path, opts);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401 && err.code === 'admin_required') {
      goLogin();
      return new Promise(() => {}); // the page is leaving; don't show errors
    }
    throw err;
  }
}

/** ?a=1&b=2 without empty values */
export function qs(params) {
  const u = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') u.set(key, String(value));
  }
  const s = u.toString();
  return s ? `?${s}` : '';
}

export function showError(err) {
  toast((err && err.message) || 'Da ist etwas schiefgelaufen.', { type: 'error', ms: 5000 });
}

export async function logout() {
  try {
    await api('/api/admin/logout', { method: 'POST' });
  } finally {
    location.href = '/admin/login';
  }
}

/** Wire the standard header: logout button + connection badge. */
export function mountHeader() {
  const btn = document.getElementById('logout');
  if (btn) btn.addEventListener('click', () => logout());
}

// ------------------------------------------------------------------ time

const DAY_FMT = new Intl.DateTimeFormat('de-DE', { weekday: 'short', hour: '2-digit', minute: '2-digit' });
const FULL_FMT = new Intl.DateTimeFormat('de-DE', {
  weekday: 'short', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit',
});

export function absTime(iso) {
  if (!iso) return '–';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : FULL_FMT.format(d);
}

export function relTime(iso) {
  if (!iso) return '–';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 45) return 'gerade eben';
  if (s < 90) return 'vor 1 Min.';
  if (s < 3600) return `vor ${Math.round(s / 60)} Min.`;
  if (s < 6 * 3600) {
    const hours = Math.floor(s / 3600);
    const mins = Math.round((s % 3600) / 60);
    return `vor ${hours} Std.${mins ? ` ${mins} Min.` : ''}`;
  }
  return DAY_FMT.format(new Date(t));
}

/** <time> that keeps its relative text fresh (see the interval below). */
export function timeEl(iso, cls = 'adm-time') {
  return h('time', { class: cls, datetime: iso || '', title: absTime(iso), 'data-rel': '1' }, relTime(iso));
}

setInterval(() => {
  for (const el of document.querySelectorAll('time[data-rel]')) el.textContent = relTime(el.getAttribute('datetime'));
}, 30000);

// ------------------------------------------------------------ extensions

let extMap = new Map();

export async function loadExtensions() {
  const data = await aapi('/api/admin/extensions');
  extMap = new Map(data.extensions.map((e) => [e.id, e]));
  return data.extensions;
}

export function extInfo(id) {
  return extMap.get(id) || { id, title: id, emoji: '📷', meta_labels: {} };
}

/** "Gefäß: bottle · Filter: sepia" using the extension's meta_labels */
export function metaText(photo) {
  const labels = extInfo(photo.extension).meta_labels || {};
  return Object.entries(photo.meta || {})
    .filter(([, v]) => v !== null && v !== '')
    .map(([k, v]) => `${labels[k] || k}: ${v}`)
    .join(' · ');
}

// ---------------------------------------------------------------- people

export function userUrl(id) {
  return `/admin/user?id=${encodeURIComponent(id)}`;
}

/** Pseudonym + @insta, links to the user page. */
export function userLink(user, { cls = '' } = {}) {
  if (!user) return h('span', { class: 'adm-muted' }, 'unbekannt');
  return h('a', { class: `adm-user ${cls}`.trim(), href: userUrl(user.id), 'data-testid': 'user-link' },
    h('span', { class: 'adm-user-name' }, `🙂 ${user.name}`, user.banned ? h('span', { class: 'adm-badge adm-badge--ban adm-badge--xs' }, 'GESPERRT') : null),
    user.instagram
      ? h('span', { class: 'adm-user-insta' }, `@${user.instagram}`)
      : h('span', { class: 'adm-user-insta adm-user-insta--none' }, 'kein Instagram'),
  );
}

export function instagramUrl(handle) {
  return `https://www.instagram.com/${encodeURIComponent(handle)}/`;
}

// ---------------------------------------------------------------- photos

export function statusBadge(photo) {
  if (photo.hidden && photo.hidden_reason === 'ban') {
    return h('span', { class: 'adm-badge adm-badge--hidden', 'data-testid': 'status', title: 'Versteckt, weil der Gast gesperrt ist' }, '🙈 Versteckt (Sperre)');
  }
  if (photo.hidden) return h('span', { class: 'adm-badge adm-badge--hidden', 'data-testid': 'status' }, '🙈 Versteckt');
  return h('span', { class: 'adm-badge adm-badge--ok', 'data-testid': 'status' }, '✓ Sichtbar');
}

/** the band across a hidden photo's thumbnail */
export function thumbFlag(photo) {
  if (!photo.hidden) return null;
  return h('span', { class: 'adm-thumb-flag' }, photo.hidden_reason === 'ban' ? 'GAST GESPERRT' : 'VERSTECKT');
}

export function photoTitle(photo) {
  const ext = extInfo(photo.extension);
  return `${ext.emoji} ${ext.title} #${photo.seq}`;
}

/** POST hide/unhide → the updated photo */
export async function setHidden(id, hide) {
  const res = await aapi(`/api/admin/photos/${encodeURIComponent(id)}/${hide ? 'hide' : 'unhide'}`, { method: 'POST' });
  return res.photo;
}

export async function deletePhoto(id) {
  await aapi(`/api/admin/photos/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

/** The big take-down / show-again button. */
export function toggleButton(photo, onToggle, { cls = '' } = {}) {
  const hidden = photo.hidden;
  return h('button', {
    class: `vb-btn adm-toggle ${hidden ? 'adm-toggle--show' : 'adm-toggle--hide'} ${cls}`.trim(),
    type: 'button',
    'data-testid': 'toggle',
    'data-action': hidden ? 'unhide' : 'hide',
    onclick: (event) => onToggle(photo, event.currentTarget),
  }, hidden ? '👁 Wieder zeigen' : '🙈 Runternehmen');
}

/** Shared toggle handler: disables the button, calls the API, reports. */
export async function runToggle(photo, button, onUpdated) {
  if (button) button.disabled = true;
  const hide = !photo.hidden;
  try {
    const updated = await setHidden(photo.id, hide);
    onUpdated(updated);
    toast(hide ? `${photoTitle(updated)} runtergenommen` : `${photoTitle(updated)} ist wieder sichtbar`, { type: 'success' });
  } catch (err) {
    if (button) button.disabled = false;
    showError(err);
  }
}

// ------------------------------------------------------- photo collection

/**
 * Keeps photos (newest first) and their DOM nodes in a container in sync.
 * render(photo) → element. upsert() replaces in place or inserts sorted.
 */
export class PhotoCollection {
  constructor(container, render) {
    this.container = container;
    this.render = render;
    this.items = new Map(); // id → { photo, el }
  }

  get size() { return this.items.size; }

  get photos() {
    return [...this.container.children]
      .map((el) => this.items.get(el.dataset.photoId))
      .filter(Boolean)
      .map((item) => item.photo);
  }

  get(id) { const item = this.items.get(id); return item ? item.photo : null; }

  has(id) { return this.items.has(id); }

  newest() { const first = this.photos[0]; return first || null; }

  oldest() { const list = this.photos; return list[list.length - 1] || null; }

  /** returns 'inserted' | 'updated' */
  upsert(photo, { append = false } = {}) {
    const existing = this.items.get(photo.id);
    const el = this.render(photo);
    el.dataset.photoId = photo.id;
    if (existing) {
      existing.el.replaceWith(el);
      this.items.set(photo.id, { photo, el });
      return 'updated';
    }
    this.items.set(photo.id, { photo, el });
    if (append) {
      this.container.append(el);
      return 'inserted';
    }
    // newest first; created_at is ISO-8601 UTC so strings compare in time order
    const next = [...this.container.children].find((child) => {
      const item = this.items.get(child.dataset.photoId);
      return item && item.photo.created_at < photo.created_at;
    });
    this.container.insertBefore(el, next || null);
    return 'inserted';
  }

  rerender(id) {
    const item = this.items.get(id);
    if (item) this.upsert(item.photo);
  }

  remove(id) {
    const item = this.items.get(id);
    if (!item) return false;
    item.el.remove();
    this.items.delete(id);
    return true;
  }

  clear() {
    this.items.clear();
    this.container.replaceChildren();
  }
}

// ---------------------------------------------------------------- copying

export async function copyText(text, label) {
  let ok = false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      ok = true;
    }
  } catch (_) { /* fall back below */ }
  if (!ok) {
    // plain http on a LAN IP has no async clipboard API
    const area = h('textarea', { class: 'adm-offscreen', readonly: true });
    area.value = text;
    document.body.append(area);
    area.select();
    try { ok = document.execCommand('copy'); } catch (_) { ok = false; }
    area.remove();
  }
  if (ok) toast(`Kopiert: ${label || text}`, { type: 'success' });
  else toast('Kopieren ging nicht. Bitte von Hand markieren.', { type: 'error' });
  return ok;
}

// ----------------------------------------------------------------- dialogs

/** Promise<boolean>. Escape / backdrop / "Abbrechen" → false. */
export function confirmDialog({ title, text, confirm = 'OK', cancel = 'Abbrechen', danger = false, extra = null }) {
  return new Promise((resolve) => {
    const done = (value) => {
      document.removeEventListener('keydown', onKey, true);
      backdrop.remove();
      resolve(value);
    };
    const onKey = (event) => {
      if (event.key === 'Escape') { event.stopPropagation(); done(false); }
    };
    const okBtn = h('button', {
      class: `vb-btn ${danger ? 'vb-btn--danger' : 'vb-btn--primary'} vb-btn--block`, type: 'button',
      'data-testid': 'confirm-ok', onclick: () => done(true),
    }, confirm);
    const dialog = h('div', { class: 'vb-sheet adm-dialog', role: 'alertdialog', 'aria-modal': 'true', 'aria-labelledby': 'adm-dialog-title' },
      h('h2', { id: 'adm-dialog-title' }, title),
      text ? h('p', { class: 'vb-muted' }, text) : null,
      extra,
      h('div', { class: 'vb-actions' },
        okBtn,
        h('button', { class: 'vb-btn vb-btn--ghost vb-btn--block', type: 'button', 'data-testid': 'confirm-cancel', onclick: () => done(false) }, cancel),
      ),
    );
    const backdrop = h('div', { class: 'vb-scrim adm-dialog-scrim', 'data-testid': 'confirm' }, dialog);
    backdrop.addEventListener('click', (event) => { if (event.target === backdrop) done(false); });
    document.addEventListener('keydown', onKey, true);
    document.body.append(backdrop);
    okBtn.focus();
  });
}

// ---------------------------------------------------------------- lightbox

/**
 * Fullscreen photo viewer.
 *   const lb = new Lightbox({ list: () => photos, actions: (photo, lb) => [nodes] });
 *   lb.open(id); lb.refresh(); lb.close();
 * The phone's back button closes it (history entry).
 */
export class Lightbox {
  constructor({ list, actions }) {
    this.list = list;
    this.actions = actions;
    this.currentId = null;
    this.el = null;
    this.onKey = (event) => this.key(event);
    this.onPop = () => this.teardown();
  }

  open(id) {
    this.currentId = id;
    if (!this.el) {
      this.el = h('div', { class: 'adm-lightbox', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Foto', 'data-testid': 'lightbox' });
      document.body.append(this.el);
      document.body.classList.add('adm-noscroll');
      document.addEventListener('keydown', this.onKey);
      history.pushState({ admLightbox: true }, '');
      window.addEventListener('popstate', this.onPop);
    }
    this.render();
  }

  get isOpen() { return Boolean(this.el); }

  /** re-render if open (after an update of the photo or the list) */
  refresh() {
    if (!this.el) return;
    if (!this.list().some((p) => p.id === this.currentId)) {
      this.close(); // the photo is gone (deleted elsewhere)
      return;
    }
    this.render();
  }

  close() {
    if (!this.el) return;
    if (history.state && history.state.admLightbox) history.back(); // → popstate → teardown
    else this.teardown();
  }

  teardown() {
    window.removeEventListener('popstate', this.onPop);
    document.removeEventListener('keydown', this.onKey);
    document.body.classList.remove('adm-noscroll');
    if (this.el) this.el.remove();
    this.el = null;
    this.currentId = null;
  }

  step(delta) {
    const list = this.list();
    const index = list.findIndex((p) => p.id === this.currentId);
    const next = list[index + delta];
    if (next) {
      this.currentId = next.id;
      this.render();
    }
  }

  key(event) {
    if (event.target && /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)) return;
    if (document.querySelector('.adm-dialog-scrim')) return;
    if (event.key === 'Escape') this.close();
    else if (event.key === 'ArrowLeft') this.step(-1);
    else if (event.key === 'ArrowRight') this.step(1);
  }

  render() {
    const list = this.list();
    const index = list.findIndex((p) => p.id === this.currentId);
    const photo = list[index];
    if (!photo) { this.close(); return; }
    const img = h('img', { src: photo.thumb_url, alt: photoTitle(photo), 'data-testid': 'lightbox-img' });
    // thumb first (instant), full size when loaded
    const full = new Image();
    full.addEventListener('load', () => { if (this.currentId === photo.id) img.src = photo.url; });
    full.src = photo.url;
    const meta = metaText(photo);
    this.el.className = `adm-lightbox${photo.hidden ? ' is-hidden' : ''}`;
    this.el.replaceChildren(
      h('div', { class: 'adm-lb-top' },
        h('button', { class: 'vb-btn adm-btn-sm', type: 'button', 'data-testid': 'lightbox-close', onclick: () => this.close() }, '✕ Schließen'),
        h('span', { class: 'adm-lb-count' }, `${index + 1} / ${list.length}`),
        h('div', { class: 'adm-lb-navs' },
          h('button', { class: 'vb-icon-btn adm-icon-sm', type: 'button', 'aria-label': 'Neueres Foto', disabled: index <= 0, onclick: () => this.step(-1) }, '‹'),
          h('button', { class: 'vb-icon-btn adm-icon-sm', type: 'button', 'aria-label': 'Älteres Foto', disabled: index >= list.length - 1, onclick: () => this.step(1) }, '›'),
        ),
      ),
      h('div', { class: 'adm-lb-stage', onclick: (event) => { if (event.target === event.currentTarget) this.close(); } },
        img,
        photo.hidden ? h('div', { class: 'adm-lb-flag' }, photo.hidden_reason === 'ban' ? '🚫 Versteckt (Gast gesperrt)' : '🙈 Versteckt: Gäste sehen es nicht') : null,
      ),
      h('div', { class: 'adm-lb-panel' },
        h('div', { class: 'adm-lb-info' },
          h('strong', { class: 'adm-lb-title' }, photoTitle(photo)),
          statusBadge(photo),
          timeEl(photo.created_at),
          h('span', { class: 'adm-muted' }, `${photo.width}×${photo.height}`),
          meta ? h('span', { class: 'adm-muted' }, meta) : null,
        ),
        h('div', { class: 'adm-lb-user' }, userLink(photo.user)),
        h('div', { class: 'adm-lb-actions' }, ...this.actions(photo, this)),
      ),
    );
  }
}

// ------------------------------------------------------------------ events

const EVENT_TYPES = [
  'photo.created', 'photo.hidden', 'photo.unhidden', 'photo.deleted',
  'user.created', 'user.banned', 'user.unbanned', 'fingerprint.banned', 'fingerprint.unbanned',
];

const CONN_TEXT = {
  connecting: 'Verbinde…',
  live: 'Echtzeit',
  reconnecting: 'Verbinde neu…',
  polling: 'Abruf alle 5 s',
};

/** Show the connection state in #conn. */
export function connBadge(state) {
  const el = document.getElementById('conn');
  if (!el) return;
  el.dataset.state = state;
  el.replaceChildren(h('span', { class: 'adm-conn-text' }, CONN_TEXT[state] || state));
  el.title = state === 'live'
    ? 'Neue Fotos erscheinen sofort.'
    : 'Keine Live-Verbindung: die Seite fragt alle paar Sekunden nach.';
}

/**
 * Server-Sent Events from /api/admin/events with auto-reconnect. While the
 * stream is down the page polls (onResync('poll')) every pollMs; after a
 * reconnect onResync('reconnect') fills the gap.
 */
export function connectEvents({ onEvent, onResync = () => {}, onStatus = connBadge, pollMs = 5000, retryMs = 4000 }) {
  let es = null;
  let pollTimer = null;
  let retryTimer = null;
  let stale = false;
  let stopped = false;

  const startPolling = () => {
    if (!pollTimer) pollTimer = setInterval(() => onResync('poll'), pollMs);
  };
  const stopPolling = () => {
    clearInterval(pollTimer);
    pollTimer = null;
  };

  async function checkSession() {
    try {
      const s = await api('/api/admin/session');
      if (!s.authenticated) goLogin();
    } catch (_) { /* offline: keep polling/retrying */ }
  }

  function open() {
    clearTimeout(retryTimer);
    if (stopped) return;
    if (typeof EventSource === 'undefined') {
      onStatus('polling');
      startPolling();
      return;
    }
    es = new EventSource('/api/admin/events');
    es.addEventListener('open', () => {
      onStatus('live');
      stopPolling();
      if (stale) {
        stale = false;
        onResync('reconnect');
      }
    });
    es.addEventListener('error', () => {
      stale = true;
      onStatus('reconnecting');
      startPolling();
      if (es && es.readyState === EventSource.CLOSED) {
        // the server refused (401, proxy error): EventSource gives up, we don't
        es.close();
        es = null;
        checkSession();
        retryTimer = setTimeout(open, retryMs);
      }
    });
    for (const type of EVENT_TYPES) {
      es.addEventListener(type, (event) => {
        let data;
        try { data = JSON.parse(event.data); } catch (_) { return; }
        try { onEvent(type, data); } catch (err) { console.warn('event handler failed', type, err); }
      });
    }
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible' || stopped) return;
    // phones freeze background tabs; the stream may be dead without an error
    if (!es || es.readyState !== EventSource.OPEN) {
      if (es) es.close();
      es = null;
      stale = true;
      open();
    } else {
      onResync('visible');
    }
  });

  onStatus('connecting');
  open();
  return {
    close() {
      stopped = true;
      stopPolling();
      clearTimeout(retryTimer);
      if (es) es.close();
    },
  };
}

/** Debounce: run fn at most once per `ms` after the last call. */
export function debounce(fn, ms) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

/**
 * Throttle: run fn once, `ms` after the first call of a burst. Unlike a
 * debounce it still fires while calls keep coming (busy party = steady events).
 */
export function throttle(fn, ms) {
  let timer = null;
  return () => {
    if (timer) return;
    timer = setTimeout(() => {
      timer = null;
      fn();
    }, ms);
  };
}

/** Parse a user agent into "iPhone · iOS 17.4 · Safari 17.4". */
export function describeUA(ua) {
  if (!ua) return 'unbekannt';
  const parts = [];
  let m;
  if ((m = ua.match(/iPhone OS (\d+)[_.](\d+)/))) parts.push('iPhone', `iOS ${m[1]}.${m[2]}`);
  else if ((m = ua.match(/iPad.*OS (\d+)[_.](\d+)/))) parts.push('iPad', `iPadOS ${m[1]}.${m[2]}`);
  else if ((m = ua.match(/Android (\d+(?:\.\d+)?)(?:;\s*([^;)]+))?/))) {
    parts.push(`Android ${m[1]}`);
    if (m[2] && !/^(K|wv|Linux|U)$/.test(m[2].trim())) parts.push(m[2].trim());
  } else if (/Macintosh/.test(ua)) parts.push('Mac');
  else if (/Windows/.test(ua)) parts.push('Windows');
  else if (/Linux/.test(ua)) parts.push('Linux');
  if (/Instagram/.test(ua)) parts.push('Instagram-App');
  else if (/FBAN|FBAV/.test(ua)) parts.push('Facebook-App');
  else if ((m = ua.match(/SamsungBrowser\/(\d+)/))) parts.push(`Samsung Internet ${m[1]}`);
  else if ((m = ua.match(/(?:CriOS|Chrome)\/(\d+)/)) && !/Edg/.test(ua)) parts.push(`Chrome ${m[1]}`);
  else if ((m = ua.match(/Edg(?:A|iOS)?\/(\d+)/))) parts.push(`Edge ${m[1]}`);
  else if ((m = ua.match(/(?:FxiOS|Firefox)\/(\d+)/))) parts.push(`Firefox ${m[1]}`);
  else if ((m = ua.match(/Version\/(\d+(?:\.\d+)?).*Safari/))) parts.push(`Safari ${m[1]}`);
  return parts.length ? parts.join(' · ') : ua.slice(0, 60);
}

// ------------------------------------------------------ shared widgets

/** <label class="adm-field"><span>Label</span>control</label> */
export function field(label, control, tag = 'label') {
  return h(tag, { class: 'adm-field' }, h('span', {}, label), control);
}

/** Segmented buttons: options = [[value, text], ...]. el.setValue(v) */
export function segmented(options, value, onChange, { label = '', testid = null } = {}) {
  const wrap = h('div', { class: 'adm-seg', role: 'group', 'aria-label': label, 'data-testid': testid });
  const set = (v) => {
    for (const b of wrap.children) b.setAttribute('aria-pressed', String(b.dataset.value === v));
  };
  for (const [v, text] of options) {
    wrap.append(h('button', {
      type: 'button', 'data-value': v, 'aria-pressed': String(v === value),
      onclick: () => { set(v); onChange(v); },
    }, text));
  }
  wrap.setValue = set;
  return wrap;
}

/** Grid tile for the management screens (selection optional). */
export function photoTile(photo, { selected = null, onSelect, onOpen, onToggle, onDelete, showUser = true }) {
  const selectable = selected !== null;
  let check = null;
  if (selectable) {
    const box = h('input', { type: 'checkbox', 'aria-label': `${photoTitle(photo)} auswählen`, 'data-testid': 'select', checked: selected });
    box.addEventListener('click', (event) => onSelect(photo, box.checked, event.shiftKey));
    check = h('label', { class: 'adm-tile-check', title: 'Auswählen (Shift-Klick: Bereich)' }, box);
  }
  const cls = ['adm-tile', photo.hidden ? 'is-hidden' : '', selected ? 'is-selected' : ''].filter(Boolean).join(' ');
  return h('article', { class: cls, 'data-testid': 'photo-tile' },
    check,
    h('button', {
      class: 'adm-thumb', type: 'button', 'aria-label': `${photoTitle(photo)} groß anzeigen`,
      'data-testid': 'thumb', onclick: () => onOpen(photo),
    },
      h('img', { src: photo.thumb_url, alt: '', loading: 'lazy', decoding: 'async' }),
      thumbFlag(photo),
    ),
    h('div', { class: 'adm-tile-body' },
      h('span', { class: 'adm-tile-title', title: photoTitle(photo) }, photoTitle(photo)),
      h('div', { class: 'adm-meta' }, timeEl(photo.created_at), statusBadge(photo)),
      showUser ? userLink(photo.user) : null,
      h('div', { class: 'adm-tile-actions' },
        toggleButton(photo, onToggle),
        h('button', {
          class: 'vb-btn adm-del adm-btn-danger-ghost', type: 'button', title: 'Endgültig löschen',
          'aria-label': `${photoTitle(photo)} löschen`, 'data-testid': 'delete', onclick: () => onDelete(photo),
        }, '🗑', h('span', { class: 'adm-del-label' }, ' Löschen')),
      ),
    ),
  );
}

/** Download / copy handle / toggle / delete, for the management lightbox. */
export function managementActions(photo, { onToggle, onDelete }) {
  return [
    h('a', {
      class: 'vb-btn', href: `${photo.url}?download=1`, download: `${photo.extension}-${String(photo.seq).padStart(5, '0')}.jpg`,
      'data-testid': 'download',
    }, '⬇ Download'),
    photo.user && photo.user.instagram
      ? h('button', {
        class: 'vb-btn vb-btn--cool', type: 'button', 'data-testid': 'copy-handle',
        onclick: () => copyText(`@${photo.user.instagram}`),
      }, `📋 @${photo.user.instagram} kopieren`)
      : null,
    toggleButton(photo, onToggle),
    h('button', {
      class: 'vb-btn vb-btn--danger', type: 'button', 'data-testid': 'lightbox-delete', onclick: () => onDelete(photo),
    }, '🗑 Löschen'),
  ];
}

/**
 * Ask, then delete for good. Resolves the ids that are gone now
 * (deleted, or already missing on the server).
 */
export async function confirmAndDelete(photos) {
  const n = photos.length;
  if (!n) return [];
  const ok = await confirmDialog({
    title: n === 1 ? `${photoTitle(photos[0])} endgültig löschen?` : `${n} Fotos endgültig löschen?`,
    text: 'Die Bilddateien werden sofort vom Server gelöscht. Das lässt sich nicht rückgängig machen. '
      + 'Zum Verstecken reicht „Runternehmen“.',
    confirm: n === 1 ? '🗑 Endgültig löschen' : `🗑 ${n} Fotos endgültig löschen`,
    danger: true,
  });
  if (!ok) return [];
  const ids = photos.map((p) => p.id);
  const gone = [];
  try {
    for (let i = 0; i < ids.length; i += 200) {
      const res = await aapi('/api/admin/photos/bulk', { method: 'POST', json: { ids: ids.slice(i, i + 200), action: 'delete' } });
      gone.push(...res.changed, ...res.missing);
    }
    toast(n === 1 ? 'Foto gelöscht' : `${gone.length} Fotos gelöscht`, { type: 'success' });
  } catch (err) {
    showError(err);
  }
  return gone;
}
