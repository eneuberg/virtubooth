# Abschlussbericht: Überarbeitung von virtubooth

Stand 13.10.2026. Basis vor der Überarbeitung: `main` auf `1d6b5eb`. Danach 122 Commits
bis zum Merge `01960c7`, plus die Nacharbeiten auf `fin/*`. Nichts wurde gepusht.

## Kurzfassung

- virtubooth ist neu aufgebaut: ein Frontend mit React 19 und TypeScript statt
  handgeschriebenem HTML/CSS/JS, ein Backend in Schichten, eine neue Ordnerstruktur
  und das neue Design „Kontaktbogen“.
- Alle bisherigen Funktionen sind geblieben. Neu sind unter anderem „Deine Bilder“,
  der Gästepass, die Outbox auch für die Beer Cam, Exporte im Admin und das
  Instagram-ZIP mit „Erledigt“.
- Sicherheitsreview: 0 kritisch, 0 hoch, 1 mittel, 5 niedrig, 9 Info. Der mittlere
  und alle niedrigen Befunde sind behoben.
- Dringend: SEC-13 heute ab 18:30 Uhr erledigen (siehe Todos).

## Was gemacht wurde

### Stack

| Bereich | Jetzt |
|---|---|
| Frontend | React 19.3 mit React Compiler, TypeScript 6 (strict), Vite 8 (drei Einstiege: Gast, Admin, Gate), Tailwind CSS 4.3, React Aria Components, TanStack Query, wouter, zustand, zod |
| API-Client | aus dem OpenAPI-Schema des Backends generiert (`make openapi`), CI schlägt bei Abweichung fehl |
| Backend | Python 3.14, FastAPI 0.143 in Schichten, Pydantic-Modelle für jede Antwort, pydantic-settings für alle `VB_*` |
| Datenbank | SQLite (WAL) mit den bisherigen Migrationen; neue Schritte sind angehängt, eine alte Datenbank wird beim Start aktualisiert |
| Werkzeuge | uv, pnpm 11, ruff, mypy --strict, oxlint, Prettier |
| Betrieb | ein Docker-Image (eine Node-Stufe baut das Frontend), Compose- und Coolify-Datei, CI unter `.github/workflows/ci.yml` |

Vorher war das Frontend rund 6.500 Zeilen JavaScript, 2.300 Zeilen CSS und sechs
HTML-Seiten, alles im Ordner `virtubooth/` neben dem Server.

### Ordnerstruktur

```
virtubooth/
├── backend/                 Python-Paket und Tests
│   ├── src/virtubooth/
│   │   ├── core/ db/ domain/ repositories/ services/ api/ web/
│   │   ├── extensions/      sdk.py, beer/, booth/
│   │   └── tools/           qr, timelapse, export (Kommandozeile)
│   └── tests/               unit/, api/, e2e/ (Playwright)
├── frontend/                React-App
│   ├── index.html  admin.html  gate.html
│   └── src/                 api/ ui/ styles/ sdk/ guest/ admin/ extensions/ lib/
├── docs/                    ARCHITECTURE.md, DEPLOY.md, overhaul/
├── scripts/                 docker-smoke.sh
└── Dockerfile  compose.yaml  docker-compose.coolify.yaml  Makefile
```

### Design „Kontaktbogen“

- Jedes Foto ist ein Bild auf dem Filmstreifen der Party.
- Gäste und die Live-Ansicht sind eine Dunkelkammer: dunkles „Rotlicht“ mit dem
  Bernstein-Akzent „Safelight“.
- Die Verwaltung ist ein heller „Leuchttisch“ mit Fettstift: X heißt ausgeblendet,
  ein Kreis heißt ausgewählt.
- Erkennungszeichen ist der Filmrand mit Perforation und Bildnummer. Er zeigt auch
  den Upload-Fortschritt.
- Schriften: Bricolage Grotesque für alles, Doto nur für große Ziffern. Beide sind
  selbst gehostet. Icons von Lucide statt Emoji.
- Vorgehen: erst Mockups der Hauptscreens in vier Größen, Kritik, dann die echten
  Komponenten in `frontend/src/ui/`. Details: `docs/overhaul/design/DESIGN.md`.

### Architektur

- **Backend in Schichten.** Importe gehen nur nach unten. Router schreiben kein SQL,
  Repositories senden keine Events. Nur Services öffnen Schreib-Transaktionen. Das
  Audit-Log wird in derselben Transaktion geschrieben wie die Änderung, Events und
  Dateilöschungen laufen erst nach dem Commit.
- **Acht bekannte Fehler behoben**, je mit Test: unter anderem verpasste Live-Events,
  ein hängender Event-Stream, nicht atomares Audit und Löschen vor dem Commit.
