// User page: who is this guest, which device, all uploads, ban / unban.

import {
  aapi, absTime, ApiError, autoBanSource, banMark, confirmAndDelete, confirmDialog, connectEvents, copyText,
  describeUA, field, focusFirst, h, instagramUrl, Lightbox, loadExtensions, managementActions, mountHeader,
  PhotoCollection, photoTile, refocusAfterRemoval, relTime, runToggle, showError, toast, unbanToast, userUrl,
} from './admin.js';
import { guestUploadsPanel } from './uploadcontrols.js';

const root = document.getElementById('user-root');
const rawId = new URLSearchParams(location.search).get('id') || '';
const userId = /^[1-9]\d{0,15}$/.test(rawId) ? rawId : null;

let data = null; // { user, fingerprints, sharing, photos }

const grid = h('div', { class: 'adm-grid', 'data-testid': 'user-photos' });
const photosCol = new PhotoCollection(grid, (photo) => photoTile(photo, {
  onOpen: (p) => lightbox.open(p.id),
  onToggle,
  onDelete: (p) => deletePhotos([p]),
  showUser: false, // it's this guest's page
}));
const lightbox = new Lightbox({
  list: () => photosCol.photos,
  actions: (photo) => managementActions(photo, { onToggle, onDelete: (p) => deletePhotos([p]) }),
});
const uploadsCount = h('span', { class: 'adm-muted', 'data-testid': 'uploads-count' });
const uploadsEmpty = h('div', { class: 'adm-empty vb-hidden' }, h('strong', {}, 'Keine Uploads.'), 'Dieser Gast hat (noch) keine Fotos hochgeladen.');

function onToggle(photo, button) {
  runToggle(photo, button, (updated) => {
    photosCol.upsert(updated);
    lightbox.refresh();
    syncUploads();
  });
}

async function deletePhotos(list) {
  const before = photosCol.photos.map((p) => p.id);
  const gone = await confirmAndDelete(list);
  for (const id of gone) photosCol.remove(id);
  lightbox.refresh();
  syncUploads();
  refocusAfterRemoval(before, gone);
}

function syncUploads() {
  const list = photosCol.photos;
  const hidden = list.filter((p) => p.hidden).length;
  uploadsCount.textContent = list.length ? `(${list.length}${hidden ? `, davon ${hidden} versteckt` : ''})` : '(0)';
  uploadsEmpty.classList.toggle('vb-hidden', list.length > 0);
}

function dl(rows) {
  return h('dl', { class: 'adm-dl' }, ...rows.filter(Boolean).flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)]));
}

function sharingText(n) {
  return n === 1 ? '1 anderes Gerät teilt diesen Fingerprint' : `${n} andere Geräte teilen diesen Fingerprint`;
}

// ------------------------------------------------------------- panels

function profilePanel(u) {
  return h('section', { class: 'adm-panel', 'data-testid': 'profile' },
    h('h1', { class: 'adm-profile-name', 'data-testid': 'user-name' }, `🙂 ${u.name}`),
    h('div', { class: 'adm-profile-insta' },
      u.banned
        ? h('span', { class: 'adm-badge adm-badge--ban', 'data-testid': 'user-status' }, u.auto_banned ? '🚫 AUTO-GESPERRT' : '🚫 GESPERRT')
        : h('span', { class: 'adm-badge adm-badge--ok', 'data-testid': 'user-status' }, '✓ Aktiv'),
      u.instagram ? h('span', { class: 'adm-user-insta', 'data-testid': 'user-insta' }, `@${u.instagram}`) : h('span', { class: 'adm-muted' }, 'kein Instagram angegeben'),
    ),
    u.instagram
      ? h('div', { class: 'adm-profile-insta' },
        h('button', { class: 'vb-btn vb-btn--cool adm-btn-sm', type: 'button', onclick: () => copyText(`@${u.instagram}`) }, '📋 Handle kopieren'),
        h('a', { class: 'vb-btn adm-btn-sm', href: instagramUrl(u.instagram), target: '_blank', rel: 'noopener noreferrer' }, 'Profil ↗'),
      )
      : null,
    dl([
      ['Einwilligung', `${absTime(u.consent_at)} (Version ${u.consent_version})`],
      ['Erstmals da', absTime(u.created_at)],
      ['Zuletzt da', h('span', { title: absTime(u.last_seen_at) }, relTime(u.last_seen_at))],
      ['Fotos', String(u.photo_count)],
      ['Gast-Nr.', `#${u.id}`],
    ]),
  );
}

