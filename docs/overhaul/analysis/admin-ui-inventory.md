# virtubooth admin UI: behaviour inventory

Everything below comes from reading the code in `/home/erikli/a/personal/aaa_doingthings/random_projects/virtubooth/.worktrees/overhaul`. Nothing was modified. Paths are relative to `virtubooth/` unless stated otherwise.

Overall: the admin UI has no QR feature and no export beyond a single-photo download. The admin cannot edit or rename a guest's Instagram handle or name; handles are only shown, copied or linked. Section 15 lists the existing bugs, which the rewrite should knowingly keep or fix.

---

## 0. Files and LOC

| File | LOC | Role |
|---|---|---|
| admin/static/login.html | 30 | login page |
| admin/static/live.html | 44 | live screen shell |
| admin/static/manage.html | 44 | manage screen shell (tabs and panels) |
| admin/static/user.html | 32 | guest detail shell |
| assets/login.js | 46 | login logic, `safeNext` |
| assets/admin.js | 925 | shared library: api wrapper, formatting, badges, PhotoCollection, Lightbox, confirmDialog, focus helpers, SSE, widgets |
| assets/live.js | 181 | live screen |
| assets/manage.js | 905 | manage screen (5 tabs) |
| assets/user.js | 397 | guest page |
| assets/uploadcontrols.js | 390 | upload chip and sheet, guest uploads panel, paused badges |
| assets/admin.css | 620 | |
| assets/uploadcontrols.css | 147 | |
| context: admin/api.py | 517 | |
| context: admin/upload_controls.py | 150 | |
| context: pages.py | 126 | |
| context: static/core/vb.js | 790 | |

**Imports from vb.js.**
- `admin.js` imports `api`, `ApiError`, `h`, `toast` and re-exports `ApiError`, `h`, `toast`.
- `login.js` imports `api` directly.
- Every other module imports only `./admin.js` and `./uploadcontrols.js`. `tests/test_admin_pages.py` enforces that only `./x` or `/static/core/vb.js` may be imported.

**Side effects of importing vb.js.**
- It sets `window.__vbReady = true`. The classic script `/static/core/loader.js` (deferred on every admin page) checks this after 6000 ms. If it is not set, it shows the notice "Die Seite startet nicht" / "Wahrscheinlich blockiert ein Werbe- oder Tracking-Blocker einen Teil der Seite. Schalte ihn für diese Seite aus und lade neu." with a "Neu laden" button (`data-testid="load-failed"`).
- `?debug` turns on the vb debug panel (sessionStorage `vb_debug`, `vb_debug_folded`).
- It re-exports from camera.js.
- It registers a guest-only `visibilitychange` listener, which does nothing on admin pages.

