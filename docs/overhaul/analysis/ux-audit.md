# virtubooth UX/UI audit (phase 1: analysis, read-only)

The repo was not modified. I ran my own server on port 8121 (stopped at the end; the host's server on port 8000 was not touched) and seeded it through the real API: 13 guests (with and without handles, one 29-character handle), about 50 beer and booth photos, 2 hidden photos, 1 deleted photo, 1 guest banned with a fingerprint ban plus an auto-banned twin, 1 paused guest, and a stop-all / pause-new-guests round trip.

I took 172 screenshots and reviewed all of them through 38 montages. Scratch root: `<scratchpad>/ux-audit/`
- `shots/`: every state (naming scheme in section 10)
- `mont/`: the review montages
- `lib.py`, `phase_a.py`, `seed.py`, `moderate.py`, `phase_beer.py`, `phase_booth.py`, `phase_admin.py`, `phase_states.py`, `measure.py`: re-runnable. Point `lib.BASE` at the rebuilt app to get before/after shots.
- `guidelines.md`: the fetched Vercel rules (fetched raw with curl; WebFetch only returned a summary).

---

## 0. Summary

1. **There is no design system, so every screen is tuned on its own.** The CSS has:

   | Item | Distinct values |
   |---|---|
   | Font sizes | 41 |
   | Border radii | 20 |
   | Hex colours | 39 |
   | rgba colours | 74 |
   | Gradients | 19 |
   | Box shadows | 23 |
   | z-index levels | 17 |

   Weights 800 and 900 make up 42 of 55 weight declarations. A single admin screen renders 17–18 different font sizes. That is the main measurable reason it "looks sloppy".
2. **Everything is loud, so nothing leads.** The same pink→orange→yellow gradient fills primary buttons, the shutter, active tabs, headline text, the "new photos" pill and the progress bars. Every live card has a big red "Runternehmen" button, and almost every label starts with an emoji.
3. **Emoji are the icon system.** There are about 146 emoji in UI code, plus unicode glyphs (■ ⏸ ▶ ↻ ← ›), plus a few SVGs: three icon languages. Emoji render differently per OS (the logout 🚪 shows as a brown block), sit off the text baseline, and are read aloud by screen readers.
4. **The camera screens are designed like a web page, not a camera.** The 3:4 preview is a rounded card with a glow, sitting on a purple gradient, with controls in leftover space and dead bands above and below. Labels are 10.6–11.5 px.
5. **Overlays collide.** Toasts stack at the top and cover the back button and header, the upload sheet's title and close button, and the lightbox navigation. The pause chip floats over the Fotobox print. The filter name sits over the face. The bulk bar covers tiles.
6. **Admin density is wrong in both directions.**
   - Live on a 390 px phone shows about 3.5 photos per screen.
   - Manage in phone landscape shows **zero** photos under the sticky header.
   - Desktop is a stretched phone layout with small type in a lot of empty space.
   - Long explanatory paragraphs live inside the controls.
7. **Copy is inconsistent.** Hiding has five names (Runternehmen, runtergenommen, Versteckt, Wieder zeigen, Zeigen). "Nochmal" means three different things. Startseite and Übersicht are mixed, as are "Wird geloggt…" and "Wird hochgeladen …". English slips through: Download, Handle, Uploads.
8. **I found 12 behavioural bugs or UX defects (section 9).** The most important:
   - a stale "Keine Verbindung" error toast sits over the Beer Cam success screen;
   - a banned guest's page says "✓ Darf hochladen";
   - the Beer Cam lets a paused or stopped guest shoot and then throws the photo away.
9. **The host's after-party jobs (export, timelapse, QR sheet) have no UI; they are CLI-only.** Instagram tagging means downloading each photo one by one from the lightbox.
10. **Recommended direction: "Kontaktbogen"** (darkroom and contact sheet; section 6). Every photo is a frame on the party's film roll.
    - Guests and the live screen use a dark "safelight" mode.
    - Manage is a light "light table" with grease-pencil marks: an X for hidden, a circle for selected.
    - Hide (reversible pencil mark) and delete (gone) look clearly different, which supports the live = hide-only rule.
    - It works in a dark room, keeps the admin calm and dense, and is one brand across both.

---

## 1. Coverage

Viewports: phone 390×844 @2x, small phone 360×640 @2x, landscape 844×390 @2x (all mobile with touch and an Android user agent), and desktop 1440×900.

| Area | States captured (`shots/…`) |
|---|---|
| Gate / 404 | `g01-gate-{phone,small,land,desk}`, `g02-notfound-{phone,desk}` (phone without a cookie shows the gate, as designed) |
| Join | `g03-join-{phone,small,land,desk}`, `g03b-join-filled-phone`, `g03c-join-error-phone`, `g07-join-over-beer-phone`, `g08-join-over-booth-phone` |
| Home | `g04-home-firstjoin-phone` (confetti), `g05-home-{phone,small,land,desk}`, `g05b-home-nohandle-phone`, `s01-home-stopped`, `s05-home-paused`, `s10-home-banned` |
| User chip editor | `g06-chip-editor-{phone,small,desk}` |
| Beer Cam | Loading: `b00-loading`<br>Camera: `b01-camera-bottle-{4 vps}`, `b02-camera-cup-{phone,land}`, `b02-camera-cup-on-bottle`<br>Flow: `b03-uploading-{4}`, `b04-upload-error-{phone,small}`, `b05/b05b-success-{4}`<br>Hints and errors: `b06-inapp-hint`, `b07-camera-denied-{phone,desk}`<br>Moderation states: `s02/s03/s04` (stopped, its hint dialog, after a shot), `s06/s07` (paused), `s11` (banned) |
| Fotobox | Loading: `f00-loading`<br>Filters: `f01-camera-normal-{4}`, `f02-camera-{party,neon,comic,bw,emoji,vhs}-phone`, `f02-camera-party-{small,land,desk}`<br>Countdown: `f03-countdown-toggle-toast-{phone,desk}`, `f04-countdown-{phone,desk}`<br>Result: `f05-result-uploading-{phone,desk}`, `f06-result-done-{4}`<br>Failure: `f07-result-upload-error`, `f08-camera-outbox-chip`, `f09-leave-dialog`, `f10-camera-denied`<br>Moderation states: `s08-booth-paused-{phone,desk}`, `s09-booth-paused-result`, `s12-booth-banned` |
| Loader / fatal notices | `b08-loader-failed-phone`, `b09-fatal-noanswer-phone`, `b10-offline-phone` (offline reload shows the browser's own error page; the app has no offline shell) |
| Admin login | `a01-login-{phone,desk}`, `a01b-login-error-{phone,desk}` |
| Live | Empty: `a02-live-empty-{phone,desk}`<br>Filled: `a10-live-{phone,small,land,desk}`, `a10b-live-full-{phone,desk}`<br>Actions: `a11-live-after-hide`, `a12-live-lightbox-{phone,desk}`, `a13-live-newpill` |
| Upload controls | `a14`/`a40-uploads-sheet-{phone,desk}`, `a41-…-stopped`, `a42-…-pausenew`, `a43-live-header-pausenew`, `a44-uploads-pause-end-dialog` |
| Manage | Empty: `a03-manage-empty-{5 tabs}-{phone,desk}`<br>Filled: `a20-manage-{fotos,gaeste,instagram,sperren,protokoll}-{phone,desk}` (+ `-full`), `a20-manage-{fotos,gaeste}-{small,land}`<br>Selection and dialogs: `a21-…-bulkbar-{phone,desk}`, `a22-confirm-bulk-delete-{phone,desk}`, `a23-manage-lightbox-{phone,desk}`, `a24-confirm-delete-in-lightbox-{phone,desk}`<br>Filter: `a25-manage-gaeste-paused-filter-desk` |
| User page | `a30-user-{normal,banned,paused,autobanned}-{phone,desk}`, `a30b-user-{normal,banned}-phone-full`, `a31-user-ban-form-fp-{phone,desk}`, `a32-user-ban-confirm-{phone,desk}` |

DOM measurements are in `measure.json`: touch targets under 44 px, text under 13 px, and the set of font sizes per screen.

---

## 2. Why it reads as sloppy (root causes, in order of impact)

| # | Cause | Evidence |
|---|---|---|
| R1 | **No tokens or scale.** Spacing, radius, type and colour are set per component. | Counts in §0, item 1. Radii in use: 2, 3, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 50% and 999 px. Home h1 is `clamp(2rem,8vw,3rem)`, the sheet h2 is 1.7rem, admin h1 is 1.35rem, and the beer success title uses its own sizes. |
| R2 | **No hierarchy, because everything is emphasised.** | Gradient in 19 places. Weights 800/900 everywhere. Every live card has a red primary-sized button plus a green "✓ Sichtbar" badge (`a10-live-phone`). Tabs, chips, toggles and pills all use the same 999 px pill shape and weight. |
| R3 | **Three icon languages.** | Emoji (📸 🍺 🙈 🚪 ⏱️ 🔄 ⬇️ 📜 🧬), unicode glyphs (■ ⏸ ▶ ↻ ← › ✕), and SVG (Beer Cam back and switch). Beer Cam uses an SVG chevron for back; Fotobox uses the "←" glyph (`booth/static/index.html:18`). |
| R4 | **A template palette.** | Purple radial glow, pink/orange/yellow gradient and system-ui type could belong to any party app. Nothing says *Lena's birthday*, *beer*, *photo booth* or *night*. The only on-brand moments are inside the photos: the "Lenas Geburtstag" party frame (`f02-camera-party-phone`) and the bottle outline. |
| R5 | **Camera UI built as a page.** | `beer.css:145-155` and `booth.css:97-109` draw a rounded, glowing preview card. Dead purple bands sit above and below (`b01-camera-bottle-phone`). Controls float. Filter name sits at `top:42%`, over the face (`booth.css:136-146`). |
| R6 | **Overlays without a layout slot.** | Toasts fixed top-center, unlimited stack (`vb.css:342-353`). Pause chip fixed at `top:68px` (`vb.css:370-397`). New pill, bulk bar, filter-name pill. They collide with headers, prints and tiles (`a41`–`a43`, `s09`, `a21-…-phone`). |
| R7 | **Admin layouts are not designed per device.** | Phone: the sticky header takes about 190 px (3 rows: title/nav, stats, uploads chip, plus tabs on manage). Landscape: the header plus filters fill the screen (`a20-manage-fotos-land`). Desktop: phone components scaled into a 1440 canvas, small type, guests as full-width rows instead of a table. |
| R8 | **Copy drift.** | Section 3.4. The same concept has several names, the same word means several things, the same message is shown twice (toast plus inline, `b04`), and some copy is English. |
| R9 | **Explanations live inside controls.** | The upload sheet has two 4-line paragraphs inside the switch rows. Sperren opens with a 6-line paragraph. The user page has a 7-line fingerprint warning inline. Correct content, wrong place: it belongs in a "?" disclosure or the confirm dialog. |

---

## 3. Per-screen critique

Priority: **P0** breaks the job or loses data; **P1** clearly sloppy or real friction; **P2** polish. Guideline references use the Vercel Web Interface Guidelines section names (shortened, for example "Touch & Interaction").

### 3.1 Guest

**Gate (`g01`), 404 (`g02`)**

What works: a clear single message, centred.

| P | Issue |
|---|---|
| P1 | "So geht das leider nicht." is negative and vague. Say what to do: "Scanne einen der QR-Codes auf der Party." |
| P1 | Desktop: a 560 px column of small text in a 1440 void. This is the screen a host sees when testing on a laptop. |
| P2 | 📷 emoji as hero art; gradient headline text. |
| P2 | No hint for "QR code scanned, but in an Instagram or WhatsApp in-app browser". The Beer Cam has that hint; the gate doesn't. |

**Join sheet (`g03`, `g07`, `g08`)**

What works:
- one button, no "no" option (as the invariant requires);
- the split layout keeps the button on screen on small phones;
- inline handle validation ("Instagram-Namen haben keine Leerzeichen.").

| P | Issue |
|---|---|
| P1 | About 110 words before the input (3 paragraphs, `identity.py:108-115`). Slightly drunk people won't read it. Lead with one sentence (photos are stored and may be posted on @lenas.party) and move the device-recognition detail into a disclosure ("Mehr dazu"). It still has to be visible before the button, and wording changes need a `VB_CONSENT_VERSION` bump. |
| P1 | "…nutze die Fotobox bitte nicht" names one activity even when the guest scanned the Beer Cam code (`g07`). Use "…mach hier bitte keine Fotos." |
| P1 | The Instagram label is a bold two-sentence run-on ("Dein Instagram (freiwillig). Dann markieren wir dich!"). Use a label "Instagram (freiwillig)" plus helper text "Dann können wir dich markieren." |
| P1 | The sheet doesn't say where you are going ("Gleich geht's zur Beer Cam"). The party name is blurred behind the scrim. |
| P2 | Straight apostrophe and emoji in the CTA, "los geht's! 🍻" (`identity.py:117`); use ’. The placeholder "@deinname" is shown while "@" is also typed; make "@" a fixed prefix adornment (Forms). |
| P2 | Desktop: a 280 px sheet with 11 px text (`g03-join-desk`). |

**Home (`g04`, `g05`)**

What works: two big tappable tiles and a party name.

| P | Issue |
|---|---|
| P1 | 60% of the phone screen is empty. No live counter ("29 Biere"), no "your photos", no sense that a party is happening. The beer goal, the product's hook, isn't on the home screen. |
| P1 | The identity chip is 35 px tall (below 44, Touch & Interaction). "Hüpfendes Alpaka · Insta?" is cryptic; "Insta?" is a prompt dressed as data. |
| P1 | "Such dir was aus:" is filler. The h1 has a decorative 🎉 that isn't aria-hidden. |
| P2 | Tile tint gradients cycle by `nth-child`, so the colour means nothing. Taglines use emoji and "–". |
| P2 | Desktop: a small column, top-left heavy. Landscape: fine. |

**Chip editor sheet (`g06`)**

| P | Issue |
|---|---|
| P2 | Fine functionally. The title "Dein Instagram" doesn't match the field label "Instagram-Name (freiwillig)". It shows the pseudonym ("Du bist hier „Verrückte Ente #1“") as prose. The pseudonym is the guest's identity at the party and deserves a visual (a "guest pass"). |
| P2 | No "remove handle" affordance other than clearing the field. |

**Beer Cam, camera (`b01`, `b02`, `b06`)**

What works:
- the bottle and cup outlines are good, legible signature content;
- landscape splits nicely;
- the counter is always visible;
- the in-app browser hint exists.

| P | Issue |
|---|---|
| P0-ish | The preview is not the hero. On 390×844 the frame is about 300×400 inset with rounded corners, and about 120 px of dead band sits between the hint and the controls (`b01-camera-bottle-phone`). The 3:4 frame (preview equals saved photo) can be edge to edge: 390×520. |
| P1 | Vessel labels "Flasche"/"Becher" are 10.6 px (`beer.css:343`). The selected state is a gradient blob. |
| P1 | The shutter has a 🍺 emoji inside. The camera-switch button is low-contrast and small-looking (it's 52 px, but reads as dim). |
| P1 | Loading: the "Kamera startet…" text is crossed by the bottle outline stroke (`b00`). |
| P1 | The counter chip "🍺 25 / 1 Mio." needs a non-breaking space ("1&nbsp;Mio."). "/ 1.000.000" in landscape and "/ 1 Mio." in portrait is inconsistent. |
| P2 | The hint uses an emoji pointer (👆). Desktop: a tiny 3:4 frame with tiny controls and no visible keyboard hint (Space works). |

**Beer Cam, uploading, error, success (`b03`, `b04`, `b05`)**

| P | Issue |
|---|---|
| P0 | After a failed upload and a successful retry, the error toast "Keine Verbindung. Nochmal versuchen?" is still showing on top of the success screen (`b05-success-phone`, `b05b-success-settled-small`). |
| P1 | The error is shown twice, as a top toast and as an inline card with the same text (`b04`). The toast also covers the back button, chip and counter. |
| P1 | "Wird geloggt… 0 %" is jargon; the beer is being *counted*. |
| P1 | The success screen states the number three times: polaroid caption "Bier #26 · Flasche", h1 "Bier #26 geloggt 🍺", counter chip "🍺 26 / 1.000.000", plus "Noch 999.974 bis zur Million – weiter so!". Pick one hero number and one progress line. |
| P2 | Small phone: the top of the polaroid is cut off. Desktop: everything is tiny. |
| P2 | Random cheers ("Hopfen und Malz, Gott erhalt’s!") are good tone and should stay. |

**Beer Cam, paused, stopped, banned (`s02`–`s07`, `s11`)**

| P | Issue |
|---|---|
| P0 | With uploads stopped, or this guest paused, the shutter stays live. The guest shoots, then gets "Uploads sind gerade kurz gestoppt…" with only "Nochmal" or "Verwerfen" (stopped) or "Zur Startseite" or "Verwerfen" (paused), and the beer photo is lost (`s04`, `s07`). The Fotobox at least offers "Speichern". The redesign must either queue the shot locally (as the Fotobox outbox does) or block the shutter up front with the reason. |
| P1 | The pause chip "⏸ Uploads sind gerade pausiert" is an extra floating pill pushed under the top bar. It needs a permanent status slot. |
| P2 | Banned: a plain full-screen notice ("Gesperrt") with one button. Acceptable. The tone is fine. |

**Fotobox, camera and filters (`f01`, `f02`)**

What works:
- the filters are fun and good;
- the party frame with "Lenas Geburtstag 13.10.2026" is the best-looking thing in the app;
- landscape works.

| P | Issue |
|---|---|
| P1 | The filter name pill appears at `top:42%`, right over the face, the thing the guest is checking (`booth.css:136`). Move it to the frame's bottom-left, small, or into the carousel only. |
| P1 | Filter labels are 11.5 px and hyphenated over two lines ("Schwarz-/Weiß", "Party-/Rahmen"), `booth.css:254`. All ten labels show at once, so the strip is busy. Show the name only under the selected swatch. |
| P1 | The header has the "←" glyph, a "📸 Fotobox" title, and a chip that truncates the pseudonym ("Hüpfendes Alpaka ·…"). Three different back-button treatments exist across the app. |
| P1 | The countdown toggle "⏱️ 3s" uses a gradient fill when on. Its toast "Countdown an: 3 … 2 … 1 ⏱️" covers the top bar (`f03`). The switch-camera button is a 🔄 emoji. |
| P2 | The preview is again a rounded inset card with a glow. Desktop: a small frame plus a 10-item strip at 9 px. |

**Fotobox, countdown, result, outbox (`f04`–`f09`)**

| P | Issue |
|---|---|
| P1 | The result has two buttons labelled "Nochmal" with different meanings: "↻ Nochmal hochladen" (retry) and "📸 Nochmal" (new photo), `f07`. Use "Erneut senden" and "Neues Foto". |
| P1 | The outbox chip "⚠️ 1 nicht hochgeladen · nochmal" is cryptic (`booth.js:593`, `f08`). Use "1 Foto wartet aufs Hochladen · Jetzt senden" in the status slot. |
| P1 | The upload status is small green text ("Hochgeladen ✓ · Foto #15") and the error is small red text. Status should live on the print itself (frame edge), not as a floating line. |
| P2 | The countdown digit is a big gradient-outlined numeral (`f04-countdown-desk`). It's good, but has no ring or progress, and no way to cancel is shown. |
| P2 | The leave dialog (`f09`) has good copy and the right stakes. Keep it. |

**Notices: loader, fatal, camera denied, offline (`b07`–`b10`, `f10`)**

| P | Issue |
|---|---|
| P1 | They are inconsistent:<br>- titles "Kamera geht nicht" vs "Die Kamera geht nicht" vs "Ups";<br>- buttons "Neu laden" vs "Nochmal versuchen";<br>- links "Zur Startseite" vs "Zur Übersicht";<br>- the loader-failed button is not full width while the others are. |
| P1 | "Ups" says nothing. Write titles that name the problem: "Keine Verbindung zum Server". |
| P2 | Offline reload falls back to the browser's own error page. A tiny app-shell service worker would let the outbox and offline notice work. This is structural and optional. |

### 3.2 Admin

**Login (`a01`)**

| P | Issue |
|---|---|
| P2 | Fine. `autofocus` on the password field (`login.html:23`) pops the keyboard on phones; the guideline says autofocus on desktop only. 🔐 emoji plus gradient "Admin". Desktop: a small card. |

**Live (`a02`, `a10`–`a13`)**

What works:
- hide-only works, as the rule requires;
- the connection state is shown;
- the new-photos pill exists;
- hidden cards show a clear "VERSTECKT" band;
- the empty state is friendly.

| P | Issue |
|---|---|
| P1 | Density: one card per row with a 124 px thumb, about 3.5 photos per phone screen (`a10-live-phone`). Watching a party needs a 2-column grid of thumbnails (3 in landscape) with a 44 px hide toggle overlay. |
| P1 | Red is the dominant colour of the screen: every card has a red "🙈 Runternehmen" (`admin.css:178`). The routine action should be quiet (an icon toggle), and the hidden *state* should be the loud thing. |
| P1 | Hide feedback is a toast at the top covering the header; it has no "Rückgängig" (Navigation & State: undo window). The card button flips to a green "Wieder zeigen", so green means "currently hidden": inverted semantics. |
| P1 | The header has three rows: title, connection and nav; stat pills; uploads chip. Landscape: only one row of photos fits (`a10-live-land`). Small phone: the button label wraps ("🙈/Runternehmen"). |
| P2 | "✓ Sichtbar" badge on every card is noise; only show the exceptional state. "Echtzeit" vs "Live" naming. |
| P2 | Lightbox (`a12`): toast covers prev/next. Meta shows raw ids "Filter: neon · Kamera: user" and "Gefäß: cup · Kamera: environment" (`admin.js:111`). Not deep-linkable. |
| P2 | The new pill is a gradient, overlapping the card titles (`a13`). |

**Upload controls sheet (`a14`, `a40`–`a44`)**

What works: one sheet, two clear switches, the pause-end decision dialog (restore or keep), and the "1 Gast pausiert, ansehen" link.

| P | Issue |
|---|---|
| P1 | Toasts stack over the sheet title and close button; three toasts in `a42`. The live header in pause state is also covered (`a43`). |
| P1 | State is said twice: status row "⏸ Neue Gäste pausiert seit 03:48 · 0 betroffen" plus the switch subtitle "Neue Gäste können seit 03:48 nichts hochladen · 0 betroffen". |
| P1 | A 4-line explanation inside each switch row. Use one line plus "?" for details. |
| P2 | The emergency control, stop everything, should look like an emergency control: a distinct full-width row at the top, red when on. Today it's a generic iOS switch. |

**Manage, Fotos (`a20-manage-fotos-*`, `a21`–`a24`)**

What works:
- filters;
- select all;
- the shift-click range hint on desktop;
- the bulk bar;
- confirm dialogs with good, specific copy ("3 Fotos endgültig löschen?" plus "Zum Verstecken reicht „Runternehmen“");
- the lightbox with a "Versteckt: Gäste sehen es nicht" banner.

| P | Issue |
|---|---|
| P1 | Tiles carry two full buttons each (Runternehmen, Löschen); a tile is about 380 px tall on a phone, so 2 tiles fit per screen. On desktop, 6 columns with only 1.3 rows visible above the fold. |
| P1 | Phone landscape: 0 photos visible (`a20-manage-fotos-land`). The header and filters aren't collapsible. |
| P1 | Bulk bar on phone wraps to 3 rows and covers tiles (`a21-…-phone`). |
| P1 | The tab strip clips mid-word ("Instagı", "ste 13") and hides its scrollbar with no fade or affordance (`admin.css:245-254`). Emoji in every tab label, not aria-hidden (`manage.html:28-32`). |
| P2 | Uppercase tracked field labels "AKTIVITÄT / GAST / STATUS" (`admin.css:284`). The "Gast" select stretches to 320 px. "Download" is English in the lightbox. |

**Manage, Gäste (`a20-manage-gaeste-*`)**

| P | Issue |
|---|---|
| P1 | On desktop this is a list of full-width rows with the data in middle-dot strings ("@neu.hier · zuletzt gerade eben · Android 14 · Pixel 7 · Chrome 140"). It is a table: Nr., Name, Instagram, Fotos, Status, Zuletzt, Gerät, sortable. |
| P1 | Phone: the 4-option segmented control wraps to 2 lines ("Nicht/gesperrt"). The search placeholder is truncated. |
| P2 | "AUTO-GESPERRT" in caps with a dashed orange border. Status badges at 10.4 px. |

**Manage, Instagram (`a20-manage-instagram-*`)**

This is the core after-party workflow.

What works: grouped by handle, with photo strip, "Kopieren", "Profil ↗" and "Alle 8 Handles kopieren".

| P | Issue |
|---|---|
| P1 | No bulk download per handle. Photos are downloaded one by one from the lightbox. There is no "posted/tagged" progress marker. A third button style (purple→cyan gradient "Kopieren", `vb-btn--cool`) appears only here. |
| P2 | A 3-line explanation paragraph. Count line "8 Handles · 8 Gäste". |

**Manage, Sperren (`a20-manage-sperren-*`)**

| P | Issue |
|---|---|
| P1 | A 6-line paragraph header plus a 5-line warning box before any data. Big green "✅ Entsperren" buttons: green for unbanning is the same colour as "Wieder zeigen". |
| P2 | Fingerprint hashes in monospace ("e6c336695afa…"). Content is good; the structure should be two tables, guest bans and device bans. |

**Manage, Protokoll (`a20-manage-protokoll-*`)**

| P | Issue |
|---|---|
| P1 | Phone: the table is clipped horizontally (ZIEL "Foto V5aCr…", "127.0") with no scroll affordance. Raw ids ("Foto V5aCnChc…", "admin:edb5eaeb", "anonymous"). Use readable targets ("Fotobox 18", "Cooler Igel #7") and readable actors ("Admin (Sitzung 3)", "Unbekannt"). |
| P2 | Uppercase `th` (`admin.css:560`). Timestamps lack tabular-nums. |

**User page (`a30`–`a32`)**

What works:
- everything is present: profile, upload pause, ban with reason and fingerprint option, photos, fingerprints, device;
- the confirm dialog is a good second step ("Singende Giraffe #5 sperren?" with "Gast + Fingerprint sperren").

| P | Issue |
|---|---|
| P0 | A banned or auto-banned guest shows "✓ Darf hochladen" in the Hochladen panel (`a30-user-banned-desk`, `a30-user-autobanned-phone`). That contradicts the ban. |
| P1 | On a phone it's about 5 screens long. The destructive ban form (reason, fingerprint checkbox, 7-line warning, red button) comes *before* the photos. Move the form into the "Sperren…" dialog and keep one button on the page. |
| P1 | Status is spread across badges: "✓ Aktiv", "✓ Darf hochladen", "GESPERRT", "AUTO-GESPERRT". Use one status line. |
| P2 | The user agent dumped in monospace; "Grafik –", "Sprache –", "Leistung –" rows show dashes for empty values. Collapse them into "Technische Details". |
| P2 | Ban-hidden photos offer "Wieder zeigen" while the guest is still banned; this needs a clarifying hint. |

### 3.3 Guideline findings (file:line)

```text
## virtubooth/static/core/vb.css
vb.css:25 - system-ui only: no brand face; renders as Roboto/SF/Noto depending on device
vb.css:46 - overscroll-behavior:none on body for all pointers → kills pull-to-refresh on phones (rule: only in @media (pointer:fine)); keep it on camera stages only
vb.css:155-170 - .vb-chip used as button is 35px tall → <44px target
vb.css:188 - .vb-input:focus {outline:none} → :focus-visible ring (border tint alone is weak)
vb.css:342-353 - toast host fixed top, unlimited stack → covers headers, sheet close, lightbox nav (Focus States: overlays must not cover focused element)
vb.css:370-397 - .vb-pausechip fixed top:68px → overlaps prints/frames; needs a layout slot
vb.css:20-21 - one gradient reused as fill for buttons, shutter, text, progress, tabs → no hierarchy
## virtubooth/static/core/vb.js
vb.js:371,458 - placeholder "@deinname" + typed "@" → "@" prefix adornment; example placeholder ends with "…"
vb.js:443 - chip text "Name · Insta?" cryptic
vb.js:516 - straight apostrophe "geht's" → "geht’s"
vb.js:674-682 - toast(): no max/replace, no action slot (undo/retry), no dismiss; same 2.8s for long errors
## virtubooth/identity.py
identity.py:108-117 - 3 paragraphs before CTA; "Fotobox" named for whole product; "los geht's! 🍻" straight quote + emoji in label
## virtubooth/static/core/home.html
home.html:20-21 - decorative 🎉 in h1 not aria-hidden; filler "Such dir was aus:"
## virtubooth/extensions/beer/static
index.html:43 - "Wird geloggt…" jargon
beer.css:145-155 - preview as rounded glowing card instead of camera stage
beer.css:343 - vessel label 0.66rem (10.6px)
## virtubooth/extensions/booth/static
index.html:7 - theme-color #000000 vs #14021f on every other page
index.html:18 - back "←" text glyph (Beer Cam: SVG chevron); aria-label "Zurück zur Übersicht" vs "…Startseite"
index.html:34 - "Kamera startet …" (space before …) vs Beer "Kamera startet…"
index.html:42-51 - emoji ⏱️ 🔄 as control icons
booth.css:136-146 - filter-name pill at top:42% covers the face
booth.css:254 - filter names 0.72rem (11.5px), 2-line hyphenation
booth.js:525 - "Wird hochgeladen … %" space before …
booth.js:593 - outbox label "⚠️ n nicht hochgeladen · nochmal" cryptic
booth.js:283-287 - "Die Kamera geht nicht" / "Nochmal versuchen" / "Zur Übersicht" ≠ beer.js:183 "Kamera geht nicht" / "Neu laden" / "Zur Startseite"
booth (camera screen) - no h1 on the page (result uses h2)
## virtubooth/admin/static
login.html:23 - autofocus on phone pops keyboard (rule: desktop only)
live.html:19, manage.html:19,28-32 - emoji in headings/tabs not aria-hidden → SR reads "Kamera mit Blitz Live"
live.html:23 - logout 🚪 emoji renders as a brown block on Android/Linux
assets/admin.css:245-254 - tab scroller hides scrollbar, no overflow affordance → labels cut mid-word
assets/admin.css:284,560 - uppercase tracked labels/th (also a frontend-design "template tell")
assets/admin.css:298-299 - :focus outline none on select/search
assets/admin.css:16-25 (+stats, uploads slot, tabs) - sticky header 190–230px on phones; fills landscape viewport
assets/admin.css:178-180 - red primary button on every card (live/manage) → visual alarm everywhere
assets/admin.js:111,884 - raw meta ids in lightbox ("neon", "user", "cup", "environment"); "⬇ Download" English
assets/manage.js (Protokoll) - raw ids "Foto V5aCnChc…", "admin:edb5eaeb", "anonymous"
assets/user.js:89-131 - ban form inline above content; contradicting "Darf hochladen" for banned users
assets/uploadcontrols.js:222-235 - long paragraphs inside switch rows; status said twice
assets/live.js:33, admin.js:860, manage.js:503 - <img> without width/height (mitigated by aspect-ratio boxes)
## cross-cutting
- tabular-nums only in beer.css:77,446 → admin counts, stats, table times/numbers lack it
- no translate="no" on pseudonyms, @handles, "Beer Cam"/"Fotobox" (Chrome auto-translate garbles them)
- no skip link on admin desktop pages (header + 5 tabs + chip before content)
- lightbox state not in URL (Navigation & State); manage tab/filter state IS (good)
- hide has no undo window in its toast (reversible only via the card button)
✓ pass: reduced motion (global kill switch vb.css:497 + confetti check vb.js:749), Intl.* formatting,
  color-scheme:dark, touch-action:manipulation on buttons, confirm before delete/ban, aria-live toasts,
  dialog focus trap/Escape, form labels, inputmode/autocapitalize/spellcheck on handle fields, contrast
  (muted 10.2:1, buttons 5–9:1, red text 5.3–5.8:1; only gradient-headline pink on the purple glow drops to 4.0:1)
```

Note: the guideline "Title Case for headings/buttons (Chicago)" is English-only. German UI must use sentence case, which the app already does; keep it.

### 3.4 Copy: proposed glossary (one name per concept, same word in button, toast and badge)

| Concept | Today (variants seen) | Proposed |
|---|---|---|
| Hide a photo (live and manage) | Runternehmen, runtergenommen, Versteckt, versteckt, Wieder zeigen, Zeigen, Sichtbar | **Ausblenden** → toast "Ausgeblendet · Rückgängig"; badge **Ausgeblendet**; reverse **Einblenden**; default state needs no badge |
| Delete | Löschen, endgültig löschen | **Löschen…** (dialog title "… endgültig löschen?", button "Endgültig löschen"). Keep. |
| Guest upload transport | Uploads, Hochladen, geloggt, hochgeladen | **Hochladen / Wird hochgeladen… / Hochgeladen**. Beer domain verb **gezählt** ("Bier Nr. 30 gezählt"). |
| Retry upload | Nochmal, Nochmal hochladen, ↻ Nochmal hochladen | **Erneut senden** |
| Take another | Nochmal, Noch eins! 🍺 | Beer **Noch ein Bier**; Fotobox **Neues Foto** |
| Reload | Neu laden, Nochmal versuchen | **Seite neu laden** |
| Home | Startseite, Übersicht | **Start** |
| Per-guest pause | Uploads pausiert, Hochladen pausiert | **Hochladen pausiert** |
| Stop all | Alle Uploads stoppen, Uploads kurz gestoppt | Admin **Hochladen für alle stoppen**; guest **Hochladen ist kurz angehalten** |
| Ban | Gesperrt, GESPERRT, AUTO-GESPERRT | **Gesperrt**, **Automatisch gesperrt** (sentence case) |
| Instagram | Instagram-Name, Handle, Insta? | **Instagram-Name** (guest), **Instagram** (admin column); no "Handle" |
| Fingerprint | Fingerprint | UI copy: **Gerätemerkmal** ("Gerätemerkmal auch sperren"). Avoid the word in class and file names (content blockers). |
| Live connection | Echtzeit, Verbinde…, Live | Dot plus **verbunden / verbindet… / nur Abfrage** |
| Save (guest) / download (admin) | Speichern, Download | **Speichern** (guest), **Herunterladen** (admin) |

Typography:
- "…" with no space before it: "Lädt…", "Wird hochgeladen… 40 %".
- German quotes „…“ and apostrophe ’.
- Non-breaking space in "1&nbsp;Mio.", "3&nbsp;s", "40&nbsp;%".
- Tabular figures for every number column and counter.

Tone: keep the warm du-form and the beer cheers. Errors say what happened and what to do, without "Ups".

---

## 4. User journeys

### A. Guest at a party: first visit → join → beer → booth → return later

| Step | Today (evidence) | Friction | Must be effortless |
|---|---|---|---|
| Scan the QR in the camera app | Lands on home or an activity (`g03`, `g07`). In-app browser: hint only on the Beer Cam. | The gate doesn't help with in-app browsers or an expired token. | A context-aware gate: "Öffne den Link in Safari/Chrome" when the user agent is an in-app browser. |
| Join | 110-word sheet, then handle, then button | Reading load; doesn't say which activity is next | One glance: 2 lines, optional "@" field, one big button "Los geht's". Details behind "Mehr dazu". Then land **directly in the activity whose code they scanned** (already true for the URL). |
| Beer | Framed card preview, tiny vessel toggle, success screen with 3 numbers | Small targets; double error messages; stale error on success; beer lost if paused or stopped | From scan to shutter in ≤2 taps. Huge preview, big shutter. Success is one number plus a "Noch ein Bier" button. Never lose a shot: queue it like the Fotobox outbox, and tell the guest before they shoot when uploads are paused. |
| Switch to Fotobox | Back to home, then tile | Two taps, page reload, camera restart | An activity switcher in the camera top bar ("Beer Cam ▾"); tapping the title opens a sheet. The camera still restarts, but the guest doesn't hunt. |
| Fotobox | Filter name over face; tiny labels; two "Nochmal" | Hard to judge filters; ambiguous result actions | Carousel with named, selected swatch; preview unobstructed; result has "Speichern" (primary) and "Neues Foto". Upload status shown on the print. |
| Return later (cookie is 30 days) | Same home; toast "Du bist schon dabei als …" | Nothing new to see; no "my photos" | Home shows "Deine Bilder" (own photos only; **needs a small API**) and the live beer count. The guest pass shows who you are at a glance. |

### B. Host on a phone during the party (watching, hiding, banning, pausing)

| Step | Today | Friction | Must be effortless |
|---|---|---|---|
| Watch | Live list, 3.5 photos per screen, header 190 px | Scrolling a lot; landscape useless | A 2-column (landscape 3–4) thumbnail grid. Compact one-row header. "n neue Fotos" pill that scrolls to top. |
| Hide | Big red button per card; toast at top, no undo | Visually alarming; the toast covers the header | One tap on a 44 px eye toggle in the tile corner. Pencil-X mark on the tile. Bottom toast "Ausgeblendet · Rückgängig" (5 s). |
| Inspect | Lightbox with toast over nav; raw meta | — | A viewer with swipe, arrows and buttons; readable meta; "Gast öffnen" link. |
| Ban a troublemaker | Live → name link → user page → scroll past profile and pause → fill form → confirm (5 screens on phone) | Long page; destructive form inline | Keep ban off the live screen (rule). From any photo: "Gast öffnen" → a user page whose first screen holds the status and two buttons ("Hochladen pausieren", "Sperren…"). Reason, fingerprint option and warning go in the "Sperren…" sheet. Back returns to live at the same scroll position. |
| Emergency stop / pause new guests | Uploads chip → sheet with long text; toasts pile over it | Hard to read under stress | The upload status pill always sits in the live header. One tap opens the sheet; "Hochladen für alle stoppen" is the first, biggest row. State shows in one line; explanations sit behind "?". No toast while the sheet is open (the switch state *is* the feedback). |
| Pause a single guest | User page only | Fine | The same user-page fast path. The paused count in the sheet links to the filtered guest list (exists). |

### C. Host on a laptop after the party (management, Instagram tagging, export)

| Step | Today | Friction | Must be effortless |
|---|---|---|---|
| Review all photos | 6-column grid of bulky tiles, 1.3 rows above the fold | Low density; per-tile buttons | Dense contact sheet (7–8 columns of 150 px), selection via checkbox overlay or click plus shift-click, inspector panel on the right, sticky selection bar. Keyboard: arrows, X (hide), Delete (dialog), Space (select). |
| Instagram tagging | Per handle: copy handle, open profile, open each photo, download one by one | Many clicks; no progress | Handle board: per handle "Fotos herunterladen (ZIP)", "Instagram-Name kopieren" and a "Erledigt" checkbox to track posting (new optional state, could be local-only at first). Sort by number of photos. |
| Export / timelapse / QR | CLI only (`docker compose exec …`) | Needs a terminal | An **Export** section in manage: download the archive (photos, CSV, optional DB), "Zeitraffer erstellen" with FPS and crossfade options and a progress bar, "QR-Bogen öffnen". Backend jobs needed (structural); the CLI tools stay. |
| Guests and bans | Rows with middle-dot strings; paragraphs before data | Scanning is hard | Sortable tables. Ban details in an expandable row. Readable audit log. |
| Cleanup | README instructions | — | An "Aufräumen" checklist page linking to the docs (copy only). |

---

## 5. Information architecture proposal

### Guest

- **URLs stay**: `/` start, `/x/<ext>/` activities. Printed QR codes point at them, and the extension contract depends on them.
- **Start screen** (`/`):
  - party name;
  - one card per activity, each showing its own live line (Beer Cam: counter and goal; Fotobox: filter count);
  - "Deine Bilder" strip (needs API);
  - a "Was passiert mit meinen Fotos?" link that reopens the join text read-only.
- **Persistent identity, "guest pass"**: one 44 px pill at top-left on every guest screen with the short pseudonym plus @handle (or "Instagram hinzufügen"). Tap opens the "Du" sheet: pseudonym, Instagram name field, own photo count, and a help section (camera permission, in-app browser).
- **One status slot** (never floating): the guest pass changes colour and shows a short label for exceptional states. Tap explains.
  - "Hochladen pausiert";
  - "Hochladen kurz angehalten";
  - "Offline";
  - "1 Foto wartet".
- **Hints**: one line between preview and controls on camera screens. Toasts sit just above the control row, max one at a time (newer replaces older), never over the top bar.
- **Between activities**: the camera top bar title is a menu ("Beer Cam ▾" opens a sheet listing activities and Start).

### Admin

```
/admin/login
/admin/live            phone-first, dark; HIDE/UNHIDE ONLY + upload controls sheet
/admin/manage          desktop-first, light; sections via ?tab=
    fotos | gaeste | instagram | sperren | protokoll | export (new)
/admin/user?id=        guest detail (manage area): pause, ban, photos, tech details
```

- **The live/manage separation stays**: live can hide and unhide only; delete, bans, device bans and auto-ban release stay in manage and the user page. The live viewer offers "Gast öffnen" (navigates into manage), never a ban button.
- **Upload controls** live in one sheet, reachable from the status pill in both headers (live and manage) and from the phone bottom bar. Per-guest pause stays on the user page; the sheet links to "n Gäste pausiert".
- **Phone admin navigation**: a bottom bar with Live, Hochladen (opens the sheet) and Verwaltung.
- **Desktop manage navigation**: a left sidebar with sections and counts, the status pill, "Live öffnen" and "Abmelden".
- **User page**:
  1. header with name, Instagram, one status line and two actions ("Hochladen pausieren" toggle, "Sperren…" or "Entsperren…");
  2. photos grid;
  3. collapsed "Technische Details" (device, device marks, IP, user agent).
- **Deep links**: lightbox `?photo=<id>`, guest filters, tab (exists).

### Wireframes (recommended direction "Kontaktbogen")

**Phone guest start (390×844, dark Rotlicht surface)**
```
┌──────────────────────────────────────────┐
│ ┌───────────────────────────┐   ┌─────┐  │ guest pass 44h (status slot) · help
│ │ ▣ Verrückte Ente  @lena.k │   │  ?  │  │
│ └───────────────────────────┘   └─────┘  │
│                                          │
│  Lenas                                   │ display 44/46, left-aligned
│  Geburtstag                              │
│                                          │
│ ┌──────────────────────────────────────┐ │ whole card is the link
│ │ Beer Cam                             │ │
│ │ Fotografier dein Getränk im Umriss.  │ │
│ │ ▮ ▮ ▮ ▮ ▮ ▮ ▮ ▮ ▮ ▮ ▮ ▮ ▮ ▮ ▮ ▮ ▮ ▮ │ │ frame edge (sprockets)
│ │ 0 030   von 1 000 000                │ │ Doto counter, 28px
│ └──────────────────────────────────────┘ │
│ ┌──────────────────────────────────────┐ │
│ │ Fotobox                              │ │
│ │ Selfie mit Filter und Countdown.     │ │
│ │ [▧][▧][▧][▧][▧]  10 Filter           │ │ prerendered filter swatches
│ └──────────────────────────────────────┘ │
│                                          │
│  Deine Bilder  4                         │ own photos only (needs API)
│  ┌───┐ ┌───┐ ┌───┐ ┌───┐                 │
│  └───┘ └───┘ └───┘ └───┘                 │
│                                          │
│  Was passiert mit meinen Fotos?          │ reopens join text
└──────────────────────────────────────────┘
```

**Beer Cam (390×844; ≤700 px tall: top bar and frame edge overlay the preview)**
```
┌──────────────────────────────────────────┐ #000 stage, safe-area top
│ ‹   Beer Cam ▾               ▣ Ente #1   │ 56h, targets 44
├──────────────────────────────────────────┤
│                 ╭──╮                     │
│                 │  │                     │ 3:4 preview 390×520,
│                ╭╯  ╰╮                    │ edge to edge, square corners
│                │    │                    │ outline 3px paper-white
│                │    │                    │ + 1px black halo
│                │    │                    │ (optional: sensor area outside
│                ╰────╯                    │  the crop dimmed to 30%)
├─▮──▮──▮──▮──▮──▮──▮──▮──▮──▮──▮──▮──▮──▮─┤ frame edge = upload progress track
│  Nächstes Bier  0 031         Ziel 1 Mio.│ Doto 22px
├──────────────────────────────────────────┤
│  Halte die Flasche in den Umriss.        │ one line, 17px
│                                          │
│ ┌────────┬────────┐  ╭──────╮   ┌─────┐  │ segmented 48h · shutter 80 · 48
│ │Flasche │ Becher │  │  ◉   │   │  ⟲  │  │
│ └────────┴────────┘  ╰──────╯   └─────┘  │
│        [ toast slot: max 1, here ]       │
└──────────────────────────────────────────┘
```

**Fotobox (390×844)**
```
┌──────────────────────────────────────────┐
│ ‹   Fotobox ▾                ▣ Ente #1   │
├──────────────────────────────────────────┤
│                                          │
│          3:4 live preview, mirrored      │ 390×520, nothing over the face
│                                          │
│                  ┌─────┐                 │ countdown: Doto 160px numeral
│                  │  3  │                 │ inside a safelight ring that
│                  └─────┘                 │ drains per second; tap = cancel
│                                          │
│ Neon                                     │ filter name bottom-left, 1.2 s
├─▮──▮──▮──▮──▮──▮──▮──▮──▮──▮──▮──▮──▮──▮─┤
│ (▧) (▧) [▧] (▧) (▧) (▧)  ›               │ swatches 56px, scroll-snap
│          Neon                            │ name under selected only
│  ┌─────┐          ╭──────╮        ┌─────┐│
│  │ 3 s │          │  ◉   │        │  ⟲  ││ toggle shows "3 s" / "aus"
│  └─────┘          ╰──────╯        └─────┘│
└──────────────────────────────────────────┘
Result: the print develops (black → image, 700 ms) on the stage; the frame edge under it
reads "Foto 0018 · hochgeladen" or "wartet" or "Erneut senden"; buttons [Speichern] [Neues Foto].
```

**Admin live on a phone (390×844, dark)**
```
┌──────────────────────────────────────────┐
│ Live  ● verbunden         ┌────────────┐ │ one row, 56h
│ 49 Fotos, 6 ausgeblendet  │ Hochladen  │ │ status pill: neutral "an",
│                           │ an       ▾ │ │ amber "neue pausiert", red "gestoppt"
├───────────────────────────┴────────────┴─┤
│ ┌─────────────────┐ ┌─────────────────┐  │ 2 cols (landscape 4), 3:4 thumbs
│ │                 │ │╲               ╱│  │ hidden: grease-pencil X, 40% dim
│ │                 │ │   ╲         ╱   │  │
│ │                 │ │      ╲   ╱      │  │
│ │            [◎]  │ │            [⊘]  │  │ 44px eye toggle, bottom-right
│ ├─────────────────┤ ├─────────────────┤  │
│ │ Bier 0032       │ │ Fotobox 0018    │  │ caption = frame edge
│ │ Mutiger Krake   │ │ Hüpfendes Alpaka│  │
│ └─────────────────┘ └─────────────────┘  │
│ ┌─────────────────┐ ┌─────────────────┐  │
│ │       …         │ │       …         │  │
│ ┌──────────────────────────────────────┐ │
│ │ Fotobox 0018 ausgeblendet  Rückgängig│ │ toast above the bottom bar
│ └──────────────────────────────────────┘ │
├──────────────────────────────────────────┤
│    Live          Hochladen    Verwaltung │ 64h + safe area
└──────────────────────────────────────────┘
```

**Admin manage on desktop (1440×900, light "Leuchttisch")**
```
┌──────────────────┬─────────────────────────────────────────────────────────────────────┐
│ Lenas Geburtstag │ Fotos   49, davon 6 ausgeblendet                                    │
│ ● verbunden      │ [Aktivität: Alle ▾] [Gast: Alle ▾] [Alle|Sichtbar|Ausgeblendet] [⌕] │
│                  ├──────────────────────────────────────────────┬──────────────────────┤
│ Fotos         49 │ ┌───┐ ┌───┐ ┌───┐ ┌───┐ ┌───┐ ┌───┐ ┌───┐   │ ┌──────────────────┐ │
│ Gäste         13 │ │   │ │   │ │╲ ╱│ │   │ │ ◯ │ │   │ │   │   │ │                  │ │
│ Instagram      8 │ │   │ │   │ │ ╳ │ │   │ │   │ │   │ │   │   │ │   3:4 preview    │ │
│ Sperren        3 │ └───┘ └───┘ └───┘ └───┘ └───┘ └───┘ └───┘   │ │                  │ │
│ Protokoll        │  0032  0031  0018  0017  0016  0015  0030    │ └──────────────────┘ │
│ Export           │ ┌───┐ ┌───┐ ┌───┐ ┌───┐ ┌───┐ ┌───┐ ┌───┐   │ Fotobox 0018         │
│                  │ │   │ │   │ │   │ │   │ │   │ │   │ │   │   │ Hüpfendes Alpaka #2  │
│──────────────────│ └───┘ └───┘ └───┘ └───┘ └───┘ └───┘ └───┘   │ ohne Instagram       │
│ Hochladen: an  ▾ │  7 cols × 150px, caption frame no. + guest   │ vor 3 Min., Neon     │
│ Live öffnen      │  ◯ = selected (grease circle)                │ [Einblenden]         │
│ Abmelden         │                                              │ [Herunterladen]      │
│                  │                                              │ [Löschen…]           │
│                  ├──────────────────────────────────────────────┴──────────────────────┤
│                  │ 3 ausgewählt   [Ausblenden] [Einblenden] [Löschen…]  Auswahl aufheben │
└──────────────────┴─────────────────────────────────────────────────────────────────────┘
Gäste tab = table: Nr. | Name | Instagram | Fotos | Status | Zuletzt | Gerät  (sortable, row → user page)
```

---

## 6. Design directions

All three keep the hard rules:
- the camera stage is pure black and full-bleed edge to edge, with the 3:4 frame unrounded and kept exactly (preview equals saved photo);
- the admin is calm and dense;
- one brand, defined by shared type and one signature component;
- fonts are OFL and self-hosted via `@fontsource` (strict CSP, no CDNs), preloaded with `font-display: swap`;
- AA contrast, 44 px+ targets, reduced motion, visible focus.

No class or file names contain consent, cookie, banner, modal, fingerprint, ads, ad-, or track. Use instead:
- `JoinSheet`, not ConsentModal;
- `StatusStrip`, not banner;
- `DeviceMarks` for fingerprints;
- `ActivityLog` or `Protokoll`, not tracking.

Also avoid the social-widget names that the Fanboy Social list hides, such as `instagram-feed`, `share-button` and `social-*`; call it `HandleBoard`. Re-run the existing blocker test (scratchpad/blockers) on the new bundle.

### A. "Kontaktbogen": darkroom and contact sheet (recommended)

**Idea.** Every photo is a frame on the party's film roll. Guests expose frames; the Beer Cam frames literally *become a film* (the timelapse); the host reviews a contact sheet on a light table and marks frames with a grease pencil. Existing frame numbers (`#seq` per activity) map one to one.

**Palette.**

| Name | Hex | Role | Contrast |
|---|---|---|---|
| Kamera-Schwarz | `#000000` | camera stage only | Safelight on it 10.8:1 |
| Rotlicht | `#2B0F0C` | dark surface (guest pages, live, sheets); clearly red-brown, not a neutral near-black | Leuchttisch text on it 16.5:1; muted `#C9B8B0` 9.3:1 |
| Safelight | `#FFA630` | primary action, shutter ring, counters | 9.1:1 on Rotlicht; Rotlicht text on it 9.1:1 |
| Leuchttisch | `#F4F6F8` | cool light-table surface for manage (not warm cream) | — |
| Negativ-Blau | `#16203A` | ink: text on light surfaces | 14.9:1 on Leuchttisch; muted `#5A6272` 5.7:1 |
| Fettstift | `#C62A22` | grease pencil: hidden marks, destructive | 5.2:1 on Leuchttisch; white on it 5.6:1; on dark use `#FF7A66` (7.0:1 on Rotlicht) |

**Type.**
- **Bricolage Grotesque** (variable opsz 12–96, wdth 75–100; `@fontsource-variable/bricolage-grotesque`) for display and UI. Large optical sizes are characterful for the party name; small sizes are plain for tables.
- **Doto** (dot-matrix, OFL, Google Fonts 2024; verify the `@fontsource` package or self-host from google/fonts) only for *large* numerals: beer counter, countdown, frame number on the result print. It reads like film edge print and LED counters.
- Frame numbers on small tiles use Bricolage tabular figures, so there are no small monospace labels.
- Scale (1.25): 13 / 15 / 17 / 21 / 27 / 34 / 44, plus Doto 22 / 28 / 160. Weights 400 / 600 / 760 only.

**Layout.** Left-aligned, generous on guest pages, dense on manage. Spacing 4 / 8 / 12 / 16 / 24 / 32 / 48. Radii: 0 for photos and frames (prints have square corners), 10 for controls, full round only for the shutter and toggles.

**Signature element: the frame edge** (Filmrand). A thin strip with sprocket holes and the frame number. It appears:
- under the camera preview, showing the *next* frame number and doubling as the upload progress track;
- on the result print;
- as the caption on admin tiles;
- in the home beer counter.

Spend boldness only there.

**Motion moments.**
1. **Develop**: a fresh print fades from black to the image over about 700 ms, opacity and contrast only. Used on the result and on new live tiles. It replaces the yellow-border "arrive" flash.
2. **Grease pencil**: hiding draws an X stroke in 180 ms (SVG stroke-dashoffset); unhiding erases it.
3. **Frame advance**: after a beer, the sprocket strip shifts one frame (250 ms) and the Doto counter ticks.

Reduced motion means instant state changes. Confetti goes, replaced by develop.

**Camera screens.** Pure black. Paper-white outline with a black halo. Safelight shutter ring and countdown ring. Amber chrome keeps night vision and adds little colour cast to faces. Optional "screen flash" (a full white frame for 120 ms) as front light in the dark room, a behaviour that already exists (`vb-flash`).

**Admin.**
- Live: dark (Rotlicht), so the host isn't blinded at the party.
- Manage: light table (Leuchttisch) with Negativ-Blau ink; a calm dense grid and tables. Hidden = Fettstift X. Selected = Fettstift circle. Instagram "Erledigt" = a pencil tick.
- Same type and frame edge, so it reads as one brand.

**awesome-design inputs.**
- *dithered*: dot-matrix numerals and halftone feel.
- *dramatic*: black stage, theatrical contrast for the camera.
- *stitch*: calm, high-contrast data density on a non-white working surface for manage.
- *geometric*: square frames, strict grid.

**Self-check against frontend-design tells.**
- Not cream/serif/terracotta.
- Not near-black plus one acid accent: the dark is a deliberate red-brown, there are two subject-derived accents (safelight amber, grease red), and half the product is a light mode.
- No broadsheet hairlines.
- No SaaS card kit: frames, not cards; no soft grey shadows.
- No caps eyebrows, no mono small labels, no "→" on buttons, no middle-dot meta strings (use tables or line breaks).

### B. "Fotoautomat": the Berlin analog photo booth machine

**Idea.** The street photo booth: enamel signage, anthracite housing, chrome, red curtain, the "ready" lamp, and the 4-frame strip that drops from the slot.

**Palette.**

| Name | Hex | Contrast |
|---|---|---|
| Vorhang | `#8E1B2A` | white on it 9.0:1 |
| Gehäuse | `#26282C` | Chrom `#D9DDE3` on it 10.8:1 |
| Lampe | `#FFC531` | 9.3:1 on Gehäuse; ink `#1A1A1A` on it 11.0:1 |
| Alu | `#EEF0F2` (admin) | Gehäuse text 12.9:1; muted `#5B616B` 5.5:1; Vorhang on Alu 7.9:1 |
| Kamera-Schwarz | `#000000` | — |

**Type.** **Archivo** (variable wdth 62–125, wght 100–900; `@fontsource-variable/archivo`), one family. Condensed heavy (wdth 62) for enamel-sign display and numerals; normal width for UI.

**Layout.** The home screen is the machine front: two enamel "slot" panels with a coin-slot-like CTA. The camera is inside the booth: curtain-red band at the top, chrome-ringed shutter.

**Signature: the "Bitte lächeln" lamp** above the preview. It lights during the countdown and blinks on capture.

**Motion.** The result strip slides down out of a slot (Fotobox). The Beer Cam counter is a mechanical odometer whose digits roll.

**Admin.** An aluminium service panel: light Alu surfaces, anthracite text, Vorhang red for destructive actions, odometer counts.

**awesome-design inputs.** *vintage* (nostalgia, skeuomorphic hints), *bold* (heavy display), *pulse* (thick structural borders on panels).

**Risk.** Skeuomorphism can turn kitschy, and chrome in a dark room glares. It fits the Fotobox better than the Beer Cam or the admin.

### C. "Partyflyer": a two-ink riso flyer with a beer-coaster tally

**Idea.** The party's flyer, printed in two fluorescent inks on night-blue card. The Beer Cam counts like a waiter's beer coaster: tally strokes in groups of five.

**Palette.**

| Name | Hex | Contrast |
|---|---|---|
| Nachtblau | `#0D1B4C` | white on it 16.4:1 |
| Fluo-Pink | `#FF4FA3` | 5.4:1 on Nachtblau; Nachtblau text on it 5.4:1 |
| Sonnengelb | `#FFD000` | 11.2:1 on Nachtblau |
| Papierweiß | `#FFFFFF` | Nachtblau on it 16.4:1 |
| Kronkorken | `#C42B26` | white on it 5.6:1; on dark use `#FF6E5E` 6.0:1 |

**Type.**
- **Anybody** (variable wdth 50–150; `@fontsource-variable/anybody`) for display. Countdown digits stretch from ultra-condensed to ultra-wide.
- **Atkinson Hyperlegible Next** (OFL, 2025; `@fontsource-variable/atkinson-hyperlegible-next`) for UI and body. It was built for low-vision legibility, which helps tipsy eyes in the dark.

**Layout.** Poster-like home with oversized type. Misregistered two-ink offset (pink and yellow layers offset 2 px) on headings and the shutter.

**Signature: the tally-stroke beer counter.**

**Motion.** A tally stroke is drawn on each beer; countdown digits stretch per second.

**Admin.**
- Live: on Nachtblau.
- Manage: on white "paper" with blue ink, pink selection and yellow highlighter for tagged handles.

**awesome-design inputs.** *riso* (two-ink, offset print shadow), *expressive*, *dithered* (halftone empty states).

**Risk.** Loud for dense admin work. Offset text effects need a clean text layer for accessibility. Fluorescent pink at night skews close to today's look.

### Recommendation: A, "Kontaktbogen"

1. **One metaphor covers all three surfaces.** Taking photos = exposing frames; the timelapse = the film; moderation = marking a contact sheet. No other direction makes the admin as natural as the guest side.
2. **It is native to a dark room.** A safelight is the light people use in the dark: amber chrome on black keeps night vision and won't blind a tipsy guest or cast colour on selfies.
3. **It gives the admin an honest light mode** (light table) for calm desktop density, without leaving the brand. The dark live mode stays on the host's phone.
4. **It makes the moderation rules visible.** The grease-pencil X is a reversible mark (hide, allowed on live); delete is a separate, dialog-guarded removal (manage only).
5. **The data already fits.** Frame numbers exist per activity; upload progress becomes the frame-edge track; "develop" gives one memorable motion moment instead of scattered effects.
6. **It is the furthest from the current template.** No gradients, no emoji icons, square prints.

Borrow from C, optionally: Atkinson Hyperlegible Next as a fallback for long body text if Bricolage reads too quirky at 15 px in testing.

---

## 7. Component inventory (new design system)

| Component | Variants | States | Notes |
|---|---|---|---|
| Button | primary (Safelight), secondary (outline), quiet (text), danger (Fettstift), on-camera (translucent on black); sizes L 56, M 48, S 44 (desktop admin may be 36 visual with a 44 hit area) | default, hover, focus-visible, pressed, disabled, loading ("Sendet…", keeps width) | Label is a verb; optional left SVG icon; never emoji |
| IconButton | toolbar, camera, close, nav | + tooltip on desktop | 44×44 min (48 on camera); aria-label required |
| Icon set | one SVG set (Lucide ISC or Phosphor MIT, tree-shaken, inline) | — | Replaces about 146 emoji and the unicode glyphs; aria-hidden when decorative |
| Shutter | beer, booth | idle, camera-not-ready, ready, pressed, counting (ring drains), capturing (flash), blocked (paused/stopped: lock glyph, tap explains) | 80 px; Space/Enter; kbd hint on desktop |
| Countdown | 3-2-1 | running, cancelled | Doto numeral plus ring; aria-live assertive once; reduced motion: no scale |
| Segmented control | 2–4 options (Flasche/Becher; Alle/Sichtbar/Ausgeblendet; guest filters) | selected, focus, disabled | radiogroup; 48 h; labels ≥14 px; never wraps (falls back to a select) |
| Filter carousel | swatch (prerendered sample thumbnail per filter) | selected (ring plus name), focus, unsupported (disabled with reason) | listbox; scroll-snap center; arrow keys; edge fade affordance |
| Camera chrome | top bar, frame edge, hint line, control row; layouts: portrait, short-screen overlay (≤700 px), landscape split, desktop | — | Safe-area insets; black stage; out-of-crop dimming optional |
| Frame edge (signature) | camera (next frame), print, tile caption, counter | idle, uploading (progress along sprockets), done, waiting (queued), error (Erneut senden) | Doto only at ≥22 px |
| Print / result | beer success, booth result | developing, uploading, uploaded, queued, failed, saved | Develop motion; actions below |
| Guest pass | compact pill; "Du" sheet | with/without Instagram, paused, stopped, offline, n waiting, banned | 44 h; tap opens the sheet; `translate="no"` on names |
| Activity switcher | title menu | open/closed | Sheet on phones |
| Status pill (admin uploads) | an / neue pausiert / gestoppt | busy, live-updating | In both headers and the bottom bar; opens the sheet |
| Toast | info, success, error, with action (Rückgängig, Erneut senden) | enter, exit, replaced | Bottom (above controls or nav); max 1 visible; 4–6 s, longer with an action; role status/alert; never over focus or sheet headers; none while a sheet shows the same state |
| Sheet | bottom sheet (phone) / centered dialog (desktop): join, Du, upload controls, ban, activity menu | opening, scrolled (sticky footer), busy, error | Focus trap, Esc, `overscroll-behavior: contain`; name "Sheet" |
| Confirm dialog | destructive, neutral | busy | Title is a question; primary button repeats the verb |
| Notice (full screen) | gate, 404, camera denied, in-app browser, banned, load failed, offline, fatal | — | SVG icon, title naming the problem, 1–2 sentences, primary plus secondary; consistent buttons |
| Activity card (home) | beer, booth, future extensions | default, pressed, focus, disabled | Whole card is a link; live line (counter / filter count) |
| Photo tile | live (dark), manage (light), user page, Instagram strip | loading (blur placeholder), default, new (develop), hidden (grease X), selected (grease circle), focus, busy | 3:4 with width and height; caption = frame edge; 44 px toggle |
| Viewer (lightbox) | live (hide only), manage (all actions) | thumb→full, hidden, first/last | `?photo=` deep link; swipe, arrows, buttons |
| Inspector panel | manage desktop | empty, single, multi-select summary | Replaces the lightbox for quick actions |
| Selection bar | manage | n selected, busy | Sticky bottom; content gets bottom padding so it never covers the last row; single row on phone (overflow into a menu) |
| Sidebar nav / tabs | admin desktop sidebar; phone bottom bar; phone section select | active, focus, count | URL-synced |
| Data table | Gäste, Sperren, Protokoll, Instagram | loading, empty, sorted, row hover/focus, row link | Tabular nums; sticky header; horizontal scroll with shadow affordance on phones |
| Badge | Ausgeblendet, Gesperrt, Automatisch gesperrt, Hochladen pausiert, Neu | — | Sentence case; icon plus text, never colour only; ≥12 px |
| Switch | upload controls, guest pause | off, on, busy, disabled | role=switch; label plus state text; emergency row variant |
| Text input | Instagram (with "@" prefix), search, ban reason, password | focus-visible, error (inline, focused), disabled | inputmode, autocomplete off (not on password), spellcheck false; placeholder ends "…" |
| Select | filters | — | Explicit colours (Windows dark mode) |
| Checkbox | tile select, "Gerätemerkmal auch sperren" | checked, mixed (select all), focus | 44 hit area |
| Empty state | live none yet, filter empty, no bans, no Instagram, no own photos | — | Invitation plus action |
| Skeleton | grid, table, counter | — | No layout shift |
| Connection indicator | verbunden, verbindet…, nur Abfrage, getrennt | — | Dot plus text |
| Beer counter | home, camera, success | idle, tick | Doto, tabular, aria-live polite on change |
| Help disclosure | "?" next to complex controls | collapsed, expanded | Where the long explanations go |
| Debug panel | `?debug=1` | — | Keep as is |

---

## 8. Quick wins vs structural changes

**Quick wins.** Small and local; carry them into the rebuild from day 1. They also work as hotfixes on `main` if wanted.
1. One toast slot at the bottom, max one visible, replace instead of stack, clear on state change. This fixes the stale error toast on Beer Cam success and toasts covering sheets, headers and lightbox nav.
2. Apply the glossary (§3.4), especially Ausblenden/Einblenden and the three "Nochmal" meanings.
3. Remove emoji from labels and headings; adopt one SVG icon set.
4. Fix the banned user's "Darf hochladen" (show "Gesperrt" in the Hochladen panel).
5. Beer Cam: when paused or stopped, block or explain at the shutter, or queue the shot. Never discard silently.
6. Filter name off the face; filter labels only under the selected swatch, at ≥14 px.
7. Lightbox meta through `meta_labels` (human names); "Herunterladen".
8. Make the emergency stop the first, largest row; one status line; explanations behind "?".
9. `:focus-visible` rings on inputs and selects; `translate="no"` on names, handles and brand words; tabular-nums on numbers; ellipsis and apostrophe fixes; no autofocus on phone login.
10. Pull-to-refresh: `overscroll-behavior: none` only on camera stages, or under `(pointer: fine)`.

**Structural** (the overhaul):

| Change | Why | Touches |
|---|---|---|
| Design tokens (colour, type scale, spacing, radius, z-layers, motion) plus a component library in the new framework | Root cause R1, R2 | Frontend |
| Camera screen rebuild: black stage, edge-to-edge 3:4, layout slots for hint, status and toast, short-screen and landscape variants | R5, R6 | Shared camera chrome used by both extensions |
| Guest pass, status slot and activity switcher | Persistent identity, no floating chips | Core SDK |
| Never-lose-a-shot outbox for the Beer Cam too (IndexedDB queue shared with the Fotobox) | P0 data loss | SDK (keep the preview-equals-saved rule) |
| Admin live grid with undo and a bottom bar; manage desktop with sidebar, dense grid, inspector, tables | R7 | Admin |
| User page restructure (status line, two actions, ban in a sheet, technical details collapsed) | Phone length, destructive-first | Admin |
| "Deine Bilder" on the start screen | Return-visit value | **New API**: the guest's own photo list (stays inside "served only to owner") |
| Export section (archive download, timelapse job with progress, QR sheet) | Host after the party | **New API and background jobs**; CLI tools stay |
| Instagram board with ZIP per handle and an "Erledigt" mark | Tagging workflow | New API (zip stream); optional new state |
| Deep links (`?photo=`), skip link, h1 per page, readable audit targets | A11y, navigation | Admin and API (audit join) |
| Optional app-shell service worker | Offline notice and outbox | Frontend (CSP-compatible) |

---

## 9. Behaviour bugs and defects found during the audit (for architecture and QA)

1. **Stale error toast on success.** After a failed Beer Cam upload, the retry succeeds but "Keine Verbindung. Nochmal versuchen?" stays on top of the success screen (`b05-success-phone`, `b05b-success-settled-small`).
2. **Banned guest shown as allowed to upload.** Banned and auto-banned guests' user pages show "✓ Darf hochladen" (`a30-user-banned-desk`, `a30-user-autobanned-phone`).
3. **Beer Cam discards shots when uploads are stopped or paused.** The shutter is enabled and the photo is lost: no save, no queue (`s04`, `s07`).
4. **Toast stacks cover controls:** the upload sheet title and close (`a41`, `a42`), the live header (`a11`, `a43`), lightbox prev/next (`a12`), and the Fotobox top bar (`f03`).
5. **Guest pause chip overlaps the Fotobox result print** (`s09`).
6. **Same error twice** (toast plus inline) on a Beer Cam upload error (`b04`).
7. **Admin phone landscape shows no content** under the sticky header (`a20-manage-fotos-land`); live landscape fits one row (`a10-live-land`).
8. **Tab strip and Protokoll table clip** with no affordance (`a20-*-phone`).
9. **Loading text crossed by the bottle outline** on the Beer Cam (`b00`).
10. **Raw meta ids in the lightbox and raw ids in the audit log.**
11. **Phone bulk bar wraps to 3 rows** over tiles (`a21-…-phone`).
12. **Desktop guest and admin layouts are scaled-down phone layouts**: 9–12 px effective text in large empty canvases (`g05-home-desk`, `f02-camera-party-desk`, `a20-*-desk`).

---

## 10. Reproduce and compare after the rebuild

Scripts are in the scratch root above. Run them in this order:

```bash
UX=<scratchpad>/ux-audit
cd <repo> && uv run virtubooth gen-env > $UX/env && $UX/serve.sh &   # port 8121, data in $UX/data
cd $UX && PY=<repo>/.venv/bin/python
$PY phase_a.py          # empty states, then join creates guest_state.json and guest2_state.json
$PY seed.py             # guests and photos through the API (Instagram names are capped at 30 characters)
$PY phase_beer.py; $PY phase_booth.py
$PY moderate.py         # hide, delete, ban with fingerprint, auto-banned twin, pause
$PY phase_admin.py; $PY phase_states.py; $PY measure.py
```

The selectors are the current `data-testid`s. If the rebuild keeps them (recommended, since the e2e tests use them too), the same scripts give the "after" set. Fake cameras come from earlier QA assets: `scratchpad/fakecam/party.y4m` and `scratchpad/scene/scene-{bottle,cup}.y4m`.

`montage.py` and `split.py` build the review sheets. Shot names follow `g*` guest core, `b*` Beer Cam, `f*` Fotobox, `s*` moderation states on the guest side, and `a*` admin, each suffixed with `-{phone,small,land,desk}`. `admin_state.json` (the admin session) was deleted at the end.