function banPanel(u) {
  const reason = h('input', {
    class: 'vb-input', id: 'ban-reason', type: 'text', maxlength: '200', autocomplete: 'off',
    placeholder: 'z. B. unpassende Fotos', 'data-testid': 'ban-reason',
  });
  const fpBox = h('input', { type: 'checkbox', id: 'ban-fp', 'data-testid': 'ban-fp', disabled: !u.fp_hash });
  const current = data.fingerprints.find((f) => f.current);
  const shared = current ? current.users.length : 0;
  const warn = h('div', { class: 'adm-warn', 'data-testid': 'fp-warning' },
    h('strong', {}, '⚠️ Vorsicht mit dem Fingerprint. '),
    'Er ist nur ein Geräte-Merkmal, keine Identität: gleiche Handymodelle (z. B. zwei gleiche iPhones) haben oft denselben. '
    + 'Jedes neue Gerät mit diesem Fingerprint startet dann gesperrt, auch Unbeteiligte. Nur für Störer, die sich immer wieder neu anmelden.',
    shared ? h('div', {}, h('strong', {}, `${sharingText(shared)} schon.`), ' Diese bereits bekannten Gäste bleiben unberührt.') : null,
  );
  const btn = h('button', { class: 'vb-btn vb-btn--danger vb-btn--block', type: 'button', 'data-testid': 'ban' }, '🚫 Gast sperren');
  btn.addEventListener('click', async () => {
    const withFp = fpBox.checked;
    const visible = photosCol.photos.filter((p) => !p.hidden).length;
    const ok = await confirmDialog({
      title: `${u.name} sperren?`,
      text: `${visible === 1 ? 'Das sichtbare Foto wird' : `Alle ${visible} sichtbaren Fotos werden`} versteckt, weitere Uploads sind blockiert.`
        + `${withFp ? ' Zusätzlich wird der Fingerprint gesperrt.' : ''}`,
      confirm: withFp ? '🚫 Gast + Fingerprint sperren' : '🚫 Gast sperren',
      danger: true,
    });
    if (!ok) return;
    btn.disabled = true;
    try {
      const res = await aapi(`/api/admin/users/${u.id}/ban`, { method: 'POST', json: { reason: reason.value.trim(), fingerprint: withFp } });
      toast(res.fingerprint_banned ? 'Gast und Fingerprint gesperrt' : 'Gast gesperrt', { type: 'success' });
      await load();
      focusPanel('ban-panel');
    } catch (err) {
      btn.disabled = false;
      showError(err);
    }
  });
  return h('section', { class: 'adm-panel', 'data-testid': 'ban-panel' },
    h('h2', { tabindex: '-1' }, '🚫 Sperren'),
    h('div', { class: 'adm-stack' },
      h('p', { class: 'adm-muted' }, 'Versteckt alle Fotos dieses Gastes und blockiert weitere Uploads. Lässt sich jederzeit rückgängig machen.'),
      field('Grund (optional, nur für euch)', reason),
      h('label', { class: 'adm-check', for: 'ban-fp' }, fpBox,
        h('span', {}, 'Fingerprint auch sperren', u.fp_hash ? null : h('span', { class: 'adm-muted' }, ' (kein Fingerprint bekannt)'))),
      warn,
      btn,
    ),
  );
}

/** other identities that only started banned because of these fingerprints */
function autoBannedPeers(fps) {
  const ids = new Set();
  for (const f of fps) for (const o of f.users) if (o.auto_banned) ids.add(o.id);
  ids.delete(data.user.id);
  return ids.size;
}