- **Erweiterungsplattform.** Jede Aktivität besteht aus zwei Hälften mit derselben ID:
  - Backend: `backend/src/virtubooth/extensions/<id>/` mit `extension = Extension(...)`:
    Titel, Upload-Regeln (Größe, erlaubte Metadaten), optional eine eigene API unter
    `/api/x/<id>/` und ein `on_upload`-Hook.
  - Frontend: `frontend/src/extensions/<id>/index.ts` mit
    `defineExtension({id, load, card})`: die Seite unter `/x/<id>/` und optional die
    Live-Zeile auf Start.
  - Den Rest macht der Kern: Gate, Beitritt, Upload, Speicherung, Limits, Moderation,
    Karte auf Start, Umschalter, Admin-Ansichten, QR-Codes, Exporte und Zeitraffer.
- **Neue Aktivität hinzufügen:** Backend-Paket anlegen, Frontend-Ordner mit einer Seite
  auf `ActivityShell` anlegen, optional in `VB_EXTENSIONS` eintragen, e2e-Tests in
  `backend/tests/e2e/activities/`. Ein Unit-Test schlägt fehl, wenn eine Hälfte fehlt.
  Ein vollständiges, getestetes Beispiel („Schnappschuss“) steht in
  `docs/ARCHITECTURE.md` unter „Adding an activity“.

### Zum Schluss

- Die Kommandozeilen-Werkzeuge benennen Dateien jetzt in `VB_TIMEZONE` wie die Exporte
  im Admin (vorher UTC).
- Beim sauberen Stoppen schreibt der Server die WAL-Datei in `virtubooth.db` zurück.
  Ein kopierter `data/`-Ordner enthält dann alles in dieser einen Datei.
- Die alten DOM-Tests (`backend/tests/e2e_legacy/`) sind gelöscht. Sie sind nach
  `backend/tests/e2e/` portiert.

## Funktionen: neu und vorher

### Gäste

| Funktion | Vorher | Jetzt |
|---|---|---|
| Beitritt | Einwilligungsdialog | Beitritts-Sheet: Partyname, was mit den Fotos passiert, optional der Instagram-Name, ein Knopf „Alles klar, los geht’s!“, kein „Nein“. Die Texte kommen vom Server. |
| Identität | Namens-Chip | Gästepass auf Start oben links (Pseudonym, Instagram-Name, Statuspunkt), auf den Kamera-Seiten kompakt oben rechts. Er öffnet das „Du“-Sheet (Instagram ändern, Pause und wartende Fotos sehen). |
| „Deine Bilder“ | gab es nicht | Auf Start die eigenen sichtbaren Fotos (neu: `GET /api/me/photos`), groß ansehen und speichern. |
| Outbox | nur Fotobox | Beide Aktivitäten. Jedes Foto liegt zuerst im Gerät (IndexedDB) und bleibt dort, bis der Server es hat. Neuer Versuch, wenn das Netz zurück ist, der Tab wieder sichtbar wird, alle 30 s und beim nächsten Besuch. Bei Fehlern „Erneut senden“. |
| Pause/Stopp | Foto wurde gemacht, dann verworfen | Der Auslöser ist vorher gesperrt und sagt, warum. |
| Start | Kacheln | Filmstreifen pro Aktivität mit Live-Zeile (Bierzähler, Fotobox-Beispielbilder); Umschalter im Seitentitel. |

### Admin

| Funktion | Vorher | Jetzt |
|---|---|---|
| Live | nur Ausblenden | Kein Löschen; Aus- und Einblenden mit „Rückgängig“. Dichtes Raster, 44-px-Schalter, „Rückgängig“ im Toast, Leiste unten am Handy (im Querformat links), Verbindungsanzeige. |
| Verwaltung | Tabs | Seitenleiste am Desktop: Fotos (Kontaktbogen, Filter, Mehrfachauswahl mit Tastatur, Inspektor), Gäste, Instagram, Sperren, Protokoll, Export. |
| Gästeseite | viele Panels | Statuszeile, Fotos, „Hochladen pausieren“, Sperre im Sheet („Gerätemerkmal auch sperren“), Technik eingeklappt. |
| Upload-Steuerung | Chip und Sheet | Status-Pille öffnet das Sheet „Hochladen“: „Hochladen für alle stoppen“, „Neue Gäste pausieren“ (beim Beenden: Betroffene freischalten oder pausiert lassen), Liste der pausierten Gäste mit „Freigeben“. Pro Gast auf der Gästeseite. Der Fokus bleibt im Sheet. |
| Exporte | nur Kommandozeile | Unter Export: Archiv (ZIP mit Fotos, CSV-Listen, optional der Datenbank), Zeitraffer (MP4) und QR-Bogen. Hintergrund-Jobs mit Fortschritt und Download, die neuesten 10 Dateien bleiben. Die Kommandozeile gibt es weiter. |
| Instagram | Handles kopieren, Fotos ansehen | Dazu ein ZIP pro Handle und die Markierung „Erledigt“. |
| Protokoll | Tab | Gleicher Inhalt, jetzt als Tabelle, auch auf dem Handy lesbar. |
| Deep Links | gab es nicht | `?photo=<id>` öffnet ein Foto in Live, Fotos und auf der Gästeseite. |