**CSP.** The policy is `script-src 'self'`, `style-src 'self'`, with no inline styles or handlers. The tests also forbid `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `eval(`, `new Function`, `document.write`, `style:` in h() attrs and `setAttribute('style'`. All DOM is built with `h()` and `replaceChildren`.

**Server-side page routing (pages.py).**
- `/admin` returns 303 to `/admin/live`.
- `/admin/login` is public.
- `/admin/assets/*` is public.
- `/admin/{page}` without a session returns 303 to `/admin/login?next=<quote('/admin/{page}?{query}', safe='/')>`.
- Unknown page names get the notfound page.

---

## 1. Shared admin infrastructure (admin.js)

### 1.1 API wrapper and auth
- **`aapi(path, opts)`** wraps vb `api()`. On `ApiError` with status 401 and `code === 'admin_required'` it calls `goLogin()` and returns `new Promise(() => {})`, a never-resolving promise ("the page is leaving; don't show errors"). All other errors are rethrown.
- **`goLogin()`** runs once (module flag `redirecting`) and sets `location.href = /admin/login?next=${encodeURIComponent(location.pathname)}`. It drops the query string (see bugs).
- **`logout()`**: `POST /api/admin/logout`, then in `finally` sets `location.href = '/admin/login'` (no `next`). Wired by `mountHeader()` to `#logout`. The button is 🚪 with `title`/`aria-label` "Abmelden". There is no confirmation.
- **vb `api()` behaviour:**
  - Sends `Accept: application/json` and `credentials: 'same-origin'`; the `json` option is serialized.
  - Throws `ApiError(status, code = data.error || 'http_<status>', message = data.message || 'Da ist etwas schiefgelaufen.')`.
  - On 429/503 with `Retry-After` it sets `err.retryAfter` and rewrites the message to `"<msg without trailing period> (in N s nochmal)."`, or `(in N min nochmal).` when N ≥ 90.
  - Network failure gives `code 'network'`, status 0. The message is "Keine Verbindung. Bist du noch im Netz?" when `navigator.onLine === false`, otherwise "Keine Antwort vom Server. Prüf dein Netz und versuch es nochmal.".
  - `code 'scan_qr'` triggers `location.reload()` (not used by admin endpoints).
- **`showError(err)`** shows `toast(err.message || 'Da ist etwas schiefgelaufen.', {type: 'error', ms: 5000})`.
- **Server error texts the UI can show** (all shown raw through `showError` unless noted):

| Status / code | Message |
|---|---|
| 401 `admin_required` | "Bitte als Admin anmelden." (never shown; triggers redirect) |
| 401 `wrong_password` | "Falsches Passwort." |
| 429 `rate_limited` | "Langsam! Zu viele Anfragen. Warte kurz." plus the Retry-After suffix (login only; admin sessions are not throttled) |
| 429 `login_locked` | "Zu viele Fehlversuche. Login ist kurz gesperrt." (no Retry-After) |
| 403 `bad_origin` | "Anfrage von fremder Seite abgelehnt." (CSRF guard on unsafe methods) |
| 422 | "Ungültige Anfrage." |
| 404 | "Foto nicht gefunden." / "Gast nicht gefunden." / "Diese Fingerprint-Sperre gibt es nicht." |
| 400 | "Für diesen Gast ist kein Fingerprint bekannt." (`no_fingerprint`); "Ungültige Aktivität." / "Ungültige Gast-ID." / "Ungültiger Filter für versteckt/sichtbar." / "Ungültiger Filter." (`invalid_filter`); "Unbekannter Cursor." (`invalid_cursor`); "Bitte wählen: die pausierten neuen Gäste freischalten oder pausiert lassen." (`restore_required`) |

- There is no 409 anywhere in the admin API. There is no automatic retry on 429.

### 1.2 Formatting helpers (pure; port verbatim)
- **`qs(params)`** builds `?a=1&b=2` and skips null, undefined and `''`.
- **`absTime(iso)`**:
  - Uses `Intl.DateTimeFormat('de-DE', {weekday:'short', day:'2-digit', month:'2-digit', year:'numeric', hour, minute, second})`.
  - Falsy input gives '–'; an invalid date returns the raw string.
- **`relTime(iso)`**:
  - < 45 s: "gerade eben"
  - < 90 s: "vor 1 Min."
  - < 1 h: `vor N Min.` (rounded)
  - < 6 h: `vor H Std.` plus ` M Min.` if M > 0
  - otherwise `DAY_FMT`, e.g. "Fr., 22:14" (weekday short plus HH:MM)
  - Falsy input gives '–'.
- **`timeEl(iso, cls='adm-time')`** renders `<time class datetime title=absTime data-rel="1">relTime</time>`. A global `setInterval` of 30000 ms rewrites the text of every `time[data-rel]`.
- **`describeUA(ua)`** (empty gives 'unbekannt'):
  - Device:
    - `iPhone OS x_y` gives "iPhone", "iOS x.y".
    - `iPad…OS` gives "iPad", "iPadOS x.y".
    - `Android n(; model)` gives "Android n" plus the model, unless the model is K, wv, Linux or U.
    - Otherwise Mac, Windows or Linux.
  - App or browser, in priority order: "Instagram-App", "Facebook-App" (FBAN/FBAV), "Samsung Internet N", "Chrome N" (CriOS/Chrome, not Edg), "Edge N", "Firefox N" (FxiOS/Firefox), "Safari N.N" (Version/…Safari).
  - Parts are joined with " · ". The fallback is `ua.slice(0,60)`.
- **Extensions:** `loadExtensions()` calls `GET /api/admin/extensions` and stores the result in a module-global `extMap`.
  - `extInfo(id)` falls back to `{id, title:id, emoji:'📷', meta_labels:{}}`.
  - `photoTitle(p)` returns `${emoji} ${title} #${seq}`.
  - `metaText(p)` joins `${meta_labels[k]||k}: ${v}` with " · " and skips null and `''` values.
- **`userUrl(id)`** returns `/admin/user?id=<encoded>`. **`instagramUrl(h)`** returns `https://www.instagram.com/<encoded>/`.

### 1.3 Badges and atoms (shared look; also JS hooks)
- **`statusBadge(photo)`** (`data-testid="status"`):
  - ban-hidden: class `adm-badge--hidden`, "🙈 Versteckt (Sperre)", title "Versteckt, weil der Gast gesperrt ist"
  - hidden: "🙈 Versteckt"
  - otherwise: `adm-badge--ok`, "✓ Sichtbar"
- **`thumbFlag(photo)`**: a band `.adm-thumb-flag` reading "GAST GESPERRT" (`hidden_reason==='ban'`) or "VERSTECKT"; null when the photo is visible.
- **`toggleButton(photo, onToggle, {cls})`**:
  - A button `.vb-btn.adm-toggle.adm-toggle--show|--hide` with `data-testid="toggle"` and `data-action="unhide|hide"`.
  - Text: "👁 Wieder zeigen" when the photo is hidden, otherwise "🙈 Runternehmen".
- **`runToggle(photo, button, onUpdated)`**:
  - Remembers whether the button had focus, then disables it.
  - Calls `POST /api/admin/photos/{id}/hide` or `/unhide`, which returns `{photo, changed}`, then `onUpdated(res.photo)`.
  - If the button had focus and focus is now lost, it focuses the lightbox's `[data-testid=toggle]`, or else the toggle inside `[data-photo-id=<id>]`.
  - Toast (success): `${photoTitle} runtergenommen` / `${photoTitle} ist wieder sichtbar`.
  - On error it re-enables the button and calls `showError`.
- **`userLink(user)`**:
  - With no user it renders `span.adm-muted` "unbekannt".
  - Otherwise `a.adm-user[href=userUrl][data-testid=user-link]` containing:
    - `span.adm-user-name`: `🙂 ${name}`, then `banBadge(user)` (xs), then the paused mark `span.adm-badge--pause.adm-badge--xs[data-testid=paused-mark][title="Uploads pausiert"]` "⏸" when `user.uploads_paused`.
    - `span.adm-user-insta`: `@${instagram}`, or `.adm-user-insta--none` "kein Instagram".
- **`banBadge(user, {xs=true})`**:
  - Null if not banned.
  - Auto ban: `span.adm-badge--ban.adm-badge--auto[data-testid=auto-ban]` "AUTO-GESPERRT", title "Automatisch gesperrt: neues Gerät mit gesperrtem Fingerprint".
  - Otherwise "GESPERRT".
- **`banMark(user)`**: " 🚫 auto" / " 🚫" / ''.
- **`autoBanSource(user)`**:
  - Without `user.auto_ban`: "gesperrtem Fingerprint (die Sperre gibt es inzwischen nicht mehr)".
  - Otherwise `gesperrtem Fingerprint ${fp_hash.slice(0,12)}…`, plus ` (gesperrt über ${source_user_name || '#'+source_user_id})` when a source exists.
- **`unbanToast(text, released)`**: `${text} · ${n} weiteres Gerät|weitere Geräte entsperrt`, success, shown for 5000 ms if n > 0, otherwise the default 2800 ms.
- **`copyText(text, label)`**:
  - Uses `navigator.clipboard.writeText` in a secure context. Otherwise it falls back to an off-screen `textarea.adm-offscreen` with `execCommand('copy')` ("plain http on a LAN IP has no async clipboard API").
  - Toast: `Kopiert: ${label || text}` on success, or the error "Kopieren ging nicht. Bitte von Hand markieren.".
- **`field(label, control, tag='label')`** renders `<label class=adm-field><span>label</span>control</label>`.
- **`segmented(options, value, onChange, {label, testid})`**:
  - `div.adm-seg[role=group][aria-label][data-testid]` containing buttons with `data-value` and `aria-pressed`.
  - `el.setValue(v)` updates `aria-pressed`. There is no arrow-key navigation.
- **`throttle(fn, ms)`** fires once, `ms` after the first call of a burst. The comment says: "Unlike a debounce it still fires while calls keep coming (busy party = steady events)". **`debounce(fn, ms)`** is a standard trailing debounce.

### 1.4 PhotoCollection (keyed list ↔ DOM)
- `new PhotoCollection(container, render)` keeps `items: Map<id, {photo, el}>`.
- **`photos`** is derived from DOM order (`container.children` mapped through `dataset.photoId`).
- **`upsert(photo, {append})`**:
  - Renders the element and sets `el.dataset.photoId`.
  - If the photo exists, it replaces the element in place. If focus was inside the old element, it refocuses the matching control in the new one, matched by `focusKey` = `data-testid` || `aria-label` || `textContent`. Returns 'updated'.
  - Otherwise it appends, or inserts sorted newest first by comparing `created_at` strings ("ISO-8601 UTC so strings compare in time order"). Returns 'inserted'.
- Also has `remove(id)` (returns bool), `clear()`, `get`, `has`, `size`, `newest()`, `oldest()` (unused) and `rerender()` (unused).

### 1.5 Focus helpers
- **`FOCUSABLE`** = `'a[href], button, input, select, textarea, [tabindex]'`. **`focusables()`** keeps elements that are not disabled, not `tabindex=-1`, and visible (`getClientRects().length`).
- **`keepTabInside(event, root)`**: a Tab/Shift+Tab cycle. When nothing is focusable it calls `preventDefault`. It wraps at the first and last element, and pulls focus back in when it is outside `root`.
- **`inertOthers(layer)`**:
  - Sets `inert = true` on every `document.body` child except the layer itself, already-inert elements, `.vb-toast-host` ("toasts stay: they announce results") and `SCRIPT` elements.
  - Returns an undo that only reverts what it changed, so layers can nest.
- **`focusFirst(...candidates)`**: candidates may be elements or functions. It focuses the first one that is connected, not disabled, not inside `[inert]` and visible.
- **`thumbFor(id)`**: the first visible `[data-thumb-for=id]`.
- **`refocusAfterRemoval(beforeIds, goneIds)`**: if focus was lost, it focuses the thumb of the next surviving photo after the first removed one, else the previous one.

---

## 2. Header, nav, connection badge, toasts (shared chrome)

**Header** `header.adm-header` (sticky, z 50, blurred) contains `.adm-header-row` with:
- the title (live "📸 Live", manage "🛠 Verwaltung"; the user page has the back link `a.adm-back[data-testid=back]` "← Gäste" to `/admin/manage?tab=gaeste`)
- `#conn`
- `nav.adm-nav[aria-label=Admin]`:
  - live: `a[data-testid=nav-manage]` "Verwaltung" plus `#logout`
  - manage: `a[data-testid=nav-live]` "📸 Live" plus `#logout`
  - user: "📸 Live", "🛠 Verwaltung" (`.adm-hide-narrow`, hidden at ≤520px), `#logout`

**Connection badge** `span#conn.adm-conn[data-testid=conn][data-state]`, initially `data-state="connecting"` with text "Verbinde…".
- `connBadge(state)` sets `data-state` and replaces the content with `span.adm-conn-text`.
- States and text: connecting "Verbinde…", live "Echtzeit", reconnecting "Verbinde neu…", polling "Abruf alle 5 s".
- `title`: when live, "Neue Fotos erscheinen sofort."; otherwise "Keine Live-Verbindung: die Seite fragt alle paar Sekunden nach.".
- The CSS dot is yellow by default, green with a ring when live, orange when reconnecting or polling.
- On the manage page at ≤480px the text is hidden and only the dot shows.

**Toasts** (vb.js `toast(msg, {type, ms=2800})`):
- Host: `div.vb-toast-host[aria-live=polite]`, z 2000.
- Each toast: `div.vb-toast.vb-toast--{type}` with `role=alert` for errors, otherwise `role=status`. It is removed after `ms`.

**Stacking order:** `.vb-scrim` 1000, lightbox 1500, `.adm-dialog-scrim` 1600, toasts 2000, bulkbar 60, new-pill 55.

---

## 3. Login (`/admin/login`, login.html + login.js)

**Structure:**
- `body.adm`, `main.vb-page.adm-login`, `.vb-card`, h1 "🔐 Admin" (with "Admin" in `.vb-grad-text`).
- Paragraph: "Moderation für die Party: Fotos runternehmen, Gäste verwalten."
- `form#login-form[novalidate]`:
  - label "Passwort"
  - `input#password[type=password][autocomplete=current-password][maxlength=256][required][autofocus]`
  - `div#login-error.vb-field-error[role=alert][data-testid=login-error]`
  - `button#login-submit` "Anmelden"
- The tab title is "Admin-Login".

**`safeNext(raw)`** is exported:
- Regex `^\/admin\/[a-z0-9-]*(\?id=\d{1,9})?$`.
- It rejects `/admin/` and `/admin/login`; the fallback is `/admin/live`. This prevents open redirects.
- Only `?id=` queries survive, so `/admin/manage?tab=…` falls back to `/admin/live`.

**On load:** `GET /api/admin/session`. If `{authenticated:true}`, `location.replace(next)`. Errors are ignored and the form is shown.

**Submit:**
1. `preventDefault` and clear the error.
2. If the field is empty: show "Bitte das Passwort eingeben." and focus the input.
3. Disable the button and set its text to "Prüfe…".
4. `POST /api/admin/login {password}`.
5. Success: the button text becomes "Willkommen!" and the page calls `location.replace(next)`.
6. Error: show `err.message || 'Login fehlgeschlagen.'` in the error div (the possible messages are in §1.1), re-enable the button with text "Anmelden" and call `input.select()`.

`api` is used rather than `aapi`, so there is no redirect loop.

---

## 4. Live screen (`/admin/live`, live.html + live.js)

**Purpose:** newest uploads in real time. The only allowed actions are taking a photo down and showing it again. The rule "deleting lives in the management screen on purpose" is enforced by `test_live_screen_cannot_delete`: live.js must not contain `'DELETE'`, `'delete'`, "Löschen", "/bulk", deletePhoto, confirmAndDelete, managementActions or photoTile, and must contain "photo.deleted".

**HTML hooks:**
- `body.adm.adm-live`
- Stats: `.adm-stats[role=group][aria-label=Zähler]` with `b#stat-photos[data-testid=stat-photos]` "Fotos", `#stat-guests` "Gäste" and `#stat-hidden` "versteckt" (`.adm-stat--hidden`, red number). All start as "–".
- `div#upload-controls.adm-uploads-slot`: the upload chip sits below the stats row.
- `button#new-pill.adm-new-pill.vb-hidden[data-testid=new-pill]`
- `div#feed.adm-feed[data-testid=feed][aria-live=polite]`
- `div#loading.adm-loading` with a `.vb-spinner`
- `div#empty.adm-empty.vb-hidden[data-testid=empty]`: "Noch keine Fotos." / "Sobald jemand knipst, taucht das Foto hier sofort auf."
- `button#more` "Ältere Fotos laden"

**Card** `renderCard`: `article.adm-card[.is-hidden][data-testid=photo-card][data-photo-id]`, containing:
- `button.adm-thumb[data-testid=thumb][data-thumb-for=id][aria-label="<title> groß anzeigen"]`, wrapping `img[src=thumb_url][alt=""][loading=lazy][decoding=async]` and the thumbFlag. Clicking it opens the lightbox.
- `.adm-card-body`: `span.adm-card-title`, `.adm-meta` (timeEl and statusBadge), userLink, toggleButton.

The layout is 124px plus 1fr on phones and an auto-fill grid with min 240px at ≥760px.

**Boot (`main`):**
1. `mountHeader()` and `mountUploadControls(#upload-controls)`.
2. `await loadExtensions()`.
3. `GET /api/admin/photos?limit=30`, append the results, store `nextCursor = data.next`.
4. Remove `#loading` and run `syncEmpty()`. Empty shows when size is 0; `#more` shows when `nextCursor` is set.
5. `loadStats()` immediately ("the throttled refresh would show '–' for a moment").
6. `connectEvents({onEvent, onResync: resync})`.
7. Wire the more button, an `IntersectionObserver` on `#more` with `rootMargin 400px` (infinite scroll), and `setInterval(refreshStats, 60000)`.

If `main` fails, `#loading` is removed and `showError` runs. There is no retry, and the conn badge stays "Verbinde…".

**Stats:** `GET /api/admin/stats` fills photos, guests and hidden. Errors are ignored. `refreshStats` is `throttle(loadStats, 800)` and runs after every SSE event, after toggles and after resync.

**Load more:**
- Guarded by `loadingMore`; the button is disabled while loading.
- `GET /api/admin/photos?limit=30&before=<nextCursor>`, appended.
- Errors go to `showError`. `finally` re-enables the button and calls `syncEmpty`.

**New photos:** `add(photo)`.
- If the photo is already known, it is handled as an update.
- `atTop` means `scrollY < 60`. The photo is upserted (sorted) and gets the `is-new` class, which runs a 1.2 s `adm-arrive` animation; the class is never removed.
- When not at the top, the page scrolls by the height delta so the view does not move. `html, body { overflow-anchor: none }` ("we keep the scroll position ourselves"). It then increments `unseen`.
- The pill text is `⬆ ${n} neues Foto|neue Fotos`.
- Clicking the pill hides it and scrolls smoothly to the top. A passive scroll listener also hides it once `scrollY < 60`.

**Toggle:** `runToggle` followed by `update()`: upsert if known, `lightbox.refresh()`, `refreshStats()`.

**Remove:** `photos.remove(id)`, then `syncEmpty` and `lightbox.refresh`.

**Lightbox:** `list = photos.photos`. The only action is `toggleButton(photo, onToggle, {cls:'vb-btn--big'})`; there is no download, copy or delete.

**SSE handling:**
- `photo.created`: `add(data.photo)`
- `photo.hidden` / `photo.unhidden`: `update(data.photo)`
- `photo.deleted`: `remove(data.id)`
- `user.banned` / `user.unbanned`: update each of `data.photos` (known ones only)
- `refreshStats()` runs after every event type.

**Resync** (on poll, reconnect or visible):
1. `GET photos?limit=30`.
2. Every local photo with `created_at >= oldest server created_at` that is missing from the response is removed ("inside the window the server sent, anything missing was deleted"). If the server returned nothing, all local photos are removed.
3. `add()` each server photo from oldest to newest, so new ones increment the pill.
4. If the collection is empty, set `nextCursor = data.next`.
5. Run `syncEmpty` and `refreshStats`.
6. Non-network errors go to `showError`; this can repeat every 5 s while polling.

---

## 5. Manage screen (`/admin/manage`, manage.html + manage.js)

### 5.1 Shell, URL state and tabs
**HTML:**
- `body.adm.adm-manage`; the header holds the title, `#conn`, nav, then `#upload-controls`. **The upload chip sits above the tabs.**
- Tab list: `div.adm-tabs[role=tablist][aria-label=Bereiche]`. Each tab is `button.adm-tab[role=tab][type=button][data-tab][id=tab-X][aria-controls=panel-X][aria-selected=false]`:

| `data-tab` | Label | Count span |
|---|---|---|
| fotos | "📸 Fotos" | `span.adm-count#count-fotos` |
| gaeste | "🙂 Gäste" | `#count-gaeste` |
| instagram | "📷 Instagram" | `#count-instagram` |
| sperren | "🚫 Sperren" | `#count-sperren` |
| protokoll | "📜 Protokoll" | none |

- Then `#new-pill`.
- Panels: `section#panel-X[role=tabpanel][aria-labelledby=tab-X][tabindex=0][hidden]`.
- Before JS runs, no tab is selected and every tab is in the Tab order.

**URL params** (validated on load):
- `tab` must be in TABS (default fotos).
- `ext` must match `^[a-z][a-z0-9-]{1,30}$`.
- `status` must be visible or hidden (default all).
- `user` must match `^[1-9]\d{0,15}$`.
- `show=paused` presets the Gäste filter.

**`syncUrl()`** calls `history.replaceState(history.state, '', '/admin/manage' + qs({tab (omitted for fotos), ext, status (omitted for all), user}))`. It preserves the lightbox history marker and does not write `show` back.

**`showTab(tab)`:**
1. Set `aria-selected` on every tab.
2. Roving tabindex: the selected tab gets 0, the others -1.
3. `scrollToSelectedTab()` calls `scrollIntoView({block:'nearest', inline:'nearest'})`, because the tab row scrolls sideways on phones.
4. Set `panel.hidden` on every panel, then call `syncUrl()` and `syncPill()`.
5. Lazy load: if the panel is not loaded, or is dirty, set `loaded = true`, `dirty = false` and call `panel.load()`.

**Tab keyboard** (keydown on `.adm-tabs`):
- Only acts while focus is on a tab and Alt, Ctrl and Meta are not held (Shift is not excluded).
- ArrowRight and ArrowLeft wrap; Home goes to the first tab, End to the last.
- `preventDefault`, focus the target, `showTab` (automatic activation). ArrowUp and ArrowDown do nothing.
- The panels are `tabindex=0`, so Tab from the tab list lands on the panel (the test expects focus on `panel-fotos`).
- CSS: the tab row has 4px padding as "room for the focus ring: the scroller clips outlines". The selected tab gets the gradient. A focused panel gets a cyan outline.

**Boot:**
1. `mountHeader`, `mountUploadControls`.
2. Click listeners on the tabs and keydown on the tab list.
3. Build all five panels.
4. `await loadExtensions()` and `fillExtSelect`, then `await fillUserSelect()`.
5. `showTab(state.tab)`.
6. `loadStats().then(scrollToSelectedTab)`, because "the counts widen the tabs".
7. `connectEvents({onEvent, onResync})`.
8. `main().catch(showError)`.

**Tab counts:** `GET /api/admin/stats`.
- `#count-fotos` = `s.photos` (unfiltered total).
- `#count-gaeste` = `s.guests`.
- `#count-instagram` = `s.instagram_handles`, with `title = handleCount(instagram_handles, instagram)`, e.g. "4 Handles · 9 Gäste" (singular "Handle", "Gast").
- `#count-sperren` = `s.banned + s.fingerprint_bans`.
- Errors are ignored. `refreshStats` is `throttle(loadStats, 400)`.

**`invalidate(tab, ms = 800)`:**
- If the panel was never loaded, nothing happens.
- If the tab is not the current one, `panel.dirty = true` and it reloads on the next show.
- Otherwise it calls a per-tab throttle of `panel.load()`, cached in `reloadVisible[tab]` with the **first** `ms` ever used for that tab.

### 5.2 Tab "Fotos"
**Toolbar** `.adm-toolbar.adm-toolbar--filters`:
- `field('Aktivität', select.adm-select[aria-label=Aktivität][data-testid=filter-ext])`. Options: "Alle Aktivitäten" (value `''`), then `${emoji} ${title}` per extension (this includes unloaded extensions that still have photos, shown with 📷 and the id as title), plus the raw id if the URL's `ext` is unknown.
- `field('Gast', select[aria-label=Gast][data-testid=filter-user])`:
  - Filled from `GET /api/admin/users?limit=500` (cap 500).
  - Includes users with `photo_count > 0` or the selected id, sorted with `name.localeCompare(…, 'de')`.
  - First option "Alle Gäste". Each user: `${banned?'🚫 ':''}${name}${instagram?' · @'+instagram:''} (${photo_count})`. Fallback `Gast #<id>`.
  - Builds the `fotos.userIds` set. `refreshUserSelect` is `throttle(fillUserSelect, 1500)`. Errors go to `showError`.
- `div.adm-field.adm-field--wide` with "Status" and `segmented([['all','Alle'],['visible','Sichtbar'],['hidden','Versteckt']], {label:'Status', testid:'filter-status'})`.
- Changing any filter updates state and calls `reloadPhotos()`.
- On phones (≤600px) the filters form a two-column grid with the visible labels hidden (hence the aria-labels on the selects) and the segmented control at full width.

**Select line** `.adm-selectline`:
- `span.adm-num[data-testid=photo-total]`: `${total} Foto|Fotos`.
- `button[data-testid=select-all]` "☑ Alle auswählen".
- `span.adm-muted.adm-hover-only` "Tipp: Shift-Klick auf die Häkchen wählt einen Bereich.", shown only under `(hover:hover) and (pointer:fine)`.

**Grid and states:**
- Grid: `div.adm-grid[data-testid=grid]`.
- Spinner: `.adm-loading`.
- Empty: `div.adm-empty[data-testid=grid-empty]` "Keine Fotos." / "Für diesen Filter gibt es (noch) nichts.", shown when not loading and the grid is empty.
- More: `button.adm-more` "Mehr laden", shown when `fotos.next`. An `IntersectionObserver` with `rootMargin 600px` loads more automatically.
- Then the bulkbar.

**Tile** `photoTile(photo, {selected, onSelect, onOpen, onToggle, onDelete, showUser=true})`: `article.adm-tile[.is-hidden][.is-selected][data-testid=photo-tile][data-photo-id]`, containing:
- When selectable: `label.adm-tile-check[title="Auswählen (Shift-Klick: Bereich)"]` wrapping `input[type=checkbox][aria-label="<title> auswählen"][data-testid=select]`. Its click calls `onSelect(photo, checked, event.shiftKey)`.
- `button.adm-thumb` (same attributes as on live). Click calls `onOpen`.
- `.adm-tile-body`:
  - `span.adm-tile-title[title]`
  - `.adm-meta` (time and status)
  - userLink when `showUser`
  - `.adm-tile-actions`: toggleButton plus `button.vb-btn.adm-del.adm-btn-danger-ghost[title="Endgültig löschen"][aria-label="<title> löschen"][data-testid=delete]` "🗑" with `span.adm-del-label` " Löschen". The label is visible only when the container query matches ≤205px, where the buttons also stack.

**reloadPhotos():**
1. `syncUrl`, then `++reqId`, `loading = true`, `next = null`.
2. `hidePill()` (pending = 0), `clearSelection()`, clear the grid, show the spinner.
3. `GET /api/admin/photos?extension&hidden=(visible|hidden|'')&user_id&limit=48`.
4. Stale responses are dropped by `reqId`.
5. Append the photos and set `next`, `total = data.total` and `gone.clear()`.
6. Errors go to `showError`. The grid then shows the empty state as well.

**loadMorePhotos():**
- Guarded by `next` and `!loading`; same filters plus `before=next`; appended.
- `finally` always resets `loading` and the button.

**Selection:**
- `onSelectClick`: Shift range is computed from `lastClicked` to the clicked photo in the current DOM order. Every photo in the range is set to the clicked checkbox state, then `lastClicked` is updated.
- `markSelected(id)` toggles `.is-selected` and sets the checkbox.
- `selectAllLoaded` selects every loaded photo.
- `clearSelection` clears.
- The selection survives re-renders because render reads `fotos.selected`, and it is cleared on every filter reload.

**Bulkbar** `div.adm-bulkbar[data-testid=bulkbar][role=toolbar][aria-label=Auswahl]`:
- Fixed at the bottom centre, hidden when nothing is selected.
- Contents:
  - `strong[data-testid=bulk-count]` `${n} ausgewählt`
  - `button[data-testid=bulk-hide]` "🙈 Runternehmen"
  - `button[data-testid=bulk-unhide]` "👁 Zeigen"
  - `button[data-testid=bulk-delete]` "🗑 Löschen" (`vb-btn--danger`)
  - `button[data-testid=bulk-clear]` "Abbrechen"

**`bulk(action)`:**
- Uses the selected ids still present in the grid.
- delete: `deletePhotos(list)`, which asks for confirmation. If cancelled, the selection stays ("deleted ones leave it via dropPhoto()").
- hide / unhide (no confirmation):
  1. In chunks of 200: `POST /api/admin/photos/bulk {ids, action}`, which returns `{action, changed[], unchanged[], missing[]}`.
  2. `missing` ids go through `dropPhoto`.
  3. Each changed photo is patched locally: `{...p, hidden, hidden_reason: hide ? 'admin' : null, hidden_at: now|null}`.
  4. Toast `${changed} Fotos runtergenommen` / `${changed} Fotos wieder sichtbar` (no singular form).
  5. `clearSelection` and `refreshStats`.
  6. On error, `showError` and the selection is kept.

**Single and bulk delete:**
- `deletePhotos(list)` records the id order before, calls `confirmAndDelete(list)`, then `dropPhoto(id, photo)` for each id that is gone, `refreshStats`, and `refocusAfterRemoval`.
- `confirmAndDelete` (in admin.js) shows the confirm dialog (§8), then sends `POST /api/admin/photos/bulk {ids (chunks of 200), action:'delete'}`. Gone = `changed + missing`.
- Toast: "Foto gelöscht" when n = 1, otherwise `${gone.length} Fotos gelöscht`.
- On error mid-way, `showError` and the partially gone list is returned.
- The admin.js export `deletePhoto` (`DELETE /api/admin/photos/{id}`) is never used.

**`patchPhoto(photo)`:**
- Upserts into the grid if present. It does not remove a photo that no longer matches the status filter and does not adjust the total.
- Also replaces the photo in `insta.data[].recent`, re-renders the Instagram tab if it is visible, and calls `lightbox.refresh()`.

**`dropPhoto(id, photo?)`:**
- Counted once per id through the `fotos.gone` set ("the API answer and the SSE event both report a deletion: count it once"). `total` is decremented if the photo was in the grid or matches the filter.
- Removes the photo from the grid, the selection and insta.recent, then runs `syncBulkbar`, `syncFotosEmpty` and `lightbox.refresh()`.

**New-photo pill** (manage semantics differ from live):
- `photo.created` does not insert into the grid. When the photo matches the filter and the Fotos panel is loaded, it increments `fotos.pending`.
- `syncPill` shows the pill only on the Fotos tab: `⬆ ${n} neues Foto|neue Fotos anzeigen`.
- Clicking it calls `showNewPhotos()`:
  - With an empty grid it calls `reloadPhotos`.
  - Otherwise `GET photos?…filters&limit=200&after=<newest.id>`, upserted sorted. `total += inserted` and the page scrolls smoothly to the top.
- There is no scroll listener here. If more than 200 photos arrived, only the newest 200 are fetched, leaving a gap.

**resyncPhotos()** (only when the Fotos panel is loaded and not loading):
1. `GET` the first page with filters.
2. Known photos are upserted. Unknown photos newer than the local newest are counted as `fresh` (pill only). Older unknown photos are inserted.
3. Local photos inside the window that are missing from the server are dropped.
4. `pending = fresh`; `total = data.total`; then `syncTotal`, `syncFotosEmpty` and `lightbox.refresh`.
5. Errors are silent.

**Lightbox on manage:**
- The module keeps a `lightboxSource` function. `openLightbox(source, photo)` sets the source and opens the lightbox.
- Tiles use `() => photosCol.photos`.
- Actions come from `managementActions(photo, {onToggle, onDelete: p => deletePhotos([p])})`:
  - `a.vb-btn[href="${url}?download=1"][download="${extension}-${seq padded to 5}.jpg"][data-testid=download]` "⬇ Download"
  - when the photo's user has Instagram: `button.vb-btn--cool[data-testid=copy-handle]` `📋 @${handle} kopieren`, which calls `copyText('@handle')`
  - toggleButton
  - `button.vb-btn--danger[data-testid=lightbox-delete]` "🗑 Löschen"

### 5.3 Tab "Gäste"
- **Search:** `input.adm-search[type=search][placeholder="Name, @instagram oder #Nummer"][aria-label="Gäste suchen"][autocomplete=off][autocapitalize=none][spellcheck=false][maxlength=100][data-testid=guest-search]`. Input is debounced 250 ms; the trimmed value is set as `gaeste.search`, then `loadGaeste()`.
- **"Zeigen" filter:** `segmented([['all','Alle'],['banned','Gesperrte'],['ok','Nicht gesperrt'],['paused','⏸ Pausiert']], {label:'Filter'})`, with no testid. The initial value comes from `?show=paused`.
- **Count:** `.adm-toolbar-end` holds `span.adm-num`. When search, banned or paused is active it shows `${rows}${next_offset!==null?'+':''} Treffer`, otherwise it is empty.
- **loadGaeste({more}):**
  - Uses `reqId`.
  - Request: `GET /api/admin/users?search&banned=('true'|'false'|'')&paused=('true'|'')&limit=100&offset=(more ? next : 0)`.
  - Shows a spinner only when the list is empty and this is not a "more" request.
  - Replaces the list, or appends for "more".
  - Empty text: `Niemand passt zu „${search}“.` with a search, otherwise "Noch keine Gäste." (also shown when the banned or paused filter has no results).
  - "Mehr laden" (`button.adm-more`) is shown when `next_offset !== null`. Clicking it loads more. There is no infinite scroll here.
- **Row:** `a.adm-row[.is-banned][href=userUrl][data-testid=guest-row]`.
  - Title: `🙂 ${name}`, then `banBadge(u)` (AUTO-GESPERRT for auto bans), then `pausedBadge(u)`.
  - Sub-line, joined with " · ": `@insta` or "kein Instagram"; `zuletzt ${relTime(last_seen_at)}` (static, not refreshed); `describeUA(user_agent)`.
  - Side: `span.adm-num[title=Fotos]` `📸 ${photo_count}` and an `aria-hidden` "›".

### 5.4 Tab "Instagram"
- **Section:**
  - h2 "Instagram-Handles" with `span[data-testid=insta-count]`, e.g. `handleCount(handles, sum of users)` like "4 Handles · 9 Gäste".
  - Paragraph: "Zum Markieren beim Posten. Tippe ein Foto an, um es herunterzuladen und den Handle zu kopieren. Handles gesperrter Gäste werden beim Kopieren aller Handles ausgelassen."
  - Toolbar button `[data-testid=copy-all-handles]`: initially "📋 Alle Handles kopieren", after render `📋 Alle ${taggable} Handles kopieren`.
- **Copy all:**
  - Taggable handles are those with at least one non-banned user.
  - With none, an info toast says "Noch keine Instagram-Handles.".
  - Otherwise `copyText('@a @b …' joined by spaces, '${n} Handles')`, which produces the toast "Kopiert: n Handles".
- **Load:** `GET /api/admin/instagram`, which returns `{handles:[{handle, users:[{id, name, banned, photos}], photos, visible, hidden, last_upload_at, recent:[≤8 newest visible admin_view photos]}]}` sorted by most photos.
  - A spinner shows on the first load only.
  - Then `renderInsta()` and `lightbox.refresh()`. Errors go to `showError`.
- **Empty:** "Noch keine Handles." / "Gäste können ihren Instagram-Namen beim Start oder über den Namens-Chip angeben."
- **Entry:** `article.adm-insta[data-testid=insta-row][data-handle]`.
  - Head:
    - `span.adm-insta-handle` `@handle`
    - "GESPERRT" badge if **all** of its users are banned
    - facts: `${photos} Foto|Fotos`, ` · ${hidden} versteckt` if any, ` · zuletzt ${rel}`
    - buttons: `button.vb-btn--cool[data-testid=copy-handle]` "📋 Kopieren" (`copyText('@handle')`), and `a[target=_blank][rel="noopener noreferrer"]` "Profil ↗" to instagram.com
  - Chips:
    - per user: `a.adm-chip-link[href=userUrl]` `🙂 ${name}` plus `banMark`
    - per user with photos > 0: `button.adm-chip-link`, text `📸 Alle ${u.photos} Fotos von #${u.id}` when the handle has more than one user, otherwise `📸 Alle ${u.photos} Fotos`. It calls `showUserPhotos(id)`.
  - Strip `.adm-strip`: `button.adm-thumb[aria-label="<title> ansehen"][data-thumb-for]`. Opens the lightbox with a source that re-looks-up this handle's current `recent`, so navigation stays within the strip.
- **`showUserPhotos(id)`:** sets `state.user = id`, `status = 'all'`, `ext = ''`, syncs the controls (adding a `Gast #id` option if needed), sets `panels.fotos.loaded = false` and calls `showTab('fotos')`.

### 5.5 Tab "Sperren"
Both lists load together: `Promise.all([GET /api/admin/users?banned=true&limit=500, GET /api/admin/device-bans])`. There is no spinner; errors go to `showError`.

**Section "🚫 Gesperrte Gäste"** with count `(N)`:
- Paragraph: "Gesperrte Gäste können nichts mehr hochladen; ihre Fotos sind versteckt. Entsperren holt nur die Fotos zurück, die durch die Sperre versteckt wurden. „AUTO-GESPERRT“ heißt: neues Gerät mit einem gesperrten Fingerprint, vielleicht nur dasselbe Handymodell."
- Row `div.adm-row.adm-row--stack.is-banned[.is-auto][data-testid=banned-user-row]` (dashed orange when auto). It contains:
  - userLink(u). The full user view includes `auto_banned`, so the badge here can read AUTO-GESPERRT.
  - Sub-line for an auto ban: `Automatisch gesperrt ${rel(banned_at)}: neues Gerät mit ${autoBanSource(u)}. Vielleicht nur dasselbe Handymodell.`
  - Sub-line otherwise: `Grund: ${ban_reason||'–'} · gesperrt ${rel} · ${photo_count} Fotos`.
  - Button `[data-testid=unban-user][aria-label="${name} entsperren"]` "✅ Entsperren".
- Clicking the button (no confirmation):
  1. Disable it.
  2. `POST /api/admin/users/{id}/unban {fingerprint:false}`.
  3. Toast `${name} ist entsperrt`.
  4. `loadSperren` and `refreshStats`.
  5. On error: re-enable and `showError`.
- Empty: "Niemand gesperrt. 🎉"

**Section "🧬 Gesperrte Fingerprints"** with count:
- Warning (`p.adm-warn`): "⚠️ Neue Geräte mit einem gesperrten Fingerprint starten direkt gesperrt. Gleiche Handymodelle (z. B. zwei gleiche iPhones) können denselben Fingerprint haben, dann trifft es auch Unbeteiligte. Bereits bekannte Gäste sind davon nicht betroffen. Entsperren hebt auch die automatischen Sperren auf, die nur an diesem Fingerprint hängen."
- Row `[data-testid=fp-ban-row]`:
  - Title `.adm-mono[title=full hash]` `🧬 ${hash16}…`.
  - Sub-line `Grund: ${reason||'–'} · seit ${rel}`, plus ` · gesperrt über <a href=userUrl>${source_user_name||'#'+id}</a>` when there is a source.
  - Chips `${n} Gerät|Geräte:`, each a user chip with `banMark`.
  - Auto note `[data-testid=fp-auto-note]`: `${k} Gerät ist|Geräte sind nur wegen dieses Fingerprints gesperrt (🚫 auto) und wird|werden beim Entsperren mit entsperrt.`
  - Button `[data-testid=unban-fp][aria-label="Fingerprint ${hash16} entsperren"]` "✅ Entsperren".
- Clicking the button (no confirmation): `DELETE /api/admin/device-bans/{hash}`, which returns `{users_unbanned:[refs]}`. Then `unbanToast('Fingerprint entsperrt', users_unbanned)`, `loadSperren` and `refreshStats`. On error (for example the 404 "Diese Fingerprint-Sperre gibt es nicht.") the button is re-enabled and the error toasted.
- Empty: "Keine Fingerprint-Sperren."

### 5.6 Tab "Protokoll"
- **Header:** h2 "📜 Protokoll", then "Wer hat wann was gemacht. „admin:…“ ist die Kennung der jeweiligen Admin-Sitzung."
- **Table:** `div.adm-table-wrap` (scrolls sideways) holding `table.adm-table[data-testid=audit]` with columns Zeit / Aktion / Ziel / Details / Wer. There is no empty state and no spinner.
- **Load:** `GET /api/admin/audit?limit=100&before=<next>`, where the cursor is a numeric id. "Ältere Einträge" (`button.adm-more`) is shown when `next`.
- **Row:**
  - Zeit: `absTime` with the weekday prefix stripped (regex `^\w+\.,\s*`), full value in `title`, `.adm-nowrap`.
  - Aktion: `ACTIONS[action] || action`.
  - Ziel: `auditTarget(target)`:

    | Target | Rendered as |
    |---|---|
    | `user:<n>` | link "Gast #n" |
    | `photo:<id>` | `a[href=#]` `Foto ${id8}…`. Click: `GET /api/admin/photos/{id}`, then open the lightbox with the static list `() => [photo]`. On 404 the error toast "Das Foto wurde gelöscht.", otherwise `err.message`. |
    | `fp:<h>` | mono `🧬 h` |
    | `ip:<ip>` | mono |
    | anything else | raw text or '–' |

  - Details: entries joined with " · ". The key `reason` is shown as `Grund: ${v||'–'}`; others as `k: v`.
  - Wer: actor in mono.
- **ACTIONS labels:**

| Action | Label |
|---|---|
| photo.hide | 🙈 Foto runtergenommen |
| photo.unhide | 👁 Foto wieder gezeigt |
| photo.delete | 🗑 Foto gelöscht |
| user.ban | 🚫 Gast gesperrt |
| user.unban | ✅ Gast entsperrt |
| fingerprint.ban | 🧬 Fingerprint gesperrt |
| fingerprint.unban | 🧬 Fingerprint entsperrt |
| admin.login | 🔐 Admin angemeldet |
| admin.logout | 🚪 Admin abgemeldet |
| admin.login_failed | ⚠️ Falsches Admin-Passwort |
| user.uploads_pause | ⏸ Uploads des Gasts pausiert |
| user.uploads_unpause | ▶ Uploads des Gasts erlaubt |
| uploads.lock_on | ⏸ Neue Gäste pausiert |
| uploads.lock_off | ▶ Pause für neue Gäste beendet |
| uploads.stop | ⏹ Alle Uploads gestoppt |
| uploads.resume | ▶ Uploads laufen wieder |

The six upload labels come from `UPLOAD_AUDIT_LABELS` in uploadcontrols.js.

### 5.7 Manage SSE handling (`onEvent`)

| Event | Effect |
|---|---|
| photo.created | `pending++` and `syncPill` if it matches the filter and Fotos is loaded; `refreshUserSelect()` if the uploader is not in `fotos.userIds`; `invalidate('instagram', 2000)`; `invalidate('gaeste', 2000)` |
| photo.hidden / unhidden | `patchPhoto(data.photo)`; `invalidate('instagram')` |
| photo.deleted | `dropPhoto(data.id, data.photo)`; `invalidate('instagram')` |
| user.created | `invalidate('gaeste', 2000)` |
| user.banned / unbanned | `patchPhoto` each of `data.photos`; invalidate gaeste, sperren and instagram; `refreshUserSelect()` |
| fingerprint.banned / unbanned | `invalidate('sperren')` |
| user.uploads_changed, settings.upload_pause | `invalidate('gaeste')` |
| every event | `invalidate('protokoll', 1500)` and `refreshStats()` |

**onResync:** on the Fotos tab it runs `resyncPhotos()`; on other tabs `invalidate(state.tab, 100)`. Then `refreshStats()`.

---

## 6. Guest detail page (`/admin/user?id=N`, user.html + user.js)

**Shell:**
- `body.adm.adm-userview`; the header is as in §2.
- `main#user-root.adm-main` starts with a spinner.
- There is no upload chip on this page; it uses the guest uploads panel instead, although uploadcontrols.css is loaded.
- Valid ids match `^[1-9]\d{0,15}$`.

**States:**
- Invalid or missing id: `div.adm-empty` "Kein Gast ausgewählt." with the link "Zur Gästeliste" (`/admin/manage?tab=gaeste`).
- 404: "Gast nicht gefunden." with the same link.
- Other load errors: toast, and the spinner stays.
- Once loaded: `document.title = "${name} · Admin"`.

**Data:** `GET /api/admin/users/{id}` returns:
- `user`: admin_view plus `auto_banned` and `auto_ban {fp_hash, source_user_id, source_user_name}`
- `fingerprints[]`: `{fp_hash, first_seen, last_seen, banned, current, users:[{id, name, instagram, banned, auto_banned}]}`
- `sharing`: unused by the UI
- `photos`: up to 1000

**Layout** `.adm-userpage`:
- Phone order: profile, pause, ban, uploads, fps, device.
- At ≥1000px there are two columns with grid areas "profile uploads" / "pause uploads" / "ban uploads" / "fps uploads" / "device uploads".

**Panels:**

1. **Profile** `section.adm-panel[data-testid=profile]`:
   - `h1.adm-profile-name[data-testid=user-name]` `🙂 ${name}`.
   - Status badge `[data-testid=user-status]`: "🚫 AUTO-GESPERRT" or "🚫 GESPERRT" (`--ban`), otherwise "✓ Aktiv".
   - Handle: `span.adm-user-insta[data-testid=user-insta]` `@x`, or "kein Instagram angegeben".
   - With a handle: "📋 Handle kopieren" (`copyText('@x')`) and "Profil ↗" (new tab).
   - A `dl` with:
     - "Einwilligung" `${absTime(consent_at)} (Version ${consent_version})`
     - "Erstmals da" `absTime(created_at)`
     - "Zuletzt da" `relTime` with an absTime title (static)
     - "Fotos" `photo_count`
     - "Gast-Nr." `#id`
   - **Nothing is editable.** There is no rename and no Instagram edit.

2. **Uploads / pause:** `guestUploadsPanel(u, {onChanged: load})`, see §9.4.

3. **Ban panel, when not banned** `section[data-testid=ban-panel]`:
   - `h2[tabindex=-1]` "🚫 Sperren".
   - Text: "Versteckt alle Fotos dieses Gastes und blockiert weitere Uploads. Lässt sich jederzeit rückgängig machen."
   - `field('Grund (optional, nur für euch)', input#ban-reason.vb-input[maxlength=200][placeholder="z. B. unpassende Fotos"][data-testid=ban-reason])`.
   - `label.adm-check[for=ban-fp]` with `input#ban-fp[type=checkbox][data-testid=ban-fp]`, disabled when there is no `fp_hash`, and the text "Fingerprint auch sperren", plus " (kein Fingerprint bekannt)" when disabled.
   - A warning that is always visible, `div.adm-warn[data-testid=fp-warning]`: "⚠️ Vorsicht mit dem Fingerprint. " (bold) + "Er ist nur ein Geräte-Merkmal, keine Identität: gleiche Handymodelle (z. B. zwei gleiche iPhones) haben oft denselben. Jedes neue Gerät mit diesem Fingerprint startet dann gesperrt, auch Unbeteiligte. Nur für Störer, die sich immer wieder neu anmelden." If others share the current fingerprint, it adds `${sharingText(n)} schon.` + " Diese bereits bekannten Gäste bleiben unberührt." `sharingText` is "1 anderes Gerät teilt diesen Fingerprint" or "N andere Geräte teilen diesen Fingerprint".
   - `button[data-testid=ban]` "🚫 Gast sperren":
     1. Open the confirm dialog: title `${name} sperren?`; text `Das sichtbare Foto wird` (1 visible) or `Alle ${visible} sichtbaren Fotos werden`, then ` versteckt, weitere Uploads sind blockiert.`, plus " Zusätzlich wird der Fingerprint gesperrt." when the checkbox is ticked; confirm button "🚫 Gast + Fingerprint sperren" or "🚫 Gast sperren"; danger.
     2. On OK: disable the button and send `POST /api/admin/users/{id}/ban {reason: trimmed, fingerprint}`.
     3. Toast "Gast und Fingerprint gesperrt" if `res.fingerprint_banned`, otherwise "Gast gesperrt".
     4. `await load()`, then `focusPanel('ban-panel')`, which focuses the panel's h2.
     5. On error: re-enable and toast.

4. **Ban panel, when banned** `section.adm-panel--ban[data-testid=ban-panel]`:
   - `h2[tabindex=-1]` "🚫 Automatisch gesperrt" or "🚫 Gesperrt".
   - For an auto ban, `div.adm-warn.adm-warn--auto[data-testid=auto-ban-note]`: "🧬 Automatisch gesperrt. " + `Dieses Gerät hat sich neu angemeldet, mit ${autoBanSource(u)}. Gleiche Handymodelle haben oft denselben Fingerprint: vielleicht ist das jemand anderes. Entsperren betrifft nur dieses Gerät.`
   - A `dl`: "Seit" absTime; "Grund" `ban_reason||'–'` (for auto bans the server reason is "Gerät gesperrt (Fingerprint)").
   - Text: "Entsperren zeigt die Fotos wieder, die durch die Sperre versteckt wurden. Von Hand runtergenommene bleiben versteckt."
   - If any of the guest's fingerprints are banned: `input#unban-fp[data-testid=unban-fp]` with `Fingerprint-Sperre auch aufheben (${count})`. If there are auto-banned peers, a hint is added: ` Entsperrt auch ${p} weiteres Gerät, das|weitere Geräte, die nur deshalb gesperrt ist|sind.`
   - `button[data-testid=unban]` "✅ Entsperren", with no confirmation:
     1. `POST …/unban {fingerprint: checked}`.
     2. `unbanToast(fingerprints_unbanned.length ? 'Gast und Fingerprint entsperrt' : 'Gast entsperrt', users_unbanned)`.
     3. `load()` and `focusPanel('ban-panel')`.

5. **Uploads** `section.adm-section[data-testid=uploads]`:
   - h2 "📸 Uploads" with `span[data-testid=uploads-count]`: `(N)`, or `(N, davon K versteckt)`, or "(0)".
   - Grid `[data-testid=user-photos]` of photoTiles with no checkbox and no user link.
   - Empty: "Keine Uploads." / "Dieser Gast hat (noch) keine Fotos hochgeladen."
   - The lightbox list is the grid; its actions are `managementActions`.
   - Deleting removes the photo, then refreshes the lightbox, syncs the count and refocuses. The profile "Fotos" count is not updated.

6. **Fingerprints** `section[data-testid=fingerprints]`:
   - `h2[tabindex=-1]` `🧬 Fingerprints (N)`, then "Ein Hinweis, kein Beweis: gleiche Handymodelle haben oft denselben Fingerprint." When there are none: "Kein Fingerprint bekannt."
   - Each `div.adm-fp[data-testid=fp]` shows:
     - the hash `${hash16}…` with the full hash as title
     - "aktuell" (`--info`) and/or "GESPERRT" badges
     - `erstmals ${absTime} · zuletzt ${relTime}`
     - when shared: `strong[data-testid=fp-shared]` `${sharingText(n)}:` and chips `🙂 name` + ` · @insta` + banMark; otherwise "Kein anderes Gerät hat diesen Fingerprint."
   - A banned fingerprint gets `button[data-testid=unban-fingerprint]` "✅ Fingerprint entsperren":
     1. `DELETE /api/admin/device-bans/{hash}`.
     2. The toast reads "Fingerprint und Gast entsperrt" if this guest was among `users_unbanned` ("an auto-banned guest's own page: lifting the ban releases this guest too"), otherwise "Fingerprint entsperrt". The other released guests are appended to the toast.
     3. `load()` and `focusPanel('fingerprints')`.
   - There is no per-fingerprint "ban" action.

7. **Device** `section[data-testid=device]`, h2 "📱 Gerät", a `dl`:
   - "Gerät": `describeUA(user_agent||fp_components.ua)`
   - "Bildschirm": `c.screen`
   - "Grafik": `gl_renderer` plus `(gl_vendor)` if different
   - "Sprache": `c.languages`
   - "Zeitzone": `c.timezone`
   - "Leistung": `N Kerne · M GB RAM`
   - "IP": `last_ip (zuerst first_ip)` when they differ
   - "User-Agent": mono
   - Any missing value shows '–'.

**Re-render and focus logic:**
- `render()` takes a snapshot first: the focused control (by `#id`, else `[data-testid]`, else the panel `h2`), the typed ban reason and the fingerprint checkbox state.
- It clears and refills `photosCol`, then rebuilds the whole root.
- If the lightbox is open it calls `lightbox.refresh()`. Otherwise it restores the reason, the checkbox (only if not disabled) and the focus.

**refresh()** ("reload without throwing away what the admin is typing"):
1. `GET` the user again.
2. Compare `panelKey`: banned, ban_reason, instagram, fp_hash, auto_ban, uploads_paused, uploads_paused_source, and per fingerprint `[hash, banned, users [id, banned, auto_banned]]`.
3. If it changed, run a full `render()`.
4. Otherwise sync the photos in place (remove missing ones, upsert all), `lightbox.refresh`, `syncUploads`.
5. Errors are silent.
- Name, last_seen and photo_count are not part of the key, so they go stale.

**SSE (`onEvent`):**
- Ignored until data has loaded.

| Event | Effect |
|---|---|
| photo.created (this user) | upsert and `syncUploads` (no lightbox refresh) |
| photo.hidden / unhidden (known photo) | upsert, `lightbox.refresh`, sync |
| photo.deleted (known photo) | remove, `lightbox.refresh`, sync |
| user.banned / unbanned for this user | `load()` |
| user.banned / unbanned for a user sharing a fingerprint | `refresh()` |
| fingerprint.* | `refresh()` |
| user.uploads_changed including this user | `refresh()` |

- `onResync` calls `refresh()`.

---

## 7. Lightbox (admin.js `Lightbox`)

**Construction:** `new Lightbox({list: () => photos[], actions: (photo, lb) => nodes[]})`.

**`open(id)`:**
- On the first open:
  - Remember the opener (`document.activeElement`).
  - Create `div.adm-lightbox[role=dialog][aria-modal=true][aria-label=Foto][data-testid=lightbox]` with a `focusin` listener that records `lastFocus = focusKey(target)`.
  - Append it to `body` and add `body.adm-noscroll` (overflow hidden).
  - `inertOthers(el)` and `document.addEventListener('keydown', …)` (bubble phase).
  - `history.pushState({admLightbox:true}, '')` and a `popstate` listener that runs `teardown()`. The phone back button closes the lightbox.
- Render, then on the first open focus `[data-testid=lightbox-close]`.
- Calling `open` while already open only switches the photo; no new history entry is added.

**Render:**
- Finds the photo by `currentId` in `list()`. If it is missing, `close()`. Stores `lastIndex`.
- Root: class `adm-lightbox` plus `is-hidden` when hidden (the image is dimmed to 0.55); `aria-label="Foto ${photoTitle}"`.
- Top bar `.adm-lb-top`:
  - `button[data-testid=lightbox-close]` "✕ Schließen"
  - `span.adm-lb-count` `${i+1} / ${n}`
  - `.adm-lb-navs`: "‹" with `aria-label="Neueres Foto"` (disabled at index 0) and "›" with `aria-label="Älteres Foto"` (disabled at the last index). There is no wrap-around.
- Stage `.adm-lb-stage`:
  - A click on the stage background (not the image) closes the lightbox.
  - `img[data-testid=lightbox-img][alt=photoTitle]`: the thumb loads first, then the full size. A `new Image()` preloads `photo.url`, and on load the src is swapped only if the photo is still current. There is no error handling and no neighbour preloading.
  - When hidden, a flag `.adm-lb-flag`: "🚫 Versteckt (Gast gesperrt)" (ban) or "🙈 Versteckt: Gäste sehen es nicht".
- Panel `.adm-lb-panel`:
  - `.adm-lb-info`: title strong, statusBadge, timeEl, `${width}×${height}`, metaText.
  - `.adm-lb-user`: userLink (a link to the user page; navigating away leaves the history entry).
  - `.adm-lb-actions`: the result of `actions(photo)`.
- **Refocus after re-render:** if focus was inside the lightbox, or focus was lost (using `lastFocus`), it focuses the control with the same `focusKey` in the new DOM, otherwise the close button.

**Keys** (`key(event)`):
1. If any `.adm-dialog-scrim` exists, return. The confirm dialog or uploads sheet on top owns the keyboard.
2. Tab: `keepTabInside`.
3. If the target is INPUT, TEXTAREA or SELECT, return.
4. Escape closes; ArrowLeft calls `step(-1)` (newer); ArrowRight calls `step(1)` (older).

There is no Home/End, no wrap and **no swipe or touch gesture support**.

**`close()`:**
- If `history.state.admLightbox`, set `closing = true` and call `history.back()`; the resulting popstate runs `teardown`. Otherwise call `teardown` directly.
- The `closing` flag prevents a second `back()` when both the API response and the SSE event report the same deletion ("must not go back once more, off the page").

**`teardown()`:**
1. Remove the listeners and `noscroll`, and release the inert state.
2. If the current photo is gone, the neighbours are `ids[lastIndex]` and `ids[lastIndex-1]`.
3. Remove the element and reset state.
4. Focus, in order: the visible thumb of the last shown photo, then the opener, then the neighbours' thumbs.

**`refresh()`:**
- No-op if closed or closing.
- If the current photo has left `list()`, it closes ("deleted elsewhere"). There is no advance to the next photo.
- Otherwise it re-renders.
- `isOpen` is a getter.

**Actions inside, per page:**
- live: toggle only.
- manage and user: download, copy handle, toggle, delete. Delete opens the confirm dialog on top of the lightbox (z 1600 over 1500), and the lightbox is made inert while it is open.

---

## 8. Confirm dialog (admin.js `confirmDialog`)

**Implementation:** a custom element, not `<dialog>`. Returns `Promise<boolean>`.
- Backdrop: `div.vb-scrim.adm-dialog-scrim[data-testid=confirm]`.
- Dialog: `div.vb-sheet.adm-dialog[role=alertdialog][aria-modal=true][aria-labelledby=adm-dialog-N-title][aria-describedby=adm-dialog-N-text]`, where `aria-describedby` is set only when there is text.
- Contents: `h2#…-title`, `p.vb-muted#…-text`, the optional `extra` node (unused), and `.vb-actions` with:
  - OK `[data-testid=confirm-ok]`, `vb-btn--danger` when `danger`, otherwise `--primary`, block width.
  - Cancel `[data-testid=confirm-cancel]` "Abbrechen", ghost, block width.

**Behaviour:**
- Keydown is registered in the **capture** phase on `document`. Escape calls `stopPropagation` and resolves false. Other keys go to the Tab trap.
- Clicking the backdrop itself resolves false.
- `inertOthers(backdrop)`.
- Initial focus is on **Cancel when `danger`**, otherwise OK ("Enter on a destructive question must not destroy anything").
- On close: remove the listener, release inert, remove the element, `focusFirst(opener)`, resolve.
- Scroll is not locked.

**Used for:**
1. Photo delete: single from a tile, single from the lightbox, and bulk. Texts:
   - Title: `${photoTitle} endgültig löschen?` for one photo, `${n} Fotos endgültig löschen?` for several.
   - Text: "Die Bilddateien werden sofort vom Server gelöscht. Das lässt sich nicht rückgängig machen. Zum Verstecken reicht „Runternehmen“."
   - Confirm button: "🗑 Endgültig löschen" or `🗑 ${n} Fotos endgültig löschen`.
   - danger.
2. Banning a guest (§6).

**Not confirmed:** hide, unhide, bulk hide or unhide, unban guest, unban fingerprint, pausing or allowing one guest's uploads, **stopping all uploads**, starting the new-guest pause, logout. Ending the new-guest pause uses a choice view inside the sheet rather than a confirm.

---

## 9. Upload controls (uploadcontrols.js)

### 9.1 State and data flow
- **Module-global** `state = {stop, pause}` and a `listeners` Set; `notify()` calls every listener.
- **`fetchState()`** loads both in parallel:
  - `GET /api/admin/upload-stop` returns `{enabled, since, by}`.
  - `GET /api/admin/upload-pause` returns `{enabled, since, period, by, affected, paused_total}`.
- `refresh` is `throttle(fetchState, 300)`. Errors are swallowed.
- **`listen()`** registers once through `onAdminEvent`:

| Hook event | Effect |
|---|---|
| settings.upload_stop | `state.stop = data.upload_stop`; notify |
| settings.upload_pause | `state.pause = data.upload_pause`; notify (`restored`/`kept` are ignored) |
| user.uploads_changed | `syncPausedMarks(data.users)` and `refresh()` (for the counts) |
| user.created with `data.uploads_paused` | `refresh()` |
| resync (any reason) | `refresh()` |

- **`clock(iso)`**: "HH:MM" if the date is today, otherwise "Fr., HH:MM". Invalid gives '–'.
- **`uploadStatus()`** returns `{kind, text}`:
  - Either value missing: loading, "Uploads …".
  - Stop on: stopped, `⏹ Alle Uploads gestoppt seit ${clock(stop.since)}`, plus ` · ⏸ neue Gäste pausiert` when the pause is also on.
  - Pause on: paused, `⏸ Neue Gäste pausiert seit ${clock(since)} · ${affected} betroffen`.
  - Otherwise: ok, "🟢 Uploads laufen". Individually paused guests are not reflected in the chip.
- There are no countdowns or ticking timers. Times are absolute and only re-rendered on notify.

### 9.2 Header chip (`mountUploadControls(slot)`)
Used on live (below the stats) and manage (above the tabs). The slot `.adm-uploads-slot` is hidden while `:empty`.
- `button.adm-uploads-chip[data-testid=uploads-chip][aria-haspopup=dialog][title="Uploads steuern"][data-state=loading|ok|paused|stopped]` containing `span.adm-uploads-chip-text[data-testid=uploads-chip-text]` and an `aria-hidden` "›". There is no `aria-expanded`.
- CSS: ok and loading are a small muted pill. paused is yellow, stopped is red with a glow; both wrap to two lines.
- On mount: `fetchState().catch(showError)`, so an error toast can appear on page load. Clicking calls `openSheet()`.

### 9.3 Sheet (`openSheet`)
**Structure:**
- Singleton (`openSheetEl`).
- `div.vb-scrim.adm-dialog-scrim[data-testid=uploads-sheet]` containing `div.vb-sheet.adm-dialog.adm-uploads-sheet[role=dialog][aria-modal=true][aria-labelledby=adm-uploads-title]`.
- Two views: main and end-pause. The sheet re-renders completely (`replaceChildren`) on every notify and on every busy change.

**Main view:**
- Head: `h2#adm-uploads-title` "Uploads" and `button[aria-label=Schließen][data-testid=uploads-close]` "✕". A spinner shows while the state is missing.
- `p.adm-uploads-status[data-state][data-testid=uploads-status]` with the status text.
- Option **stop**: `section.adm-uploads-opt--stop[.is-on][data-testid=upload-stop]`.
  - Title `strong#adm-uploads-stop-label` "⏹ Alle Uploads stoppen".
  - State `[data-testid=upload-stop-state]`: `Gestoppt seit ${clock}` or "Aus".
  - Switch: `button.adm-switch[role=switch][aria-checked][aria-labelledby=adm-uploads-stop-label][data-testid=upload-stop-switch]`, disabled while busy.
  - Text: "Niemand kann hochladen, auch bekannte Gäste nicht. Für kurze Pausen, z. B. bei einer Flut unpassender Fotos. Einzelne Pausen und „Neue Gäste pausieren“ bleiben dabei, wie sie sind."
  - Toggling sends `POST /api/admin/upload-stop {enabled: !enabled}`, sets `state.stop = res`, notifies, and toasts "⏹ Alle Uploads gestoppt" or "▶ Uploads laufen wieder".
- Option **pause**: `[data-testid=upload-pause]`.
  - Title "⏸ Neue Gäste pausieren".
  - State: `Neue Gäste können seit ${clock(since)} nichts hochladen · ${affected} betroffen`, or "Aus".
  - Text: "Wer ab jetzt neu dazukommt, kann nichts hochladen. Bekannte Gäste laden weiter hoch. Beim Ausschalten entscheidest du, ob die Betroffenen freigeschaltet werden."
  - Turning on: `POST /api/admin/upload-pause {enabled:true}`, then the toast "⏸ Wer ab jetzt neu dazukommt, kann nichts hochladen".
  - Turning off: switches to the end-pause view; no request yet.
- If `paused_total > 0`: `a.adm-uploads-link[href="/admin/manage?tab=gaeste&show=paused"][data-testid=uploads-paused-list]` `⏸ ${n Gast|Gäste} pausiert · ansehen ›`.
- Footer: "Einzelne Gäste pausierst du auf ihrer Seite (Gäste › Name)."

**End-pause view** (n = `pause.affected`):
- Head: "Pause für neue Gäste beenden".
- `p[data-testid=pause-end-text]`: with n > 0, `${'1 Gast ist' | n+' Gäste sind'} beigetreten, während die Pause lief, und ${kann|können} noch nichts hochladen. Was soll mit ${ihm|ihnen} passieren?`; with n = 0, "Während der Pause ist niemand neu dazugekommen.".
- Buttons:
  - `[data-testid=pause-end-restore]` (primary): "▶ Den 1 in der Pause beigetretenen Gast wieder freischalten" / `▶ Alle ${n} in der Pause beigetretenen Gäste wieder freischalten`, or "▶ Pause beenden" when n = 0. Calls `endPause(true)`.
  - `[data-testid=pause-end-keep]`, only when n > 0: "Nur ab jetzt wieder erlauben – der eine bleibt pausiert" / `Nur ab jetzt wieder erlauben – die ${n} bleiben pausiert`. Calls `endPause(false)`.
  - `[data-testid=pause-end-back]` "Zurück" returns to the main view.
- Footer: "Von Hand pausierte Gäste bleiben in jedem Fall pausiert."
- `endPause(restore)` sends `POST /api/admin/upload-pause {enabled:false, restore}`, which returns state plus `{changed, restored: count, kept: count}`. It switches back to the main view. Toast:
  - restored > 0: `▶ ${n Gast|Gäste} wieder freigeschaltet`
  - kept > 0: `▶ Neue Gäste können wieder hochladen – ${kept} bleibt|bleiben pausiert`
  - otherwise: "▶ Neue Gäste können wieder hochladen"
- Every request runs through `run()`: busy is set (controls disabled), errors go to `showError`, and `finally` re-renders.

**Keyboard and focus:**
- Keydown is registered in the capture phase on `document`. Escape calls `stopPropagation`; in the end-pause view it goes back to main, in the main view it closes.
- Clicking the scrim closes the sheet from either view.
- Initial focus: `dialog.querySelector('.adm-switch, button')` returns the first match in **DOM order**, which is the ✕ close button, not a switch.
- Opening also calls `refresh()`.
- There is **no** Tab trap, **no** inert background and **no** focus return to the chip on close. Every re-render drops focus to `<body>`. This is inconsistent with confirmDialog.

### 9.4 Guest uploads panel (`guestUploadsPanel(u, {onChanged})`, user page)
- `section.adm-panel.adm-uploads-guest[.is-paused][data-testid=guest-uploads]`, h2 "📤 Hochladen".
- Status badge `[data-testid=guest-uploads-status]`: "⏸ Uploads pausiert" (`--pause`) or "✓ Darf hochladen" (`--ok`).
- When paused, `span.adm-uploads-source[data-testid=guest-uploads-source]` from `pauseSource(u)`:
  - Source `new_guest_lock`, with the lock still on and `pause.period === u.uploads_lock_period`: `automatisch: neue Gäste pausiert seit ${clock(pause.since)}`.
  - Source `new_guest_lock` otherwise: `automatisch: beigetreten während der Pause für neue Gäste (${absTime(u.uploads_paused_at)})`.
  - Manual: `manuell pausiert · seit ${clock(u.uploads_paused_at)}`.
- When the stop switch is on, `p.adm-warn`: `⏹ Gerade sind ohnehin alle Uploads gestoppt (seit ${clock}).`
- Text: "Pausieren ist keine Sperre: Die Fotos bleiben sichtbar, der Gast kann sich weiter umsehen und seinen Instagram-Namen ändern. Er sieht einen freundlichen Hinweis."
- Button `[data-testid=guest-uploads-toggle]`: "▶ Uploads erlauben" (`adm-toggle--show`) or "⏸ Uploads pausieren" (`adm-uploads-pausebtn`, yellow). No confirmation.
  1. `POST /api/admin/users/{id}/uploads {paused: !paused}`.
  2. `Object.assign(u, res.user)`; this mutates the page's `data.user`.
  3. Toast `⏸ Uploads von ${name} pausiert` or `▶ ${name} darf wieder hochladen`.
  4. `onChanged(res.user)`, which on the user page is a full `load()`.
- Registers itself as a listener and re-renders on notify. When it finds itself detached after a page re-render, it removes itself.
- If the pause state is not known yet, it calls `refresh()`.

### 9.5 Badges
- **`pausedBadge(user)`** (guest rows in manage): `span.adm-badge--pause.adm-badge--xs[data-testid=paused-badge]` "⏸ Uploads pausiert", title "automatisch: in der Pause für neue Gäste beigetreten" or "manuell pausiert".
- **`syncPausedMarks(users)`**: on `user.uploads_changed`, it finds `a[data-testid="user-link"][href="<userUrl>"] .adm-user-name` and adds or removes the "⏸" paused-mark span in the DOM only.

---

## 10. SSE (admin.js `connectEvents`)

**Connection:**
- `new EventSource('/api/admin/events')` (same-origin cookie).
- Server behaviour:
  - The first chunk is `retry: 3000`.
  - A heartbeat `: ping` is sent every 15 s.
  - Each event is framed as `id:`, `event: <type>`, `data: <json>`.
  - The server re-checks the admin session at most every 30 s while sending chunks and ends the stream once the session is gone.

**Event names listened to** (`EVENT_TYPES`):
- `photo.created`, `photo.hidden`, `photo.unhidden`, `photo.deleted`
- `user.created`, `user.banned`, `user.unbanned`
- `fingerprint.banned`, `fingerprint.unbanned`
- `user.uploads_changed`, `settings.upload_pause`, `settings.upload_stop`

Each event's data is `JSON.parse`d (parse errors are dropped), then `onEvent(type, data)` runs (errors go to `console.warn`), then the `runHooks` hooks run.

**Payloads:**

| Event | Payload |
|---|---|
| photo.created / hidden / unhidden | `{photo}` (admin_view) |
| photo.deleted | `{id, photo}` |
| user.banned / unbanned | `{user, photos[]}` |
| fingerprint.banned | `{fp_hash, user_id}` |
| fingerprint.unbanned | `{fp_hash}` |
| user.created | `{id, name, banned, uploads_paused}` |
| user.uploads_changed | `{users[], paused}` |
| settings.upload_stop | `{upload_stop}` |
| settings.upload_pause | `{upload_pause, restored[], kept[]}` |

The `photo.user` object inside photo payloads has `{id, name, instagram, banned, uploads_paused}` and **no `auto_banned`**.

**Reconnect logic:**
- **open**: status live, `stopPolling()`; if `stale`, clear it and resync with reason `'reconnect'`.
- **error**:
  - Sets `stale = true`, status reconnecting ("Verbinde neu…") and `startPolling()`, which runs `setInterval(onResync('poll'), 5000)`.
  - If `readyState === CLOSED` ("the server refused (401, proxy error): EventSource gives up, we don't"): close it, run `checkSession()` (`GET /api/admin/session`; if `!authenticated`, `goLogin()`; offline errors are ignored), and `setTimeout(open, 4000)`.
  - Otherwise the browser reconnects by itself after the server's 3000 ms retry.
- **No EventSource support**: status polling ("Abruf alle 5 s") and permanent polling.
- **visibilitychange to visible**: "phones freeze background tabs; the stream may be dead without an error". If the stream is not OPEN, close it, set `stale = true` and reopen (resync then happens on open). Otherwise resync with reason `'visible'`.
- **Every resync** calls the page's `onResync(why)` and then the `'resync'` hooks.
- Returns `{close()}`, which no page uses. `onStatus`, `pollMs` and `retryMs` are never overridden.

Pages connect only after their initial fetch completes. Events in the window between the initial GET and the stream opening are missed until the next resync.

**Per-page effects** are covered in §4 (live), §5.7 (manage), §6 (user) and §9.1 (upload controls).

---

## 11. Keyboard, focus and a11y summary

**Keyboard map:**
- Manage tabs: ←/→ wrap, Home, End, with automatic activation (§5.1).
- Lightbox: Esc closes, ← newer, → older, Tab trapped; keys are ignored while a dialog scrim is open or focus is in a form field.
- Confirm dialog: Esc cancels (capture phase plus `stopPropagation`), Tab trapped.
- Uploads sheet: Esc goes back or closes; no Tab trap.
- Login: Enter submits.
- There are no other global shortcuts.

**Focus management:**
- Lightbox: on open, the close button; on close, the last photo's thumb, the opener or a neighbour; controls rebuilt during re-render are refocused.
- Confirm: on open, Cancel (danger) or OK; on close, the opener.
- `runToggle` keeps focus on the toggle after re-render.
- `PhotoCollection.upsert` keeps focus on the same control.
- `refocusAfterRemoval` after deletes.
- User page: snapshot and restore; after ban, unban or fingerprint unban, the panel `h2[tabindex=-1]` is focused.

**`inert`:** set on body siblings by the lightbox and confirm, but not the toast host. They nest.

**ARIA:**
- tablist / tab / tabpanel with `aria-selected`, `aria-controls`, `aria-labelledby` and a roving `tabindex`.
- `role=alertdialog` + `aria-modal` + `aria-labelledby`/`aria-describedby` (confirm).
- `role=dialog` + `aria-modal` + `aria-label="Foto <title>"` (lightbox).
- `role=dialog` + `aria-labelledby` (sheet), and `role=switch` + `aria-checked` (switches).
- `aria-pressed` (segmented controls), `role=group` (stats "Zähler", segmented), `role=toolbar` "Auswahl" (bulkbar).
- `aria-live=polite` on `#feed` (live) and on the toast host; `role=alert` on `#login-error`.
- `aria-haspopup=dialog` on the chip.
- `aria-label` on the selects, the search, the thumbs (`<title> groß anzeigen` / `<title> ansehen`), the checkboxes, delete, unban buttons, lightbox nav, close and logout.
- `aria-hidden` on decorative chevrons and the switch knob.

**Visual focus:** cyan `:focus-visible` outlines on thumbs, tabs, panels, segmented buttons, chips, links, the uploads chip and switches. Selects and search show a cyan border on focus.

**Contrast:** `.adm-badge--hidden` and `.adm-toggle--hide` use #d4144e ("white on --vb-red is 3.3:1; this red keeps the loud look at 5.2:1"). The selected tab's count has opacity 1 (faded dark on pink is below 4.5:1). `tests/e2e/test_admin_a11y_e2e.py` asserts ≥ 4.5.

**Touch targets:** 44px minimum height on most buttons, 46px tile checks, 68×42 switches.

---

## 12. Storage, timers, polling, visibility

**Storage:**
- No `localStorage` or `sessionStorage` in the admin JS.
- vb.js uses sessionStorage `vb_debug` and `vb_debug_folded` when `?debug` is set. `vb_uid` is guest only.
- Lightbox state lives in `history.state.admLightbox`.

**Intervals and timeouts:**
- 30 s: refresh relative times (admin.js, global).
- 60 s: live stats.
- 5 s: SSE fallback polling.
- 4 s: retry after a CLOSED EventSource.
- 6 s: loader watchdog.
- Toasts: 2800 ms by default, 5000 ms for errors and unban-with-release.

**Throttles and debounces:**

| What | Delay |
|---|---|
| live stats | 800 ms |
| manage stats | 400 ms |
| user select refresh | 1500 ms |
| `invalidate` default | 800 ms |
| instagram / gaeste on photo.created | 2000 ms |
| protokoll | 1500 ms |
| resync of a non-Fotos tab | 100 ms |
| upload-state refresh | 300 ms |
| guest search (debounce) | 250 ms |

**IntersectionObservers:** live `#more` (400px root margin) and manage `fotosMore` (600px). Guests and audit use buttons only.

**visibilitychange:** only in `connectEvents` (§10).

---

## 13. Error handling by situation
- **401 `admin_required`** from any aapi call: redirect to `/admin/login?next=<pathname>` and the promise never resolves. A 401 on the SSE stream is handled through `checkSession` → `goLogin`.
- **Page load without a session:** the server returns 303 with `next` including the query.
- **403 `bad_origin`, 400, 404, 422:** the server's German message as a toast. Special cases:
  - user page 404: "Gast nicht gefunden." view
  - audit photo link 404: "Das Foto wurde gelöscht."
- **429:** login only; the message carries the "(in N s nochmal)" suffix.
- **Network errors:** toasts with the vb texts. Silent in live `resync` (network code only), manage `resyncPhotos`, user `refresh`, both `loadStats`, upload refreshes and `checkSession`.
- **Initial `main()` failure:** toast only, with no full-screen `fatal()` and no retry.

---

## 14. Workarounds and edge cases visible in the code (regression risks)
1. `aapi` 401: a never-resolving promise and a once-only redirect flag.
2. `safeNext` regex prevents open redirects. The e2e tests `test_login_never_redirects_off_site` and `test_login_returns_to_user_page_with_id` cover it.
3. Clipboard fallback for plain http on a LAN IP.
4. The `created_at` string comparison relies on ISO-8601 UTC.
5. Focus is preserved across in-place re-renders (`focusKey` = data-testid || aria-label || text). **Testids are functional**, so renaming them breaks focus restore.
6. `runToggle` keeps focus because "a disabled button may drop the focus".
7. Lightbox `closing` flag: guards against a double `history.back()` when the API and SSE both report a deletion. Tested by `test_delete_from_lightbox_asks_on_top`, which expects the URL unchanged after a single step back.
8. Lightbox: when the shown photo is deleted, focus moves to its neighbours by `lastIndex`. The thumb shows first and the full image swaps in only if the photo is still current.
9. Lightbox keys are ignored while `.adm-dialog-scrim` exists. Confirm Escape uses the capture phase and `stopPropagation` so the lightbox does not close as well.
10. Confirm on a destructive action focuses Cancel. The dialog z-index of 1600 sits above the lightbox's 1500 and below toasts.
11. `inertOthers` skips the toast host so results are still announced, and supports nesting.
12. EventSource "gives up" on 401 or proxy errors, so the code reconnects manually and checks the session. Phones freeze background tabs, so the stream is checked on `visibilitychange`.
13. Throttle rather than debounce: refreshes still fire during a steady stream of events.
14. Live scroll compensation (`overflow-anchor: none`), the at-top threshold of 60px, and the pill.
15. Window-based deletion detection on resync (live and manage).
16. Live loads stats immediately so "–" is not shown.
17. Manage: deletions are counted once (`fotos.gone`); `reqId` drops stale responses; newer photos found on resync go to the pill rather than being inserted.
18. Manage: the selects have `aria-label` because the visible labels are hidden on phones (`test_filter_selects_have_names_on_a_phone`). The selected tab is scrolled into view, including after the counts load.
19. Manage bulk delete keeps the selection when cancelled.
20. User page: `snapshot`/`restore` keeps the typed ban reason and checkbox across live re-renders; `panelKey` avoids needless rebuilds.
21. User page: the fingerprint-unban toast detects "this guest released too".
22. User page: a ban on a peer device that shares a fingerprint triggers `refresh()`.
23. The guest uploads panel listener removes itself when the panel is detached.
24. The server requires `restore` when ending the pause, so the UI forces a choice.
25. CSS: tab-row padding for the focus ring; a container query stacks the tile buttons and shows the "Löschen" label at ≤205px; manage hides the conn text at ≤480px; the user page hides the Verwaltung link at ≤520px; the bulkbar respects the safe area.
26. Live must never be able to delete (static test).

---

## 15. Existing bugs and inconsistencies (keep or fix knowingly)
1. `goLogin` uses only `location.pathname`. After the session expires on `/admin/user?id=5`, login returns to `/admin/user` and shows "Kein Gast ausgewählt.". `safeNext` also rejects every manage query (`?tab=…`), so the login falls back to `/admin/live`.
2. The audit-log photo lightbox uses a static list `() => [photo]`. Toggling does not update its UI, and deleting leaves it open on the deleted photo.
3. `invalidate()` caches each tab's throttle with the first `ms` ever used for it.
4. The Fotos tab is never invalidated. If it was loaded but hidden while events were missed (reconnect), it shows stale data until a manual filter change.
5. `patchPhoto` keeps photos that no longer match the status filter, and the total is not adjusted.
6. Bulk toasts have no singular form ("1 Fotos runtergenommen"). The ban confirm says "Alle 0 sichtbaren Fotos werden versteckt…" when there are none.
7. The Gäste empty text reads "Noch keine Gäste." even when a banned or paused filter is active.
8. Paused marks are patched only in the DOM (`syncPausedMarks`); a later re-render from photo data reverts them. Photo cards never show AUTO-GESPERRT because `photo.user` lacks `auto_banned`.
9. Uploads sheet: no focus trap, no inert background, no focus return, focus lost on every re-render, and initial focus on ✕. If another admin ends the pause while this admin is in the end-pause view, the view goes stale.
10. Lists are capped: the user select and the Sperren banned list take the first 500 users; the user page takes 1000 photos; "show new" takes 200, after which there can be a gap.
11. User page: "Zuletzt da" and "Fotos" are not refreshed by in-place refreshes or deletions. A non-404 load error leaves the spinner showing.
12. `main()` failures on live and manage produce a toast only, with no retry.
13. Live resync shows a toast for non-network errors on every 5 s poll, so it can spam.
14. `loadMorePhotos` resets `fotos.loading` in `finally` even for a stale request, which races with `reloadPhotos`.
15. The `autoBannedPeers` hint count can differ from the server's release rule: the server skips users who still have another banned fingerprint.
16. Lightbox: no swipe, no image-error state, no neighbour preload, no wrap-around. `photo.created` on the user page does not refresh the lightbox counter.
17. `show=paused` is dropped from the URL by `syncUrl`. The Sperren tab has no spinner; the Protokoll tab has no empty state.
18. Events between the initial fetch and the SSE open are missed (§10).
19. Dead code: `deletePhoto`, `PhotoCollection.rerender` and `oldest`, the confirm `extra` parameter, `data.sharing`, and the return value of `connectEvents`.

---

## 16. Code-quality notes
**Duplication:**
- `loadStats`/`refreshStats` appear in live and manage with different targets and throttles.
- Resync window logic is duplicated: live `resync` and manage `resyncPhotos`.
- `onToggle` wrappers exist three times (live, manage, user); `deletePhotos` twice (manage, user).
- Unban flows are duplicated: manage `bannedUserRow`/`fpBanRow` and the user page panels, with different toasts.
- Fingerprint user chips are rendered in two places.
- Paused indicators exist three ways: `userLink`'s paused-mark, `pausedBadge`, and the `syncPausedMarks` DOM patching.
- "Load more" is implemented four times with three cursor styles (photo id `before`, user `offset`, audit numeric id).
- Spinners are created in three places.
- Pluralisation is ad hoc everywhere.
- **Three dialog systems:** confirmDialog (trap and inert), the uploads sheet (neither), and vb.js `holdFocus`/`sheetOpen` (unused by admin, with a different `FOCUSABLE`).

**Large functions:**
- `openSheet` (~175 lines of closures)
- `connectEvents` (~90)
- `Lightbox.render` (~50)
- manage `onEvent` switch
- `renderInsta`, `fpBanRow`, `banPanel`/`bannedPanel`

**Global mutable state:**
- admin.js: `extMap`, `redirecting`, `dialogSeq`, `eventHooks`
- uploadcontrols.js: `state`, `listeners`, `hooked`, `openSheetEl`
- manage.js: `state`, `fotos`, `gaeste`, `insta`, `sperren`, `protokoll`, `panels` (with ad-hoc `loaded`/`dirty`), `reloadVisible`, `lightboxSource`
- live.js: `nextCursor`, `loadingMore`, `unseen`
- user.js: `data`, which `guestUploadsPanel` mutates via `Object.assign`

**DOM-query coupling:**
- `runToggle` queries `.adm-lightbox` and `[data-photo-id]`.
- `Lightbox.key` checks `.adm-dialog-scrim`.
- `syncPausedMarks` queries by `href`.
- `focusKey`/`focusRef` depend on testids and labels.
- `PhotoCollection.photos` derives order from DOM children.

**innerHTML:** none (test-enforced). Everything is `h()` plus `replaceChildren`, with whole-subtree re-renders: the full user page, every Instagram entry on each patch, and the full sheet on every notify.

**Coupling to vb.js and vb.css:**
- JS: `api`, `ApiError`, `h`, `toast`.
- CSS classes: vb-btn (--primary, --ghost, --danger, --cool, --big, --block), vb-icon-btn, vb-hidden, vb-spinner, vb-scrim, vb-sheet, vb-actions, vb-muted, vb-input, vb-label, vb-field-error, vb-card, vb-page, vb-grad-text, vb-toast-host.
- `--vb-*` tokens and the `vb-pop-in` keyframes.

---

## 17. Existing tests that pin this behaviour (in `tests/`)
**`e2e/test_admin_e2e.py`:**
- login via UI; no off-site redirect; return to the user page with id; rate-limit message; logout
- live: realtime and take-down; screens stay in sync; polling fallback (`conn` shows `data-state=reconnecting` and the card appears within 12 s)
- user link; delete needs confirmation; bulk and filters; lightbox download and copy; tabs; Instagram counts
- ban/unban; fingerprint unban releases auto-banned devices; one-tap unban of an auto-banned device
- user page on a phone; unknown user; no sideways scroll on phones
- event stream; back button closes the lightbox; infinite scroll

**`e2e/test_admin_a11y_e2e.py`:** tabs with arrows and roving tabindex; confirm focus, trap, inert and return; lightbox focus and keys; delete from the lightbox shows on top; tile delete refocuses a neighbour; select names on phones; contrast.

**`e2e/test_admin_upload_controls_e2e.py`:** pause then restore; pause then keep; pause one guest; stop and resume.

**`test_admin_pages.py`:** CSP-safe HTML and JS rules, import rules, live cannot delete.

The `data-testid` values listed throughout this report are what these tests select on.