function bannedPanel(u) {
  const bannedFps = data.fingerprints.filter((f) => f.banned);
  const peers = autoBannedPeers(bannedFps);
  const fpBox = bannedFps.length ? h('input', { type: 'checkbox', id: 'unban-fp', 'data-testid': 'unban-fp' }) : null;
  const btn = h('button', { class: 'vb-btn adm-toggle--show vb-btn--block', type: 'button', 'data-testid': 'unban' }, '✅ Entsperren');
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    try {
      const res = await aapi(`/api/admin/users/${u.id}/unban`, { method: 'POST', json: { fingerprint: Boolean(fpBox && fpBox.checked) } });
      unbanToast(res.fingerprints_unbanned.length ? 'Gast und Fingerprint entsperrt' : 'Gast entsperrt', res.users_unbanned);
      await load();
      focusPanel('ban-panel');
    } catch (err) {
      btn.disabled = false;
      showError(err);
    }
  });
  const auto = u.auto_banned
    ? h('div', { class: 'adm-warn adm-warn--auto', 'data-testid': 'auto-ban-note' },
      h('strong', {}, '🧬 Automatisch gesperrt. '),
      `Dieses Gerät hat sich neu angemeldet, mit ${autoBanSource(u)}. `
      + 'Gleiche Handymodelle haben oft denselben Fingerprint: vielleicht ist das jemand anderes. Entsperren betrifft nur dieses Gerät.')
    : null;
  return h('section', { class: 'adm-panel adm-panel--ban', 'data-testid': 'ban-panel' },
    h('h2', { tabindex: '-1' }, u.auto_banned ? '🚫 Automatisch gesperrt' : '🚫 Gesperrt'),
    h('div', { class: 'adm-stack' },
      auto,
      dl([
        ['Seit', absTime(u.banned_at)],
        ['Grund', u.ban_reason || '–'],
      ]),
      h('p', { class: 'adm-muted' }, 'Entsperren zeigt die Fotos wieder, die durch die Sperre versteckt wurden. Von Hand runtergenommene bleiben versteckt.'),
      fpBox
        ? h('label', { class: 'adm-check', for: 'unban-fp' }, fpBox,
          h('span', {}, `Fingerprint-Sperre auch aufheben (${bannedFps.length})`,
            peers ? h('span', { class: 'adm-muted adm-check-hint' }, ` Entsperrt auch ${peers} ${peers === 1 ? 'weiteres Gerät, das' : 'weitere Geräte, die'} nur deshalb gesperrt ${peers === 1 ? 'ist' : 'sind'}.`) : null))
        : null,
      btn,
    ),
  );
}

function devicePanel(u) {
  const c = u.fp_components || {};
  const gpu = [c.gl_renderer, c.gl_vendor && c.gl_vendor !== c.gl_renderer ? `(${c.gl_vendor})` : ''].filter(Boolean).join(' ');
  return h('section', { class: 'adm-panel', 'data-testid': 'device' },
    h('h2', {}, '📱 Gerät'),
    dl([
      ['Gerät', describeUA(u.user_agent || c.ua)],
      ['Bildschirm', c.screen || '–'],
      ['Grafik', gpu || '–'],
      ['Sprache', c.languages || '–'],
      ['Zeitzone', c.timezone || '–'],
      ['Leistung', [c.cores ? `${c.cores} Kerne` : '', c.memory ? `${c.memory} GB RAM` : ''].filter(Boolean).join(' · ') || '–'],
      ['IP', u.first_ip && u.first_ip !== u.last_ip ? `${u.last_ip} (zuerst ${u.first_ip})` : u.last_ip || '–'],
      ['User-Agent', h('span', { class: 'adm-mono' }, u.user_agent || c.ua || '–')],
    ]),
  );
}

