# Design system "Kontaktbogen" (wave 1, FE-foundation)

This is the visual system of the rebuilt frontend. Every photo is a frame on the party's film roll:

- Guests and the live screen work in a darkroom (**Rotlicht**, with a **Safelight** amber accent).
- The host reviews on a light table (**Leuchttisch**) with grease-pencil marks: **X** means hidden, a **circle** means selected.
- The signature element is the **film edge** (Filmrand): sprocket holes plus a frame number. It doubles as the upload progress track.

The direction comes from UX audit §6A, the source of truth is `frontend/src/styles/app.css`, and the components are in `frontend/src/ui/`.

## 1. Process (image-first, adapted)

There is no image model here. The image-to-code step was replaced with static HTML mockups of the key screens, built on the same tokens. I screenshotted them with Playwright at four viewports, looked at every shot, critiqued them against the frontend-design skill and the web interface guidelines, and iterated.

| Path | What |
|---|---|
| `mockups/*.html`, `mockups/kb.css` | The 12 mockup screens and their stylesheet. Fonts come from `frontend/node_modules`, so run `pnpm install` first. |
| `mockups/img/` | Synthetic photos (rendered scenes, no real guests) |
| `shoot.py`, `montage.py` | Screenshot and review-sheet scripts: `python shoot.py <round>` |
| `shots/r1/` | Round 1, before the critique |
| `shots/final/` | After rounds 2 and 3 |
| `shots/gallery/` | The UI gallery built from the real components (`frontend/ui.html`), under the production CSP |
| `shots/app/` | The built app entries (placeholders for wave 2) under the production CSP |

Viewports: phone 390×844 @2x, small 360×640 @2x, landscape 844×390 @2x, desktop 1440×900.

### Critique round 1 (`shots/r1`), and what changed

| Finding | Change |
|---|---|
| The guest pass picked up a native button border (white ring) | `border: 0`. In the components it is a styled RAC element. |
| Doto at weight 800 with `ROND 100` read as thin rings of dots, hard to read at 22–28 px | Doto 900 with `ROND 0` (square LED dots) for 22–28 px; `ROND 60` for the 160 px countdown. Checked in a type specimen. |
| Beer Cam: a dead band of about 100 px between hint and controls on a 390×844 phone | The hint and the control row form one group, centred in the remaining height |
| Beer Cam at 360 px: Flasche/Becher, shutter and camera switch did not fit, and the switch was cut off | The vessel toggle becomes icon-only on narrow screens (`SegmentedControl iconOnly="narrow"`, < 420 px since round 3; labels stay accessible) |
| Desktop Beer Cam: the film edge was wider than the preview | The film edge takes the stage width |
| Fotobox: the filter-name pill sat on the stage (audit R5: over the face) | Removed from the stage. The name shows under the selected swatch and at the right end of the film edge. |
| Countdown: the Doto numeral painted under the ring's dark disc, and the "Abbrechen" button over a busy photo was unreadable | The numeral is stacked above the disc; camera buttons are solid `black/60` with a hairline |
| Captions "Foto 0017 Hüpfendes Alpa…" wrapped and truncated on one line | Two-line captions: the frame label on line 1, the guest (or "Ausgeblendet") on line 2 |
| The toast action and the upload status pill picked up grey native button backgrounds | Transparent; the action is underlined text in `toast-action` |
| Manage desktop showed only 5 columns | Tiles at minmax 104 px plus a 304 px inspector give 7 columns at 1440 px (audit: 7–8) |
| The grease circle ran over the caption | The circle is sized to the photo (3:4.2) |
| Gate: "QR-/Code" broke at the hyphen | "QR-Code" never breaks (`whitespace-nowrap`) |
| The user page used a middle-dot meta string ("@handle · seit 21:07"), a frontend-design tell | Plain comma |
| Desktop Start: a 1080 px two-column layout of tiny content in a void | A 5/7 grid at 1200 px: hero and "Deine Bilder" left, the film strips right |

### Round 2 (`shots/final` minus the round-3 changes), and round 3

- **Admin live in landscape** (844×390): the 4-column grid showed one cut-off row, and the bottom bar took 64 px of 390.
  - The bar becomes a 76 px **left rail** on landscape phones (`BottomBar`, `landscape-phone:` variant).
  - The grid auto-fills 128 px tiles, so one full row and its captions fit.
- **Countdown**: verified the stacking fix; the numeral is legible over a face.
- **Desktop Start**: rechecked; balanced enough for a phone-first page.

### Round 4: the real components in the gallery (`shots/gallery`)