### 404-Gate

Vorher gab es zwei handgeschriebene Seiten (`gate.html`, `notfound.html`), und
`/static` war öffentlich. Jetzt ist es eine gebaute Seite `gate.html` im neuen Design
für „Scan den QR-Code“ und „Hier ist nichts“. Sie kommt immer mit HTTP 404, funktioniert
ohne JavaScript und gibt in In-App-Browsern einen Hinweis. Ohne Party-Cookie liefert der
Server nur das Gate und eine kurze Liste von Dateien (Icons, `boot-check.js`,
`robots.txt`).

## Sicherheit

Ein unabhängiger Review hat die ganze Änderung geprüft, mit Live-Tests gegen einen
Testserver: **0 kritisch, 0 hoch, 1 mittel, 5 niedrig, 9 Info.** Das Grundmodell hält
(Party-Token, signierte Cookies, Admin-Sessions, CSRF-Prüfung, Größenlimits, Zugriff auf
Fotos, Upload-Prüfung). Alle 28 Admin-Routen weisen Gäste und Anonyme ab.

Behoben, jeweils mit Regressionstest:

- **SEC-01 (mittel), Passwort-Raten beim Login:** Limits pro IP gelten für IPv6 pro /64.
  Nach 20 Fehlversuchen in 15 Minuten wird 5 Minuten lang jeder Login abgelehnt, auch
  der richtige. Beim Start warnt das Log vor schwachen Passwörtern.
- **SEC-02:** JPEG-Kommentare blieben im Foto. Jetzt werden alle Metadaten entfernt,
  auch im Vorschaubild.
- **SEC-03:** Die Datenbank-Kopie im Archiv enthielt Admin-Sessions. Jetzt sind Sessions
  und Export-Jobs geleert, und die Kopie ist mit VACUUM bereinigt.
- **SEC-04:** Die CSRF-Prüfung ignorierte das Schema. Jetzt zählt der volle Origin.
- **SEC-05:** Vorkomprimierte HTML-Dateien umgingen das Gate. Jetzt gilt eine
  Allow-Liste.
- **SEC-06:** Der Event-Stream lief nach dem Logout bis zu 45 s weiter. Jetzt endet er
  sofort, und es gibt höchstens 4 Streams pro Session.
- Info: Token im Log immer maskiert (SEC-07), `VB_DEV` nicht mehr im Image (SEC-08),
  HTML `private` (SEC-09), höchstens 20 Gerätemerkmale pro Gast (SEC-10, teilweise),
  Grenze für progressive JPEGs (SEC-14), `*` in `VB_FORWARDED_ALLOW_IPS` ist ein
  Konfigurationsfehler (SEC-15).

Akzeptiert mit Begründung: der Rest von SEC-10 (das Gerätemerkmal ist nur ein Hinweis),
SEC-11 (`uid_token` ohne Ablauf), SEC-12 (Exporte können die Platte füllen; es gibt
Platzprüfung und Aufräumen). Offen: SEC-13 (siehe Todos). Details:
`docs/overhaul/SECURITY_REVIEW.md`.

## Tests

| Lauf | Was | Ergebnis |
|---|---|---|
| `make check` | Lint, Typecheck, Tests, OpenAPI-Abgleich | {{TEST_CHECK}} |
| Backend (pytest) | API, Migrationen, Werkzeuge, Web-Auslieferung, Content-Blocker | {{TEST_BACKEND}} |
| Vitest | SDK, Fehlerabbildung, Formatierung, Komponenten | {{TEST_VITEST}} |
| e2e Chromium | echte Browser gegen das gebaute Frontend, ohne Konsolenfehler | {{TEST_E2E_CHROMIUM}} |
| e2e Firefox | dasselbe in Firefox | {{TEST_E2E_FIREFOX}} |
| e2e WebKit | dasselbe in WebKit (Docker, `run_webkit.sh`) | {{TEST_E2E_WEBKIT}} |
| `make docker-smoke` | Image bauen, starten, Ende-zu-Ende prüfen | {{TEST_DOCKER_SMOKE}} |

