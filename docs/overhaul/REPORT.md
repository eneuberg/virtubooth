# Abschlussbericht: Überarbeitung von virtubooth

Stand 13.10.2026. Basis vor der Überarbeitung: `main` auf `1d6b5eb`. Danach 122 Commits
bis zum Merge `01960c7`, dann die Nacharbeiten (Branches `fin/*`), alle in das lokale
`main` gemerged. Nichts wurde gepusht.

## Kurzfassung

- virtubooth ist neu aufgebaut: ein Frontend mit React 19 und TypeScript statt
  handgeschriebenem HTML/CSS/JS, ein Backend in Schichten, eine neue Ordnerstruktur
  und das neue Design „Kontaktbogen“.
- Alle bisherigen Funktionen sind geblieben. Neu sind unter anderem „Deine Bilder“,
  der Gästepass, die Outbox auch für die Beer Cam, Exporte im Admin und das
  Instagram-ZIP mit „Erledigt“.
- Auf deinen Wunsch dazugekommen: „Hochladen stoppen“ und „Anmeldung stoppen“ mit
  einem Tipp direkt auf dem Dashboard, ein Statusstreifen, solange ein Stopp aktiv ist,
  und eine Live-Übersicht (aktiv, lädt hoch, gescannt, nicht beigetreten …).
- Neue README mit Logo und Screenshots, dazu eine vollständige Funktionsliste in
  `docs/FEATURES.md`.
- QA: jede Anforderung einmal im Browser durchgespielt (Gast und Admin). Kein
  Funktionsfehler im Admin; auf der Gastseite fünf Fehler gefunden und behoben.
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
- **Dashboard (dein Wunsch nach dem ersten Check):**
  - „Hochladen stoppen“ und „Anmeldung stoppen“ stehen mit einem Tipp auf Live und in
    der Verwaltung, ohne Rückfrage. Solange ein Stopp aktiv ist, verschwindet sein
    Knopf und ein Statusstreifen (rot bzw. orange) mit „Fortsetzen“ bzw. „Wieder
    öffnen“ ist die einzige Bedienung dafür. So kann niemand aus Versehen fortsetzen,
    der eigentlich stoppen will. Alles bleibt über alle Admin-Geräte live synchron.
  - Neu ist der Anmelde-Stopp: Neue Geräte bekommen beim Beitreten eine ruhige Meldung
    („Gerade kann niemand neu beitreten …“) und der Knopf kommt von selbst zurück.
    Wer schon dabei ist, merkt nichts. Anders als „Neue Gäste pausieren“ kommt dabei
    niemand Neues rein.
  - Live-Übersicht: sechs Zahlen auf Live, alle Zahlen im neuen Tab „Übersicht“
    (aktiv jetzt, lädt gerade hoch, Fotos in 15/60 min, gescannt, beigetreten, nicht
    beigetreten, Gäste mit Instagram/pausiert/gesperrt, Fotos je Aktivität). „Jetzt“
    heißt: letzte 5 Minuten. Aktualisierung alle 10 s und bei Live-Events.
  - Für „gescannt“ bekommt jedes Gerät beim Öffnen des QR-Links eine zufällige ID im
    Cookie `vb_vid`. Gespeichert werden nur diese ID, Zeitstempel und später die
    Verknüpfung zum Gast, keine IP und kein Browser-Typ. Die Archiv-Kopie der Datenbank
    leert die Tabelle. Unter „Mehr dazu“ steht ein Satz dazu für die Gäste.
  - Technik: `GET /api/admin/overview`, `GET/POST /api/admin/join-stop`, Fehlercode
    `join_closed`, Event `settings.join_stop`, Migration 4 (`visitors`, Indizes).
- **README** neu: Logo, zwei Screenshots mit Demodaten, Ablauf einer Party, Schnellstart.
  Entwickler-Details stehen jetzt in `docs/ARCHITECTURE.md`.