| Finding | Change |
|---|---|
| **CSP:** React Aria 1.22.1 injects `<style>` at runtime, in `usePress` (`#react-aria-pressable-style`, on every pressable) and in `usePreventScroll` on iOS WebKit (every open modal). Both violate `style-src 'self'`. The phase-1 stack research marked RAC as clean. | `frontend/patches/react-aria@3.53.1.patch` (pnpm `patchedDependencies`) removes both. app.css carries the same rules: `[data-react-aria-pressable] { touch-action: pan-x pan-y pinch-zoom }`, and `* { overscroll-behavior: contain }` while `<html data-vb-scroll-lock>` is set. Re-check on every react-aria update. |
| **Locale crash:** with an English browser, React Aria crashed (`longPressMessage` of undefined). The optimize-locales plugin keeps only de-DE strings, and RAC picked en-US from `navigator.language`. | `UiProvider` pins `I18nProvider locale="de-DE"`. Every app root must use it; the browser check runs desktop in en-US. |
| Default classes leaked: `react-aria-TableBody`, `react-aria-ToastList` | `className` is always passed; the browser check fails on any `react-aria-*` class |
| Sprocket holes rendered bright white. Pattern content takes `currentColor` where the `<pattern>` is defined, not where it is used. | One pattern per tone, coloured by class on the hole. Holes are now 6×7 at a 14 px pitch, which reads as sprockets, not a dashed line. |
| Segmented options were truncated ("Ausge…") | Items size to their content; never truncated |
| Inputs on the light table were grey (`sunk`) and read as disabled | New semantic token `field-bg`: white on Leuchttisch, `rot-950` on Rotlicht |
| `Notice inline` was 100dvh tall | `.vb-screen--static` has no min-height |
| The table wrapped names | Cells are `nowrap`; the table scrolls horizontally with edge shadows |
| Lazy images missing from full-page shots | The check script scrolls before the screenshot (not an app bug) |
| ActivityShell at 390 px overflowed sideways by about 14 px (hidden by `overflow-hidden`, found in the shots) | The grid column is `minmax(0,1fr)`, and the vessel toggle goes icon-only below 420 px |

## 2. Tokens (`frontend/src/styles/app.css`)

### Palette

| Token | Hex | Role |
|---|---|---|
| `kamera` | `#000000` | camera stage, film base |
| `rot-950` | `#1c0806` | sunk areas and fields on Rotlicht, the film-strip cards |
| `rot-900` **Rotlicht** | `#2b0f0c` | dark surface (guest, admin live, login) |
| `rot-800` | `#3b1712` | raised: sheets, guest pass |
| `rot-700` | `#4d2019` | hover on dark |
| `papier` | `#fbefe9` | ink on dark, toast on dark |
| `papier-muted` | `#c9b8b0` | secondary ink on dark, film-edge labels |
| `safelight` | `#ffa630` | the one primary action, shutter ring, counters, focus on dark |
| `safelight-hi` | `#ffbb5c` | primary hover |
| `fettstift` | `#c62a22` | grease pencil on light, destructive fills |
| `fettstift-hell` | `#ff7a66` | grease pencil and danger text on dark |
| `fettstift-tief` | `#9e1f18` | destructive hover, toast action on paper |
| `leuchttisch` | `#f4f6f8` | light surface (manage, user page) |
| `leuchttisch-weiss` | `#ffffff` | panels, fields, tables on the light table |
| `leuchttisch-sunk` / `-hover` | `#e7ebf0` / `#eef1f5` | sunk and hover on light |
| `negativ` | `#16203a` | ink on light, selection bar, toast on light, focus on light |
| `negativ-muted` / `-line` / `-field` | `#5a6272` / `#d3d9e0` / `#8a94a3` | secondary ink, hairlines, field borders (3:1) |
| `gruen-hell` / `gruen` | `#84d49b` / `#1d7a44` | "verbunden", "Hochgeladen" (dark / light) |
| `bernstein` / `bernstein-hell` | `#8a5300` / `#ffd9a3` | amber as text on light / on Negativ |

### Semantic colours

Components use only these. Each is defined per surface under `[data-surface="dark|light"]`; `:root` is dark.