function fingerprintPanel() {
  const fps = data.fingerprints;
  return h('section', { class: 'adm-panel', 'data-testid': 'fingerprints' },
    h('h2', { tabindex: '-1' }, `🧬 Fingerprints (${fps.length})`),
    h('p', { class: 'adm-muted' }, 'Ein Hinweis, kein Beweis: gleiche Handymodelle haben oft denselben Fingerprint.'),
    fps.length ? null : h('p', {}, 'Kein Fingerprint bekannt.'),
    ...fps.map((f) => {
      let unban = null;
      if (f.banned) {
        unban = h('button', { class: 'vb-btn adm-toggle--show adm-btn-sm', type: 'button', 'data-testid': 'unban-fingerprint' }, '✅ Fingerprint entsperren');
        unban.addEventListener('click', async () => {
          unban.disabled = true;
          try {
            const res = await aapi(`/api/admin/device-bans/${encodeURIComponent(f.fp_hash)}`, { method: 'DELETE' });
            // an auto-banned guest's own page: lifting the ban releases this guest too
            const others = res.users_unbanned.filter((o) => o.id !== data.user.id);
            unbanToast(others.length < res.users_unbanned.length ? 'Fingerprint und Gast entsperrt' : 'Fingerprint entsperrt', others);
            await load();
            focusPanel('fingerprints');
          } catch (err) {
            unban.disabled = false;
            showError(err);
          }
        });
      }
      return h('div', { class: 'adm-fp', 'data-testid': 'fp' },
        h('div', { class: 'adm-fp-head' },
          h('span', { class: 'adm-mono', title: f.fp_hash }, `${f.fp_hash.slice(0, 16)}…`),
          f.current ? h('span', { class: 'adm-badge adm-badge--info' }, 'aktuell') : null,
          f.banned ? h('span', { class: 'adm-badge adm-badge--ban' }, 'GESPERRT') : null,
        ),
        h('div', { class: 'adm-muted' }, `erstmals ${absTime(f.first_seen)} · zuletzt ${relTime(f.last_seen)}`),
        f.users.length
          ? h('div', { class: 'adm-stack' },
            h('strong', { 'data-testid': 'fp-shared' }, `${sharingText(f.users.length)}:`),
            h('div', { class: 'adm-chips' }, ...f.users.map((o) => h('a', { class: 'adm-chip-link', href: userUrl(o.id) },
              `🙂 ${o.name}`, o.instagram ? ` · @${o.instagram}` : '', banMark(o)))))
          : h('div', { class: 'adm-muted' }, 'Kein anderes Gerät hat diesen Fingerprint.'),
        unban,
      );
    }),
  );
}

// ------------------------------------------------------------- render

/** after a ban/unban rebuilt the page: focus that panel's heading */
function focusPanel(testid) {
  focusFirst(root.querySelector(`[data-testid="${testid}"] h2`));
}

/** a selector that finds the focused control again after a re-render */
function focusRef(el) {
  if (el.id) return `#${CSS.escape(el.id)}`;
  if (el.dataset.testid) return `[data-testid="${CSS.escape(el.dataset.testid)}"]`;
  const panel = el.tagName === 'H2' && el.closest('[data-testid]');
  return panel ? `[data-testid="${CSS.escape(panel.dataset.testid)}"] h2` : null;
}

/** what the admin is in the middle of: focused control, typed ban reason */
function snapshot() {
  const active = document.activeElement;
  const reason = root.querySelector('#ban-reason');
  const fpBox = root.querySelector('#ban-fp');
  return {
    focus: active && active !== root && root.contains(active) ? focusRef(active) : null,
    reason: reason ? reason.value : '',
    fp: Boolean(fpBox && fpBox.checked),
  };
}

function restore(snap) {
  const reason = root.querySelector('#ban-reason');
  if (reason && snap.reason) reason.value = snap.reason;
  const fpBox = root.querySelector('#ban-fp');
  if (fpBox && !fpBox.disabled && snap.fp) fpBox.checked = true;
  if (snap.focus) focusFirst(() => root.querySelector(snap.focus));
}

