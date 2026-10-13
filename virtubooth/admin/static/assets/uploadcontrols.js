// Upload controls (API: virtubooth/admin/upload_controls.py).
//
//   mountUploadControls(slot)        "Uploads" chip for the live/management header:
//                                    status line, tap → sheet with the two switches
//   guestUploadsPanel(user, {...})   user page: pause / allow this guest
//   pausedBadge(user)                "⏸ Uploads pausiert" for guest lists
//   UPLOAD_AUDIT_LABELS              audit log action names
//
// State comes from the API and stays live through the page's event stream
// (onAdminEvent), so every open admin screen shows the same thing.

import { aapi, absTime, h, onAdminEvent, showError, throttle, toast, userUrl } from './admin.js';

export const UPLOAD_AUDIT_LABELS = {
  'user.uploads_pause': '⏸ Uploads des Gasts pausiert',
  'user.uploads_unpause': '▶ Uploads des Gasts erlaubt',
  'uploads.lock_on': '⏸ Neue Gäste pausiert',
  'uploads.lock_off': '▶ Pause für neue Gäste beendet',
  'uploads.stop': '⏹ Alle Uploads gestoppt',
  'uploads.resume': '▶ Uploads laufen wieder',
};

const PAUSED_LIST_URL = '/admin/manage?tab=gaeste&show=paused';

// ------------------------------------------------------------------ state

const state = { stop: null, pause: null };
const listeners = new Set();

function notify() {
  for (const fn of [...listeners]) fn();
}

async function fetchState() {
  const [stop, pause] = await Promise.all([aapi('/api/admin/upload-stop'), aapi('/api/admin/upload-pause')]);
  state.stop = stop;
  state.pause = pause;
  notify();
}
const refresh = throttle(() => fetchState().catch(() => { /* the next event or poll tries again */ }), 300);

let hooked = false;
function listen() {
  if (hooked) return;
  hooked = true;
  onAdminEvent((type, data) => {
    if (type === 'settings.upload_stop') {
      state.stop = data.upload_stop;
      notify();
    } else if (type === 'settings.upload_pause') {
      state.pause = data.upload_pause;
      notify();
    } else if (type === 'user.uploads_changed') {
      syncPausedMarks(data.users || []);
      refresh(); // counts
    } else if ((type === 'user.created' && data.uploads_paused) || type === 'resync') {
      refresh();
    }
  });
}

const CLOCK = new Intl.DateTimeFormat('de-DE', { hour: '2-digit', minute: '2-digit' });
const DAY_CLOCK = new Intl.DateTimeFormat('de-DE', { weekday: 'short', hour: '2-digit', minute: '2-digit' });

/** "22:14", or "Fr., 22:14" when it wasn't today */
export function clock(iso) {
  const d = new Date(iso || '');
  if (Number.isNaN(d.getTime())) return '–';
  return (d.toDateString() === new Date().toDateString() ? CLOCK : DAY_CLOCK).format(d);
}

function guests(n) {
  return `${n} ${n === 1 ? 'Gast' : 'Gäste'}`;
}

/** { kind: 'loading' | 'ok' | 'paused' | 'stopped', text } */
export function uploadStatus() {
  const { stop, pause } = state;
  if (!stop || !pause) return { kind: 'loading', text: 'Uploads …' };
  if (stop.enabled) {
    return {
      kind: 'stopped',
      text: `⏹ Alle Uploads gestoppt seit ${clock(stop.since)}${pause.enabled ? ' · ⏸ neue Gäste pausiert' : ''}`,
    };
  }
  if (pause.enabled) {
    return { kind: 'paused', text: `⏸ Neue Gäste pausiert seit ${clock(pause.since)} · ${pause.affected} betroffen` };
  }
  return { kind: 'ok', text: '🟢 Uploads laufen' };
}

// -------------------------------------------------------- header + sheet

/** The "Uploads" chip; tap opens the switches. */
export function mountUploadControls(slot) {
  if (!slot) return;
  listen();
  const chip = h('button', {
    class: 'adm-uploads-chip', type: 'button', 'data-testid': 'uploads-chip', 'aria-haspopup': 'dialog',
    title: 'Uploads steuern', onclick: () => openSheet(),
  });
  const render = () => {
    const status = uploadStatus();
    chip.dataset.state = status.kind;
    chip.replaceChildren(
      h('span', { class: 'adm-uploads-chip-text', 'data-testid': 'uploads-chip-text' }, status.text),
      h('span', { class: 'adm-uploads-chip-more', 'aria-hidden': 'true' }, '›'),
    );
  };
  listeners.add(render);
  render();
  slot.replaceChildren(chip);
  fetchState().catch(showError);
}