| Token | Rotlicht | Leuchttisch |
|---|---|---|
| `surface` / `-raised` / `-hover` / `-sunk` | rot-900 / rot-800 / rot-700 / rot-950 | leuchttisch / white / #eef1f5 / #e7ebf0 |
| `ink` / `ink-muted` | papier / papier-muted | negativ / negativ-muted |
| `line` / `line-strong` / `field` / `field-bg` | papier at 14 % / 30 % / 42 %, field-bg rot-950 | #d3d9e0 / #aeb7c2 / #8a94a3, field-bg white |
| `accent` / `on-accent` / `accent-ink` | safelight / rot-900 / safelight | safelight / negativ / bernstein |
| `danger` / `danger-fill` / `on-danger` | fettstift-hell / fettstift / white | fettstift / fettstift / white |
| `ok`, `focus`, `mark` | gruen-hell, safelight, fettstift-hell | gruen, negativ, fettstift |
| `toast` / `on-toast` / `toast-action` | papier / rot-900 / fettstift-tief | negativ / leuchttisch / safelight |
| `film` / `film-hole` / `film-label` | black / papier at 22 % / papier-muted | (always dark: film looks the same on both) |

Surfaces are chosen per app or area, never by the user:
- `<html data-surface>`: the guest app is dark, admin live and login are dark, admin manage and the user page are light (`useDocumentSurface()` in `src/admin/surface.ts`).
- Nested areas use `<Surface tone>`. Overlays (Sheet, Select, Tooltip, Toast) read it, so their portals match.

### Contrast (WCAG 2.2 AA)

`src/styles/contrast.test.ts` asserts these from app.css: 34 pairs, ≥ 4.5:1 for text, ≥ 3:1 for UI boundaries.

| Pair | Ratio | Pair | Ratio |
|---|---|---|---|
| papier on rot-900 | 15.8 | negativ on leuchttisch | 14.9 |
| papier on rot-800 (sheets) | 14.1 | negativ on white | 16.1 |
| papier-muted on rot-900 | 9.3 | negativ-muted on leuchttisch | 5.7 |
| papier-muted on rot-800 | 8.3 | negativ-muted on leuchttisch-sunk | 5.1 |
| papier-muted on black (film labels) | 11.0 | fettstift on leuchttisch | 5.2 |
| safelight on rot-900 | 9.1 | fettstift on white | 5.6 |
| safelight on black (counters) | 10.7 | negativ on safelight (primary on light) | 8.3 |
| rot-900 on safelight (primary on dark) | 9.1 | bernstein on leuchttisch | 5.8 |
| fettstift-hell on rot-900 | 7.0 | gruen on leuchttisch | 4.9 |
| fettstift-hell on rot-800 | 6.2 | leuchttisch on negativ (selection bar, toast) | 14.9 |
| white on fettstift (danger buttons) | 5.6 | safelight on negativ (toast action) | 8.3 |
| gruen-hell on rot-900 | 10.1 | negativ-field on white (input border, 3:1) | 3.1 |
| fettstift-tief on papier (toast action) | 7.0 | safelight on rot-800 (focus ring, 3:1) | 8.2 |

### Type

**Fonts.** Both are self-hosted from `@fontsource-variable` 5.3.0 with `font-display: swap`, latin and latin-ext loaded by `unicode-range`. Both are OFL.
- **Bricolage Grotesque Variable** (`opsz` + `wght`, 77 KB for latin), used for everything. `font-optical-sizing: auto` makes large sizes characterful and small sizes plain.
- **Doto Variable** (`wght` + `ROND`, 6 KB) for numerals only, at ≥ 22 px (`dots` utility): counters, the next frame on the film edge, the countdown.

**Scale** (font-size / line-height, as Tailwind `text-*`):

| `text-xs` | `text-sm` | `text-md` | `text-lg` | `text-xl` | `text-2xl` | `text-3xl` |
|---|---|---|---|---|---|---|
| 13/18 | 15/22 (body) | 17/24 | 21/26 | 27/32 | 34/38 | 44/46 |

- The three largest sizes have negative tracking.
- Doto sizes: `text-dots-sm` 22, `text-dots-md` 28, `text-dots-xl` 160.
- Weights: `font-normal` 400, `font-semibold` 600, `font-bold` 760. There are no other weights.

**Typography rules.** No caps eyebrows, no monospace labels, no "→" in buttons, no middle-dot meta strings. Use `tabular` (tabular-nums) on every number column and counter. Use NBSP in "1 Mio.", "3 s" and "40 %" (see `src/lib/format.ts`).

### Spacing, radii, layers, motion

- **Spacing.** Tailwind's 4 px base: 4/8/12/16/24/32/48 are `1/2/3/4/6/8/12`.
- **Radii.**
  - `rounded-none` for photos, prints and frames.
  - `rounded-control` (10 px) for buttons, fields and sheets.
  - `rounded-full` only for the shutter, toggles and round photo overlays.
  - Two small extras: `rounded-small` (6 px, elements under 28 px such as checkbox, badge and monogram) and `rounded-hole` (2 px).