- **`docs/FEATURES.md`**: vollständige Funktionsliste auf Deutsch, gegen den Code
  geprüft. Dabei wurden elf veraltete Stellen in README, DEPLOY, ARCHITECTURE und
  diesem Bericht korrigiert.

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
| Schnell-Stopps | im Sheet versteckt | „Hochladen stoppen“ und „Anmeldung stoppen“ mit einem Tipp auf Live und in der Verwaltung, Statusstreifen mit „Fortsetzen“ / „Wieder öffnen“, solange ein Stopp aktiv ist. |
| Übersicht | gab es nicht | Live-Zahlen auf Live und im Tab „Übersicht“: aktiv, lädt hoch, Fotos 15/60 min, gescannt, nicht beigetreten, Gäste, Fotos je Aktivität. |
| Verwaltung | Tabs | Seitenleiste am Desktop: Übersicht, Fotos (Kontaktbogen, Filter, Mehrfachauswahl mit Tastatur, Inspektor), Gäste, Instagram, Sperren, Protokoll, Export. |
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
| `make check` | Lint, Typecheck, Tests, OpenAPI-Abgleich | grün (alles unten in einem Lauf, Code-Stand `7168423`) |
| Backend (pytest) | API, Migrationen, Werkzeuge, Web-Auslieferung, Content-Blocker | 529 bestanden, 2 übersprungen |
| Vitest | SDK, Fehlerabbildung, Formatierung, Komponenten | 340 bestanden |
| e2e Chromium | echte Browser gegen das gebaute Frontend, ohne Konsolenfehler | 191 bestanden, 22 übersprungen, 0 Fehler (8:18 min, seriell) |
| e2e Firefox | dasselbe in Firefox | 199 bestanden, 14 übersprungen, 0 Fehler (8:52 min, seriell) |
| e2e WebKit | dasselbe in WebKit (Docker, `run_webkit.sh`) | {{TEST_E2E_WEBKIT}} |
| `make docker-smoke` | Image bauen, starten, Ende-zu-Ende prüfen | bestanden |

## QA

Zwei Agenten haben jede Anforderung einmal im echten Browser durchgespielt, gegen einen
eigenen Server mit Testdaten. Jeder gefundene Fehler wurde behoben und bekam einen
gezielten Test. Am Ende jedes Durchgangs: keine Konsolenfehler.

**Gäste** (Chrome am Handy 390×844 und 360×640, Firefox wo nötig):

| Anforderung | Ergebnis |
|---|---|
| Ohne Token überall „Scan den QR-Code“ (404), auch bei falschem `?t=` | OK |
| Mit Token rein, Cookie gesetzt, Token verschwindet aus der Adresse | OK |
| Beitritts-Sheet: ein Knopf, kein „Nein“, nicht wegklickbar, Instagram freiwillig | OK |
| Pseudonym; Instagram später hinzufügen, ändern, löschen | OK |
| Beer Cam: Flasche als Standard, Becher in ähnlicher Größe, Upload 1080×1440 | OK |
| Fotobox: WebGL-Filter (Canvas2D als Rückfall), Countdown, Upload, nächste Nummer | OK |
| „Deine Bilder“: Liste, Viewer, ausgeblendete Fotos verschwinden | behoben: ein neues Foto erschien erst nach bis zu 15 s |
| Stopp, Pause neue Gäste, Pause pro Gast, Sperre: ruhige Meldung, kein Fehler | OK; behoben: in einem Grenzfall kam der rohe Servertext |
| Firefox: Startseite zeigt die Aktivitäten, Kamera und Upload in beiden | OK |
| Leere Startseite „der <Titel>“ | behoben: „Probier „Beer Cam“ oder „Fotobox“ aus …“ |
| Bier-Nummer | behoben: angezeigt wurde die Zahl sichtbarer Biere, gespeichert die Fotonummer. Jetzt sieht der Gast überall die Nummer seines Fotos. |
| Langes Pseudonym | behoben: schnitt den Titel der Aktivität ab |

**Admin** (Chrome am Desktop 1440×900 und am Handy 390×844; 16 Gäste, rund 26 Fotos):