let openSheetEl = null;

function openSheet() {
  if (openSheetEl) return;
  let view = 'main'; // 'main' | 'end-pause'
  let busy = false;
  const body = h('div', {});
  const dialog = h('div', {
    class: 'vb-sheet adm-dialog adm-uploads-sheet', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'adm-uploads-title',
  }, body);
  const scrim = h('div', { class: 'vb-scrim adm-dialog-scrim', 'data-testid': 'uploads-sheet' }, dialog);

  const close = () => {
    listeners.delete(render);
    document.removeEventListener('keydown', onKey, true);
    scrim.remove();
    openSheetEl = null;
  };
  const onKey = (event) => {
    if (event.key !== 'Escape') return;
    event.stopPropagation();
    if (view === 'main') close();
    else show('main');
  };
  const show = (next) => {
    view = next;
    render();
  };

  async function run(request, done) {
    busy = true;
    render();
    try {
      done(await request());
    } catch (err) {
      showError(err);
    } finally {
      busy = false;
      render();
    }
  }

  const setStop = (enabled) => run(
    () => aapi('/api/admin/upload-stop', { method: 'POST', json: { enabled } }),
    (res) => {
      state.stop = res;
      notify();
      toast(enabled ? '⏹ Alle Uploads gestoppt' : '▶ Uploads laufen wieder', { type: 'success' });
    },
  );
  const startPause = () => run(
    () => aapi('/api/admin/upload-pause', { method: 'POST', json: { enabled: true } }),
    (res) => {
      state.pause = res;
      notify();
      toast('⏸ Wer ab jetzt neu dazukommt, kann nichts hochladen', { type: 'success' });
    },
  );
  const endPause = (restore) => run(
    () => aapi('/api/admin/upload-pause', { method: 'POST', json: { enabled: false, restore } }),
    (res) => {
      state.pause = res;
      view = 'main';
      notify();
      let text = '▶ Neue Gäste können wieder hochladen';
      if (res.restored) text = `▶ ${guests(res.restored)} wieder freigeschaltet`;
      else if (res.kept) text += ` – ${res.kept} ${res.kept === 1 ? 'bleibt' : 'bleiben'} pausiert`;
      toast(text, { type: 'success' });
    },
  );

  const head = (title) => h('div', { class: 'adm-uploads-head' },
    h('h2', { id: 'adm-uploads-title' }, title),
    h('button', {
      class: 'vb-icon-btn adm-icon-sm', type: 'button', 'aria-label': 'Schließen', 'data-testid': 'uploads-close', onclick: close,
    }, '✕'),
  );

  function option({ name, title, on, stateText, text, onToggle }) {
    const labelId = `adm-uploads-${name}-label`;
    return h('section', { class: `adm-uploads-opt adm-uploads-opt--${name}${on ? ' is-on' : ''}`, 'data-testid': `upload-${name}` },
      h('div', { class: 'adm-uploads-opt-row' },
        h('div', { class: 'adm-uploads-opt-title' },
          h('strong', { id: labelId }, title),
          h('span', { class: 'adm-uploads-opt-state', 'data-testid': `upload-${name}-state` }, stateText),
        ),
        h('button', {
          class: 'adm-switch', type: 'button', role: 'switch', 'aria-checked': String(on), 'aria-labelledby': labelId,
          'data-testid': `upload-${name}-switch`, disabled: busy, onclick: onToggle,
        }, h('span', { class: 'adm-switch-knob', 'aria-hidden': 'true' })),
      ),
      h('p', { class: 'adm-muted' }, text),
    );
  }

  function mainView() {
    const { stop, pause } = state;
    const status = uploadStatus();
    if (!stop || !pause) return [head('Uploads'), h('div', { class: 'adm-loading' }, h('div', { class: 'vb-spinner' }))];
    return [
      head('Uploads'),
      h('p', { class: 'adm-uploads-status', 'data-state': status.kind, 'data-testid': 'uploads-status' }, status.text),
      option({
        name: 'stop',
        title: '⏹ Alle Uploads stoppen',
        on: stop.enabled,
        stateText: stop.enabled ? `Gestoppt seit ${clock(stop.since)}` : 'Aus',
        text: 'Niemand kann hochladen, auch bekannte Gäste nicht. Für kurze Pausen, z. B. bei einer Flut '
          + 'unpassender Fotos. Einzelne Pausen und „Neue Gäste pausieren“ bleiben dabei, wie sie sind.',
        onToggle: () => setStop(!stop.enabled),
      }),
      option({
        name: 'pause',
        title: '⏸ Neue Gäste pausieren',
        on: pause.enabled,
        stateText: pause.enabled
          ? `Neue Gäste können seit ${clock(pause.since)} nichts hochladen · ${pause.affected} betroffen`
          : 'Aus',
        text: 'Wer ab jetzt neu dazukommt, kann nichts hochladen. Bekannte Gäste laden weiter hoch. '
          + 'Beim Ausschalten entscheidest du, ob die Betroffenen freigeschaltet werden.',
        onToggle: () => (pause.enabled ? show('end-pause') : startPause()),
      }),
      pause.paused_total
        ? h('a', { class: 'adm-uploads-link', href: PAUSED_LIST_URL, 'data-testid': 'uploads-paused-list' },
          `⏸ ${guests(pause.paused_total)} pausiert · ansehen ›`)
        : null,
      h('p', { class: 'adm-muted adm-uploads-foot' }, 'Einzelne Gäste pausierst du auf ihrer Seite (Gäste › Name).'),
    ];
  }

  function endPauseView() {
    const n = state.pause ? state.pause.affected : 0;
    const restoreLabel = n === 1
      ? '▶ Den 1 in der Pause beigetretenen Gast wieder freischalten'
      : `▶ Alle ${n} in der Pause beigetretenen Gäste wieder freischalten`;
    const keepLabel = n === 1
      ? 'Nur ab jetzt wieder erlauben – der eine bleibt pausiert'
      : `Nur ab jetzt wieder erlauben – die ${n} bleiben pausiert`;
    return [
      head('Pause für neue Gäste beenden'),
      h('p', { 'data-testid': 'pause-end-text' }, n
        ? `${n === 1 ? '1 Gast ist' : `${n} Gäste sind`} beigetreten, während die Pause lief, und `
          + `${n === 1 ? 'kann' : 'können'} noch nichts hochladen. Was soll mit ${n === 1 ? 'ihm' : 'ihnen'} passieren?`
        : 'Während der Pause ist niemand neu dazugekommen.'),
      h('div', { class: 'vb-actions' },
        h('button', {
          class: 'vb-btn vb-btn--primary vb-btn--block adm-uploads-choice', type: 'button', 'data-testid': 'pause-end-restore',
          disabled: busy, onclick: () => endPause(true),
        }, n ? restoreLabel : '▶ Pause beenden'),
        n
          ? h('button', {
            class: 'vb-btn vb-btn--block adm-uploads-choice', type: 'button', 'data-testid': 'pause-end-keep',
            disabled: busy, onclick: () => endPause(false),
          }, keepLabel)
          : null,
        h('button', {
          class: 'vb-btn vb-btn--ghost vb-btn--block', type: 'button', 'data-testid': 'pause-end-back', onclick: () => show('main'),
        }, 'Zurück'),
      ),
      h('p', { class: 'adm-muted adm-uploads-foot' }, 'Von Hand pausierte Gäste bleiben in jedem Fall pausiert.'),
    ];
  }

  function render() {
    body.replaceChildren(...(view === 'main' ? mainView() : endPauseView()));
  }

  scrim.addEventListener('click', (event) => { if (event.target === scrim) close(); });
  document.addEventListener('keydown', onKey, true);
  listeners.add(render);
  render();
  document.body.append(scrim);
  openSheetEl = scrim;
  const first = dialog.querySelector('.adm-switch, button');
  if (first) first.focus();
  refresh();
}