function render() {
  const u = data.user;
  const snap = snapshot();
  document.title = `${u.name} · Admin`;
  const lightboxOpen = lightbox.isOpen;
  photosCol.clear();
  for (const p of data.photos) photosCol.upsert(p, { append: true });
  syncUploads();
  const area = (el, name) => {
    el.classList.add(`adm-area-${name}`);
    return el;
  };
  // phone order: who, ban, photos, then the forensic details
  root.replaceChildren(
    h('div', { class: 'adm-userpage' },
      area(profilePanel(u), 'profile'),
      area(guestUploadsPanel(u, { onChanged: load }), 'pause'),
      area(u.banned ? bannedPanel(u) : banPanel(u), 'ban'),
      h('section', { class: 'adm-section adm-area-uploads', 'data-testid': 'uploads' },
        h('h2', {}, '📸 Uploads', uploadsCount),
        grid,
        uploadsEmpty,
      ),
      area(fingerprintPanel(), 'fps'),
      area(devicePanel(u), 'device'),
    ),
  );
  if (lightboxOpen) lightbox.refresh();
  else restore(snap);
}

async function load() {
  try {
    data = await aapi(`/api/admin/users/${userId}`);
    render();
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      root.replaceChildren(h('div', { class: 'adm-empty' }, h('strong', {}, 'Gast nicht gefunden.'), h('a', { href: '/admin/manage?tab=gaeste' }, 'Zur Gästeliste')));
      return;
    }
    showError(err);
  }
}

/** what the side panels show; photos are synced in place */
function panelKey(d) {
  return JSON.stringify([
    d.user.banned, d.user.ban_reason, d.user.instagram, d.user.fp_hash, d.user.auto_ban,
    d.user.uploads_paused, d.user.uploads_paused_source,
    d.fingerprints.map((f) => [f.fp_hash, f.banned, f.users.map((o) => [o.id, o.banned, o.auto_banned])]),
  ]);
}

/** reload without throwing away what the admin is typing, unless the panels changed */
async function refresh() {
  try {
    const fresh = await aapi(`/api/admin/users/${userId}`);
    const changed = !data || panelKey(fresh) !== panelKey(data);
    data = fresh;
    if (changed) {
      render();
      return;
    }
    const ids = new Set(fresh.photos.map((p) => p.id));
    for (const p of photosCol.photos) if (!ids.has(p.id)) photosCol.remove(p.id);
    for (const p of fresh.photos) photosCol.upsert(p);
    lightbox.refresh();
    syncUploads();
  } catch (_) { /* offline: the next poll tries again */ }
}

function onEvent(type, payload) {
  if (!data) return;
  if (type === 'photo.created') {
    if (payload.photo.user.id === data.user.id) {
      photosCol.upsert(payload.photo);
      syncUploads();
    }
  } else if (type === 'photo.hidden' || type === 'photo.unhidden') {
    if (photosCol.has(payload.photo.id)) {
      photosCol.upsert(payload.photo);
      lightbox.refresh();
      syncUploads();
    }
  } else if (type === 'photo.deleted') {
    if (photosCol.remove(payload.id)) {
      lightbox.refresh();
      syncUploads();
    }
  } else if (type === 'user.banned' || type === 'user.unbanned') {
    if (payload.user.id === data.user.id) load();
    // a device sharing a fingerprint (e.g. auto-unbanned with a fingerprint ban)
    else if (data.fingerprints.some((f) => f.users.some((o) => o.id === payload.user.id))) refresh();
  } else if (type.startsWith('fingerprint.')) {
    refresh();
  } else if (type === 'user.uploads_changed') {
    if (payload.users.some((x) => x.id === data.user.id)) refresh();
  }
}

async function main() {
  mountHeader();
  if (!userId) {
    root.replaceChildren(h('div', { class: 'adm-empty' }, h('strong', {}, 'Kein Gast ausgewählt.'), h('a', { href: '/admin/manage?tab=gaeste' }, 'Zur Gästeliste')));
    return;
  }
  await loadExtensions();
  await load();
  connectEvents({ onEvent, onResync: refresh });
}

main().catch(showError);