- **Shadow.** Only `shadow-float` (toast, popovers). No soft grey card shadows.
- **Z-layers.** Use them as `z-(--z-name)`:

  | Layer | Value | Layer | Value |
  |---|---|---|---|
  | `raised` | 10 | `toast` | 50 |
  | `sticky` | 20 | `screen` (full-screen Notice) | 60 |
  | `bar` | 30 | `boot` (boot-check) | 70 |
  | `sheet` | 40 | `debug` | 80 |

- **Motion durations.**

  | Token | Duration | Used for |
  |---|---|---|
  | `--duration-press` | 80 ms | presses |
  | `--duration-quick` | 180 ms | grease-pencil stroke, toggles |
  | `--duration-base` | 250 ms | sheets, frame advance |
  | `--duration-develop` | 700 ms | develop |

- **Animations:** `animate-develop` (black → image, opacity and contrast only), `-pencil`, `-advance` (the sprocket strip moves one hole), `-sheet-in/out`, `-dialog-in`, `-toast-in`, `-fade-*`, `-shimmer`, `-pop`, `-spin`.
- **Reduced motion.** All durations drop to 0 and animations end at once; `motion-ok:` gates the decorative loops.

### Responsive variants

| Variant | Media query |
|---|---|
| `short:` | `max-height: 700px`: camera chrome overlays the stage |
| `landscape-phone:` | `orientation: landscape` and `max-height: 600px` |
| `fine:` / `coarse:` | `pointer: fine` / `pointer: coarse` |
| `motion-ok:` | no reduced-motion preference |

## 3. Components (`frontend/src/ui/`)

Every component wraps React Aria with our own classes. Every RAC element gets a `className`, and the browser check fails on any `react-aria-*` class. All are presentational: no API calls, no app state.

| Component | Variants | States |
|---|---|---|
| `Button` / `LinkButton` | primary, secondary, quiet, danger, danger-outline, camera. Sizes lg 56, md 48, sm 44, xs 36 (44 px hit area). block | hover, pressed, focus-visible, disabled, pending (spinner, label keeps its width, announced) |
| `IconButton` | plain, camera, overlay (round, over photos); 44/48 | tooltip on desktop; aria-label is required (`label`) |
| `Sheet` | bottom sheet on phones, centred dialog from 640 px; sm/md/lg; title lg/xl | dismissable (close button, Esc, scrim) or not (join); sticky footer with an edge when the body scrolls; focus trapped and starting on the dialog; `overscroll-contain`; `vb-scrim` on the root, never "modal"/"backdrop" |
| `ConfirmDialog` | danger, neutral | focus starts on "Abbrechen"; busy while `onConfirm` resolves; inline error |
| `Toast` (`showToast`, `clearToasts`, `<ToastSlot>`) | info, success, error; optional action (Rückgängig, Erneut senden) | One slot: a new toast replaces the old one. 5/6/7 s. The only file using `UNSTABLE_Toast`. |
| `Notice` | full screen (fixed) or `inline` | role alert or status; CSS class `vb-screen`, shared with `public/boot-check.js` |
| `Switch` | plain, row, emergency (red when on) | on, off, pending (blocked, pulsing), disabled; `role=switch`; state in words via `description` |
| `SegmentedControl` | tone surface/camera, md 48 / sm 40, iconOnly true/"narrow" | selected, focus, disabled; it is a radiogroup |
| `TextField` | prefix ("@"), leading icon, hidden label, md/sm | focus ring, inline error (`aria-invalid`), disabled; ≥ 16 px input on touch; spellcheck and autocapitalize off with a prefix |
| `Select` | visible or inline label (muted prefix) | open, selected tick, placeholder, disabled |
| `Checkbox` | plain, tile (over a photo corner) | checked, mixed, focus, disabled; 44 px hit area |
| `Badge` | neutral, mark, amber, ok, new | icon plus text, never colour alone |
| `Tabs` / `TabList` / `TabPanel` | scrolling strip with shadows | selected underline, counts |
| `SidebarNav` | header, items with counts, footer | current (`aria-current`, bar) |
| `BottomBar` (+ `bottomBarInset`) | link or button items | current; a left rail on landscape phones |
| `DataTable` | sortable columns, row header, end-aligned numbers, hidden-below breakpoints | sorted, row hover and link (`onRowAction`), empty, loading (skeleton rows); sticky header inside `maxHeightClass`; horizontal scroll with edge shadows |
| `PhotoTile` | open button, overlay slot, selection checkbox | hidden (grease X drawn in, dimmed, "Ausgeblendet"), selected (grease circle), new (develop), busy; 3:4 with width and height |
| `GreaseX` / `GreaseCircle` | animated stroke or static | |
| `FilmEdge` | md (camera, print) / lg (counter); holes top/bottom/both | idle, uploading (holes fill in Safelight, `role=progressbar`), done, waiting (dim amber), error (grease red); `advanceKey` plays the one-frame advance |
| `Shutter` | | ready, not-ready (disabled), counting (the ring drains), capturing (pop), blocked (lock, still pressable to explain); key hint on fine pointers |
| `Countdown` | | Doto 160 numeral in a draining ring; cancel button; announced once (assertive) |
| `ConnectionIndicator` | live, connecting, reconnecting, polling, offline | dot plus words ("verbunden / verbindet… / nur Abfrage / getrennt") |
| `StatusPill` | on, paused-new, stopped | the admin upload status; opens the sheet |
| `EmptyState`, `Skeleton` / `SkeletonGrid`, `Spinner`, `Progress` | | |
| `HelpDisclosure` | inline ("?") or section (chevron, e.g. Technische Details) | collapsed, expanded |
| `Surface`, `UiProvider` | | the area tone for overlays; locale pin and router for RAC links |