// ------------------------------------------------------------ one guest

/** "⏸ Uploads pausiert" badge for guest rows (null when not paused). */
export function pausedBadge(user) {
  if (!user.uploads_paused) return null;
  return h('span', {
    class: 'adm-badge adm-badge--pause adm-badge--xs', 'data-testid': 'paused-badge',
    title: user.uploads_paused_source === 'new_guest_lock' ? 'automatisch: in der Pause für neue Gäste beigetreten' : 'manuell pausiert',
  }, '⏸ Uploads pausiert');
}

function pauseSource(u) {
  if (u.uploads_paused_source === 'new_guest_lock') {
    const pause = state.pause;
    if (pause && pause.enabled && pause.period === u.uploads_lock_period) {
      return `automatisch: neue Gäste pausiert seit ${clock(pause.since)}`;
    }
    return `automatisch: beigetreten während der Pause für neue Gäste (${absTime(u.uploads_paused_at)})`;
  }
  return `manuell pausiert · seit ${clock(u.uploads_paused_at)}`;
}

/** User page panel: status, where the pause came from, allow / pause. */
export function guestUploadsPanel(u, { onChanged = () => {} } = {}) {
  listen();
  const panel = h('section', { class: 'adm-panel adm-uploads-guest', 'data-testid': 'guest-uploads' });
  let busy = false;
  let attached = false;

  const toggle = async () => {
    busy = true;
    render();
    try {
      const res = await aapi(`/api/admin/users/${encodeURIComponent(u.id)}/uploads`, {
        method: 'POST', json: { paused: !u.uploads_paused },
      });
      Object.assign(u, res.user);
      toast(u.uploads_paused ? `⏸ Uploads von ${u.name} pausiert` : `▶ ${u.name} darf wieder hochladen`, { type: 'success' });
      onChanged(res.user);
    } catch (err) {
      showError(err);
    } finally {
      busy = false;
      render();
    }
  };

  function render() {
    if (attached && !panel.isConnected) {
      listeners.delete(render); // the page re-rendered without this panel
      return;
    }
    attached = attached || panel.isConnected;
    const paused = u.uploads_paused;
    panel.classList.toggle('is-paused', paused);
    panel.replaceChildren(
      h('h2', {}, '📤 Uploads'),
      h('div', { class: 'adm-stack' },
        h('div', { class: 'adm-uploads-guest-status' },
          paused
            ? h('span', { class: 'adm-badge adm-badge--pause', 'data-testid': 'guest-uploads-status' }, '⏸ Uploads pausiert')
            : h('span', { class: 'adm-badge adm-badge--ok', 'data-testid': 'guest-uploads-status' }, '✓ Darf hochladen'),
          paused ? h('span', { class: 'adm-uploads-source', 'data-testid': 'guest-uploads-source' }, pauseSource(u)) : null,
        ),
        state.stop && state.stop.enabled
          ? h('p', { class: 'adm-warn' }, `⏹ Gerade sind ohnehin alle Uploads gestoppt (seit ${clock(state.stop.since)}).`)
          : null,
        h('p', { class: 'adm-muted' }, 'Pausieren ist keine Sperre: Die Fotos bleiben sichtbar, der Gast kann sich weiter '
          + 'umsehen und seinen Instagram-Namen ändern. Er sieht einen freundlichen Hinweis.'),
        h('button', {
          class: `vb-btn vb-btn--block ${paused ? 'adm-toggle--show' : 'adm-uploads-pausebtn'}`, type: 'button',
          'data-testid': 'guest-uploads-toggle', disabled: busy, onclick: toggle,
        }, paused ? '▶ Uploads erlauben' : '⏸ Uploads pausieren'),
      ),
    );
  }

  listeners.add(render);
  render();
  if (!state.pause) refresh();
  return panel;
}

/** ⏸ next to a guest's name on photo cards, kept in step with live changes. */
function syncPausedMarks(users) {
  for (const user of users) {
    const links = document.querySelectorAll(`a[data-testid="user-link"][href="${userUrl(user.id)}"] .adm-user-name`);
    for (const name of links) {
      const mark = name.querySelector('[data-testid="paused-mark"]');
      if (user.uploads_paused && !mark) {
        name.append(h('span', { class: 'adm-badge adm-badge--pause adm-badge--xs', 'data-testid': 'paused-mark', title: 'Uploads pausiert' }, '⏸'));
      } else if (!user.uploads_paused && mark) {
        mark.remove();
      }
    }
  }
}