## QA

{{QA}}

## Entscheidungen

- **FastAPI bleibt**, mit rohem `sqlite3` und den eigenen Migrationen. Kein ORM.
- **API-Pfade bleiben gleich** (kein `/api/v1`); Antworten bekommen höchstens neue Felder.
- **Ein Container, ein Worker.** Rate-Limits und Live-Events liegen im Speicher.
- **Strenge CSP bleibt** (`script-src 'self'`, `style-src 'self'`). Dafür entfernt ein
  pnpm-Patch zwei `<style>`-Injektionen von React Aria.
- **Neutrale Namen** in Dateien, Klassen und IDs, damit Content-Blocker nichts
  ausblenden. Der Build bricht bei verdächtigen Namen ab.
- **Nicht gebaut:** Service Worker, Live Wall (die Erweiterungsschnittstelle lässt sie
  zu), mehrere Worker.
- **Scope-Schnitt des Hosts:**
  - kein axe-/Barrierefreiheits-Audit; die Abhängigkeit ist entfernt, die zwei
    gefundenen Korrekturen bleiben;
  - kein Font-Preload; gemessen verzögert er den ersten Paint um bis zu 1,5 s;
  - der Karten-Slot für Erweiterungen und das Durchreichen von `data-*`-Attributen
    waren schon vor dem Schnitt fertig und sind drin.

## Offene Punkte / Todos

1. **SEC-13, heute:** Nach dem 13.10.2026, 16:30 UTC (18:30 Uhr deutscher Zeit), in
   `frontend/pnpm-workspace.yaml` den Block `minimumReleaseAgeExclude` samt Kommentar
   löschen und `cd frontend && pnpm install --frozen-lockfile` ausführen.
2. **WebKit läuft nicht in der CI.** Das Playwright-Image ist 3,5 GB groß. Lokal:
   `make e2e-webkit`.
3. **Coolify braucht Zugriff auf das Repo.** Es ist privat, und Coolify hat nur die
   Quelle „Public GitHub“. Nötig ist die GitHub App oder ein Deploy Key (siehe
   `docs/DEPLOY.md`, Abschnitt Coolify).
4. **Admin-Kontaktbogen:** Solange Fotos ausgewählt sind, wählt ein Klick aus, statt das
   Foto zu öffnen.
5. **Firefox:** Wird ein fokussiertes Element aus einem Sheet entfernt, fällt der Fokus
   auf `body`. Abgefangen ist das nur im Upload-Sheet.
6. **Login-Sperre:** Nach 20 Fehlversuchen in 15 Minuten wird 5 Minuten lang jeder Login
   abgelehnt. Logins direkt vom Server (Loopback) sind ausgenommen, ein Neustart löscht
   die Sperre, eingeloggte Admins arbeiten weiter.
7. **Speichern:** Das Teilen-Menü öffnet sich nur auf iOS. Android lädt herunter und
   bietet zusätzlich einen Knopf „Teilen“.
8. **Fotobox auf Start:** Die Beispielbilder sind statisch.
9. **Alte Worktrees** unter `.worktrees/` können weg.
10. **Reste des alten Layouts:** der Ordner `virtubooth/` im Repo-Root (nur noch
    `__pycache__`) und das `.venv` im Root können gelöscht werden.
11. **Screenshot** `docs/overhaul/design/shots/wave2-gp/02-start-photos-phone.png`
    zeigt einen echten Partynamen und Handle. Solange das Repo privat ist, ist das in
    Ordnung.

## Starten

Lokal (braucht uv, Node 22 und pnpm 11):

```bash
make setup        # uv sync + pnpm install
make build-web    # baut frontend/dist
make dev          # Server auf :8000
```

- `make dev` nutzt die `.env` im Repo-Root (fehlt sie, wird eine mit neuen Secrets
  angelegt) und den Ordner `data/`. Die Datenbank wird beim ersten Start migriert.
- Die Gast-URL mit Token gibt `make dev` aus. Admin: `http://localhost:8000/admin`.
- Mit Hot Reload: zusätzlich `make dev-web` (Vite auf :5173). Alle Aufgaben: `make help`.

Docker und Server:

```bash
docker compose run --rm -T app virtubooth gen-env > .env   # neue Secrets
docker compose up -d --build
```

- Für Coolify gibt es `docker-compose.coolify.yaml`.
- Reverse Proxy, HTTPS (für die Kamera nötig), alle Einstellungen, Backups, Updates und
  Exporte: `docs/DEPLOY.md`.