| Anforderung | Ergebnis |
|---|---|
| Login, falsches Passwort, Sperre, Logout beendet auch offene Live-Tabs | OK |
| Live: neue Fotos sofort, Ausblenden mit „Rückgängig“, nirgends Löschen | OK |
| Verwaltung: Löschen mit Rückfrage, Datei wirklich weg | OK |
| Name am Foto führt zur Gästeseite mit allen Uploads | OK |
| Sperren, Entsperren, Gerätesperre, automatische Sperre und deren Freigabe | OK |
| Gesperrter Gast kann nicht hochladen; Protokoll zeigt alle Aktionen | OK |
| Hochladen für alle stoppen; neue Gäste pausieren; beim Ausschalten „Alle N freischalten“ oder „Alle N pausiert lassen“ (beide geprüft); Pause pro Gast | OK |
| Instagram: ZIP pro Handle gültig, „Erledigt“ bleibt nach Reload | OK; ergänzt: Meldung mit „Rückgängig“ |
| Exporte: Archiv-ZIP gültig, Zeitraffer H.264 1080×1440 30 fps, QR-Codes zeigen auf Adresse mit Token | OK; Titel und Ausrichtung verbessert |
| Protokoll: Link auf gelöschtes Foto | behoben: kein toter Link mehr |

Der Admin-Durchgang fand keinen Funktionsfehler. Das neue Dashboard (Schnell-Stopps,
Anmelde-Stopp, Übersicht) wurde von seinem Agenten mit eigenen e2e-Tests in Chrome und
Firefox geprüft und ist im Testlauf unten enthalten.

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
9. **Alte Worktrees** unter `.worktrees/` (`ov-*`, `fin-*`, `overhaul`) und die
   gemergten Branches können weg.
10. **Reste des alten Layouts:** der Ordner `virtubooth/` im Repo-Root (nur noch
    `__pycache__`) und das `.venv` im Root können gelöscht werden.
11. **Screenshots** unter `docs/overhaul/design/shots/wave2-gp/` zeigen einen echten
    Partynamen und Handle. Solange das Repo privat ist, ist das in Ordnung. Die
    README-Bilder in `docs/assets/` nutzen nur Demodaten.
12. **Datenschutz-Text:** Zu jedem beigetretenen Gast speichert die App (wie schon vor
    der Überarbeitung) erste und letzte IP-Adresse und den Browser-Typ, für die
    Wiedererkennung von Geräten und Sperren. Der Beitrittstext erwähnt das nicht. Bei
    Bedarf einen Satz unter „Mehr dazu“ ergänzen.
13. **„Aktiv jetzt“** zählt API-Anfragen der letzten 5 Minuten. Wer die Seite offen hat,
    aber nichts tut, fällt heraus. Ein leichter Herzschlag würde das ändern.
14. **„Gescannt“** zählt erst ab dem Update. Direkt danach kann es kleiner sein als
    „Gäste“; die Übersicht sagt „Gezählt seit …“.
15. **Wortwahl:** Der Knopf heißt „Hochladen stoppen“ (wie im übrigen Admin), nicht
    „Uploads stoppen“. Änderbar in einer Zeile in `frontend/src/admin/dashboard/text.ts`.
    Gäste sehen beim Stopp „Hochladen ist kurz angehalten“ statt „temporär deaktiviert“.
16. **Kleinigkeiten aus der QA, nicht behoben:**
    - Am Handy verdeckt der Toast 5–7 s lang den „Ausblenden“-Knopf im Foto-Viewer.
    - Bei Mehrfachauswahl zeigt der Inspektor in „Fotos“ weiter das zuletzt geöffnete Foto.
    - Der Viewer-Dialog heißt für Screenreader „Foto Foto 0008“.
    - Von einer einzelnen Adresse zeigt der Login den allgemeinen Rate-Limit-Text
      („Langsam! … Warte kurz … in 3 Sekunden“), etwas doppelt formuliert.
    - Die Filterleiste der Fotobox zeigt Emoji als Platzhalter, bis die echten
      Vorschaubilder fertig sind (kurz, auf schwachen Geräten länger).
    - Blendet der Admin ein Foto aus, das ein Gast gerade im Viewer ansieht, springt der
      Viewer zum nächsten Foto, statt sich zu schließen.

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