## 4. Rules for wave 2

1. **App roots** wrap in `<UiProvider navigate={…}>`, call `markReady()` (`src/lib/boot.ts`) once rendered, and call `installPreloadRecovery()`.
2. **CSP.** No `<style>`, no `dangerouslySetInnerHTML`, no eval. `style={{}}` is fine (CSSOM). New libraries must be checked with `scripts/browser-check.py` against a built `dist`. The lint config already bans the known offenders (sonner, vaul, Radix, motion, emotion, styled-components, bare `zod`).
3. **Neutral names** in files, classes, ids and test ids:
   - none of consent, cookie, gdpr, banner, notice, modal, backdrop, privacy, popup, fingerprint, track, beacon, `ad(s)`;
   - examples: `vb-screen` for the full-screen state, `vb-scrim` for overlays, `vb-sheet`, `vb-film`, `vb-activity`.
   
   `pnpm build` fails on blocker-prone asset names or CSS selectors (`scripts/check-names.mjs`).
4. **One toast slot per page.** Position it with `ToastSlot className` (ActivityShell already places it above the controls), and call `clearToasts()` when the state it reported changes.
5. **Typography.** Use `src/lib/format.ts` for every number, date and frame label, and the glossary in `src/lib/messages.de.ts` for words.
6. **Photos** are `PhotoTile` with real `width`/`height`, `loading="lazy"` below the fold, square corners, and the grease marks for state.
7. **Design references** for each screen are in `mockups/` and `shots/final/`.

## 5. Self-check

Against frontend-design:
- Not cream with a serif and terracotta.
- Not neutral near-black with one acid accent: the dark surface is a red-brown, there are two subject-derived accents, and half the product is light.
- No broadsheet hairline layout, and no SaaS card kit: the activity cards are film strips, photos are square prints, and there is one shadow token.
- No caps eyebrows, no mono labels, no "→", no middle dots.
- The boldness is spent on the film edge and the Doto counters only.

Against the web interface guidelines:
- focus-visible rings everywhere;
- 44 px targets;
- `overscroll-behavior` contained in sheets, page rubber-banding off only for fine pointers;
- `touch-action` set;
- `color-scheme` set per surface;
- `theme-color` per area;
- `translate="no"` on names, handles and brand words;
- tabular figures;
- "…" in loading labels and placeholders;
- labels on every field;
- `aria-live` on toasts and the countdown;
- reduced motion honoured;
- images with dimensions;
- no `transition: all`;
- autofocus only on the confirm dialog's cancel button.

## 6. Open points for later waves

- Fonts are not preloaded: the hashed woff2 names are only known after the build. A tiny Vite plugin could add `<link rel="preload">`. They are small (≤ 77 KB) and swap.
- The production CSS also contains the gallery's few extra classes, because Tailwind scans the whole frontend. This is negligible.
- `ActivityShell` is a working first cut (GP owns it). Camera pages still need the real stage (CameraSession) and the camera-specific landscape behaviour.
- The gate page shows both copies to visitors without CSS (it has no JS on purpose).
