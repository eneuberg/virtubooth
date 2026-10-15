# Abschlussbericht: Überarbeitung von virtubooth

Stand 13.10.2026, Nachtrag 14.10.2026. Basis vor der Überarbeitung: `main` auf `1d6b5eb`.
Danach 122 Commits bis zum Merge `01960c7`, dann die Nacharbeiten (Branches `fin/*`),
alle in das lokale `main` gemerged. Am 13./14.10. kamen QR-Codes, Einstellungen, Plakate,
Tracking und die Live-Wall dazu (siehe [Nachtrag](#nachtrag-131410-qr-codes-einstellungen-plakate-tracking-live-wall)).
Nichts wurde gepusht.

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
- Tests laufen parallel: ein Browser-Durchlauf dauert 2–2,5 statt 8–10 Minuten.
  `make check` (Alltag) braucht 2:24 min, `make check-all` (alles inkl. Firefox,
  WebKit, Docker) 7:26 min.
- Sicherheitsreview: 0 kritisch, 0 hoch, 1 mittel, 5 niedrig, 9 Info. Der mittlere
  und alle niedrigen Befunde sind behoben.
- SEC-13 ist erledigt: Die Ausnahmen vom Mindestalter der Pakete sind am Abend des
  13.10. raus.
- Nachtrag 13./14.10.: mehrere QR-Codes mit Statistik pro Code, Einstellungen
  (Eventname, Admin-Passwort, Fotobox-Filter), Plakate mit eigener Vorlage, Online-Zeit
  per Herzschlag und die Live-Wall mit Fotoanalyse und 19 Kategorien.
- Sicherheitsreview 2: 0 kritisch, 0 hoch, 1 mittel, 6 niedrig, 7 Info; der mittlere
  und alle niedrigen Befunde sind behoben.

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
- **Schnellere Tests** (Branch `fin/test-speed`, App-Code unverändert):
  - Die Browser-Tests laufen mit pytest-xdist in 4 Prozessen (`E2E_WORKERS=4`), jeder
    Test hat weiter seinen eigenen Server, Datenordner und Port.
  - Playwrights Warten prüft alle 100 ms statt alle 500 ms (`tests/e2e/fastpoll.py`,
    abschaltbar mit `VB_E2E_SLOW_POLL=1`). Allein das spart etwa ein Sechstel.
  - Einige Tests warten jetzt auf den echten Zustand, statt ihm hinterherzulaufen
    (keine Wiederholungen, keine Sonderbehandlung). Firefox bekommt einen Workaround
    für einen Playwright-Fehler, bei dem `goto()` 30 s hing.
  - WebKit: die Software-Grafik (llvmpipe) auf 4 Threads begrenzt, sonst bremsten sich
    die parallelen Kamera-Tests gegenseitig aus.
  - `make check` ist jetzt der schnelle Alltags-Check (OpenAPI-Abgleich, dann Lint,
    Typecheck und Tests nebeneinander, dann Chromium). `make check-all` macht alles.
    Neu: `make e2e-changed` (nur geänderte e2e-Tests). `frontend/dist` wird nur neu
    gebaut, wenn sich in `frontend/` etwas geändert hat. Die CI nutzt ebenfalls 4 Prozesse.

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
Platzprüfung und Aufräumen). SEC-13 ist am Abend erledigt worden (siehe Todos). Details:
`docs/overhaul/SECURITY_REVIEW.md`.

## Tests

Endstand: App-Code wie `7168423`, Test-Harness aus `fin/test-speed`. `make check-all`
war darauf grün; danach lief `make check` noch einmal auf dem fertigen `main`: grün in
2:34 min.

| Lauf | Was | Ergebnis |
|---|---|---|
| Lint, Typecheck, OpenAPI-Abgleich | ruff, mypy --strict, ESLint, tsc, Schema-Drift | sauber |
| Backend (pytest) | API, Migrationen, Werkzeuge, Web-Auslieferung, Content-Blocker | 529 bestanden, 2 übersprungen (14 s, vorher 44 s) |
| Vitest | SDK, Fehlerabbildung, Formatierung, Komponenten | 340 bestanden |
| e2e Chromium | echte Browser gegen das gebaute Frontend, ohne Konsolenfehler | 191 bestanden, 22 übersprungen, 0 Fehler, 3 Läufe (2:02 min, vorher 8:19) |
| e2e Firefox | dasselbe in Firefox | 199 bestanden, 14 übersprungen, 0 Fehler, 2 Läufe (2:11 min, vorher 8:52) |
| e2e WebKit | dasselbe in WebKit (Docker, `run_webkit.sh`) | 188 bestanden, 25 übersprungen, 0 Fehler, 3 Läufe (2:36–2:40 min inkl. Container-Start, vorher 9:55 mit 1 Wackler) |
| `make docker-smoke` | Image bauen, starten, Ende-zu-Ende prüfen | bestanden (9–15 s mit Build-Cache) |

Spitzen-RAM der Testprozesse mit 4 Workern: Chromium 3,2 GB, Firefox 3,8 GB, WebKit-Container
4,1 GB. Auf schwächeren Rechnern: `E2E_WORKERS=2` (oder `0` für einen Prozess, z. B. mit `--pdb`).

| Befehl | Was | Dauer |
|---|---|---|
| `make check` | OpenAPI-Abgleich, Lint + Typecheck + Tests nebeneinander, e2e Chromium | 2:24 min |
| `make check-all` | `check` + Firefox + WebKit + Docker-Smoke | 7:26 min |
| `make test` | pytest + Vitest | 17 s |
| `make e2e-changed` | nur die seit `main` geänderten e2e-Dateien (alle, wenn ein Helfer geändert wurde) | je nach Umfang |
| `make e2e E2E_ARGS="tests/e2e/admin -k live"` | gezielt einzelne Tests | je nach Umfang |

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

1. **SEC-13: erledigt** am 13.10.2026 um 18:53 UTC. Der Block `minimumReleaseAgeExclude`
   ist aus `frontend/pnpm-workspace.yaml` entfernt. `pnpm install --frozen-lockfile` lief
   sauber durch: Lockfile unverändert, Supply-Chain-Prüfung bestanden.
2. **WebKit läuft nicht in der CI.** Das Playwright-Image ist 3,5 GB groß. Lokal:
   `make e2e-webkit` oder alles mit `make check-all`.
3. **Coolify und Repo-Zugriff:** Das Repo ist inzwischen öffentlich (Stand 13.10. abends),
   damit reicht in Coolify die Quelle „Public GitHub“. Wird es wieder privat, braucht
   Coolify die GitHub App oder einen Deploy Key (siehe `docs/DEPLOY.md`, Abschnitt Coolify).
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
11. **Vor einem Push, weil das Repo jetzt öffentlich ist:** Die Screenshots unter
    `docs/overhaul/design/shots/wave2-gp/` (20 Bilder) zeigen einen echten Partynamen und
    Handle. Sie stecken in der lokalen Git-Historie, ein Löschen per Commit reicht also
    nicht. Entweder die Historie vor dem ersten Push umschreiben (z. B. `git filter-repo`,
    geht, solange nichts davon gepusht ist) oder das Repo wieder privat stellen. Die
    README-Bilder in `docs/assets/` nutzen nur Demodaten.
12. **Datenschutz-Text:** Zu jedem beigetretenen Gast speichert die App (wie schon vor
    der Überarbeitung) erste und letzte IP-Adresse und den Browser-Typ, für die
    Wiedererkennung von Geräten und Sperren. Der Beitrittstext erwähnt das nicht. Bei
    Bedarf einen Satz unter „Mehr dazu“ ergänzen.
13. ~~**„Aktiv jetzt“** zählt API-Anfragen der letzten 5 Minuten. Wer die Seite offen hat,
    aber nichts tut, fällt heraus. Ein leichter Herzschlag würde das ändern.~~
    Erledigt: Die Gastseite meldet sich jede Minute, solange sie sichtbar ist (siehe
    Nachtrag, Tracking).
14. **„Gescannt“** zählt erst ab dem Update. Direkt danach kann es kleiner sein als
    „Gäste“; die Übersicht sagt „Gezählt seit …“.
15. **Wortwahl:** Der Knopf heißt „Hochladen stoppen“ (wie im übrigen Admin), nicht
    „Uploads stoppen“. Änderbar in einer Zeile in `frontend/src/admin/dashboard/text.ts`.
    Gäste sehen beim Stopp „Hochladen ist kurz angehalten“ statt „temporär deaktiviert“.
16. **Kleinigkeiten aus der QA:** am 14.10. alle behoben (Branch `polish/admin`).
    - ~~Am Handy verdeckt der Toast 5–7 s lang den „Ausblenden“-Knopf im Foto-Viewer.~~
      Behoben, siehe Punkt 17.
    - ~~Bei Mehrfachauswahl zeigt der Inspektor in „Fotos“ weiter das zuletzt geöffnete
      Foto.~~ Er zeigt jetzt die Auswahl.
    - ~~Der Viewer-Dialog heißt für Screenreader „Foto Foto 0008“.~~ Jetzt „Foto 0008“.
    - ~~Von einer einzelnen Adresse zeigt der Login den allgemeinen Rate-Limit-Text,
      etwas doppelt formuliert.~~ Jetzt ein Satz: „Zu viele Versuche hintereinander.
      Versuch es in 3 Sekunden nochmal.“
    - ~~Die Filterleiste der Fotobox zeigt Emoji als Platzhalter, bis die echten
      Vorschaubilder fertig sind.~~ Jetzt ein ruhiger Platzhalter; Emoji nur, wenn ein
      Vorschaubild fehlschlägt.
    - ~~Blendet der Admin ein Foto aus, das ein Gast gerade im Viewer ansieht, springt der
      Viewer zum nächsten Foto.~~ Er schließt sich jetzt mit „Dieses Bild ist nicht mehr
      zu sehen.“ (Rest siehe Nachtrag, offene Punkte).
17. **Gefunden beim Beschleunigen der Tests, danach behoben:**
    - **Firefox/Safari, behoben (`fin/preload-nav`):** Eine echte Seitennavigation
      (Adresszeile, externer Link), die startete, während noch ein Seitenmodul lud,
      wurde durch ein Neuladen der alten Seite abgebrochen. Jetzt lädt
      `frontend/src/lib/boot.ts` nur noch neu, wenn der Server wirklich einen neuen Build
      ausliefert (das HTML nennt ein anderes Einstiegsskript). Getestet in allen drei
      Browsern (ohne Fix 5/5 rot, mit Fix je 10/10 grün).
    - **Toast am Handy, behoben (`fin/phone-toast`):** Der Toast rutscht jetzt über
      markierte Aktionsflächen (Viewer-Leiste, Bestätigungsdialog, Auswahlleiste,
      Kamera-Auslöser, Filterleiste), statt sie zu verdecken; „Rückgängig“ bleibt
      erreichbar. Betroffen waren Admin und Gäste. ~~Offen: In scrollbaren Rastern kann er
      die unterste Kachelreihe noch kurz verdecken.~~ Behoben: Solange ein Toast steht,
      bekommen scrollende Seiten unten Platz.
    - `test_upload_publishes_event` dauert 5 s: sein Event-Loop wird nie geweckt, weil
      der Bus an den Loop des TestClients gebunden wird; er endet erst über den eigenen
      Timeout. Nur ein Testproblem.

## Nachtrag 13./14.10.: QR-Codes, Einstellungen, Plakate, Tracking, Live-Wall

Nach dem Bericht (`f59399d`) kamen fünf Funktionsbranches (`feat/*`), die Live-Wall in
vier Teilen (`wall/*`), Sicherheitsreview 2 (`sec/review`), ein Docker-Fix und eine
Polierrunde (`polish/*`) dazu, alle in das lokale `main` gemerged. Funktionen im Detail:
`docs/FEATURES.md`.

### Was gebaut wurde

- **QR-Codes** (Tab „QR-Codes“):
  - Beliebig viele Codes, jeder mit fester Nummer und Tiername („Gorilla 2“), Ziel
    (Start oder eine Aktivität) und Notiz. Code 1 entsteht aus `VB_PARTY_TOKEN`; alte
    Gäste und Scans zählen für ihn (Migration 5).
  - Gelöschte Codes bleiben grau in der Liste (Grabstein), ihr Token gilt nicht mehr.
    „Token ändern…“ macht einen gedruckten Code ungültig; ein gedruckter Code lässt sich
    per Link übernehmen. Kein Token wird zweimal vergeben.
  - Zahlen pro Code: gescannt, Personen, beigetreten, Fotos, aktiv jetzt, Online-Zeit;
    Gästeliste nach Code filterbar.
  - Exporte pro Code: QR als PNG, QR groß (PDF), Plakat (PDF), im Sheet und im
    Zeilenmenü.
- **Einstellungen** (Zahnrad bzw. unten in der Seitenleiste): Eventname (überall, auch
  auf Plakaten und im Archiv), Admin-Passwort ändern (scrypt, meldet alle anderen
  Geräte ab, `virtubooth reset-admin-password` für den Notfall), Fotobox-Filter einzeln
  an und aus.
- **Plakate** (Tab „Plakat“): PDF-Vorlage hochladen, Seite wählen, QR-Feld mit Maus,
  Finger oder Tastatur platzieren, Probedruck. Ohne Vorlage ein Standard-Plakat im
  Kontaktbogen-Stil. Alles entsteht im Browser des Admins.
- **Tracking:** Die Gastseite meldet sich jede Minute, solange sie sichtbar ist
  (`POST /api/here`, Migration 6). Daraus „Aktiv jetzt“, die Online-Zeit pro Gast
  („1 h 12 min in 3 Besuchen“, „gerade online“), die Spalte „Online“ und eine Statistik
  pro Gast (Fotos je Aktivität, erstes und letztes Foto, QR-Code des Beitritts). Auch in
  `users.csv`.
- **Live-Wall** (`/livewall` auf dem Fernseher, Einstellungen im Tab „Live-Wall“):
  - Zugang mit eigenem Passwort (30 Tage Cookie nur für `/livewall`), „Alle Wände
    abmelden“, Zahl der offenen Wände.
  - Drei Modi im Wechsel: Einzelbild, Galerie (endlose Fotowand), Kategorien.
  - Sieben Auswahlverfahren fürs Einzelbild (u. a. „Fair: jeder Gast reihum“, „Selten
    gezeigte zuerst“, „Neue Fotos sofort, sonst gemischt“ als Standard).
  - Elf Übergänge plus „Zufall“, WebGL mit Überblenden als Rückfall.
  - Animierter Hintergrund (Farbblasen, Polarlicht, Disco-Gitter, Konfetti-Regen oder
    ruhig) mit drei frei wählbaren Farben, 30 oder 60 fps.
  - Fernseher: Vollbild-Knopf (auch mit `webkit`-Präfix für alte TV-Browser), hält den
    Bildschirm wach, verbindet sich selbst neu und holt Verpasstes nach.
  - Neue Fotos erst nach einer Verzögerung (Standard 20 s), damit der Host vorher
    ausblenden kann; Ausblenden, Löschen und Sperren wirken sofort auf jeder Wand.
  - QR-Code, Eventname und Fotozähler in einer wählbaren Ecke.
  - **Fotoanalyse:** ein eigener Prozess (nice 10, ein Foto nach dem anderen, Neustart
    nach 200 Fotos oder 900 MB) wertet jedes Foto aus. Immer Bildwerte (Pillow); mit
    dem `ml`-Extra MediaPipe- und ONNX-Modelle für Gesichter, Ausdruck, Gesten, Personen
    und Gläser, Brillen und Hüte, optional Alter (FairFace). Gespeichert werden nur
    Zahlen und Rahmen, nichts, was eine Person wiedererkennt. Ausgelegt für einen
    Raspberry Pi 5.
  - **19 Kategorien** („Volles Haus“, „Grinsekatzen“, „Prost!“, „Dauerauslöser“ …),
    höchstens ein Gewinnerfoto pro Gast und Kategorie, einzeln abschaltbar.
  - Gäste können die Auswertung abschalten („Meine Fotos nicht automatisch auswerten“).
  - Im Admin: Analyse-Karte (Status, Herzschlag des Prozesses mit verarbeiteten Fotos,
    Speicher und Ladefehlern, Analysen an/aus, neu analysieren), die ersten drei jeder
    Kategorie, Analyse mit Rahmen im Foto-Inspektor.
  - Kommandozeile: `virtubooth wall models fetch`, `… status`, `… bench`. Docker-Image
    mit Analyse: `VB_ML=1`, Modelle eingebacken mit `VB_BAKE_MODELS=1`.
- **Polierrunde** (`polish/backend`, `polish/admin`, `polish/screen`):
  - Wall: Instagram-Änderungen live, Neuabgleich nach verpassten Ereignissen,
    Limits pro Wand, Modi blenden ineinander, mitlaufende Altersangaben, das erste Foto
    bleibt stehen, Speichertest (Heap und DOM bleiben begrenzt).
  - Admin: gleichmäßige Spalten, Speichern-Leiste in einer Zeile, Rückfrage beim
    Verlassen mit ungespeicherten Änderungen, Farbfeld mit Vorschau, QR-Zeilenmenü,
    Plakat-Vorschau mit dem gewählten Code.
  - Die QA-Reste aus Punkt 16 und der Toast über der letzten Kachelreihe (Punkt 17)
    sind behoben.
  - `make docker-smoke` erklärt einen nicht erreichbaren Port; `DOCKER_BUILD_FLAGS`
    für den Build.

### Sicherheitsreview 2

Gleiche Methode wie Review 1, Umfang: alles seit `0ff9bd4` (Passwortänderung, QR-Codes,
Live-Wall, Plakat-Upload, Herzschlag, Analyse-Prozess, CSP). **0 kritisch, 0 hoch,
1 mittel, 6 niedrig, 7 Info.** Alle mittleren und niedrigen Befunde sind behoben, je mit
Test:

- **WALL-01 (mittel):** Das Wall-Login hatte nur ein Limit pro Adresse; 1000 Versuche in
  84 s gingen durch. Jetzt sperrt es nach 20 Fehlversuchen in 15 Minuten, egal von wo,
  5 Minuten lang für alle; angemeldete Wände laufen weiter.
- **ARCH-01:** Die Datenbank-Kopie im Archiv enthielt die Passwort-Hashes (Admin, Wall).
  Jetzt geleert.
- **QR-01:** Falsche Tokens von einem Gerät konnten neue Gäste im selben Netz aussperren.
  Jetzt wird jedes gut geformte Token geprüft, nur falsche über dem Limit werden
  verzögert.
- **WALL-02:** Die 1280-px-Kopie eines gelöschten Fotos konnte liegen bleiben. Jetzt geht
  sie mit dem Foto, der Cache wird aufgeräumt.
- **WALL-03:** Keine Grenze für Event-Streams einer Wand. Jetzt höchstens 4 pro Cookie,
  dazu Abruf-Limits.
- **HERE-01:** Der Herzschlag schrieb bei jeder Anfrage. Jetzt höchstens alle 20 s.
- **ANA-01:** Jedes Umschalten des Opt-outs stellte alle Fotos des Gasts neu an. Jetzt
  höchstens alle 5 Minuten (Löschen der Auswertung weiter sofort).

Info R2-I1 bis R2-I7 sind Hinweise oder bewusst akzeptiert, z. B.: Gelöschte Codes
sperren beigetretene Gäste nicht aus (Ausweg: `VB_SECRET_KEY` wechseln), der QR-Code auf
der Wand enthält ein gültiges Token. Details: `docs/overhaul/SECURITY_REVIEW.md`,
Abschnitt „Review 2“.

### ML-Benchmark

Auf dem Entwicklungsrechner (i7-13650HX), mit den Einstellungen des Prozesses (nice 10,
3 Threads), Fotos mit 1280 px:

| | pro Foto | Fotos/min | Spitzen-RAM |
|---|---|---|---|
| ohne Alter, kalt (erstes Foto) | 1,4 s | | |
| ohne Alter, warm | 0,44 s | 151 | 593 MB |
| mit Alter (FairFace) | 0,79 s | 98 | 745 MB |

- Modelle: 144 MB, mit Alter 231 MB. Das `ml`-Extra braucht etwa 485 MB; das Docker-Image
  mit Analyse ist 1,85 GB statt 903 MB.
- Schätzung für einen Raspberry Pi 5 (ohne Alter): 1,2–1,8 s pro Foto, etwa 600 MB.

### Tests

Endlauf am 14.10. auf `fin/wrapup` (Stand von `main` plus die Herzschlag-Felder der
Analyse-Karte), je einmal:

| Lauf | Ergebnis |
|---|---|
| `make check`: OpenAPI-Abgleich, Lint, Typecheck | sauber |
| Backend (pytest, 4 Prozesse) | 926 bestanden, 8 übersprungen (44 s) |
| Vitest | 577 bestanden in 67 Dateien |
| e2e Chromium (4 Prozesse) | 242 bestanden, 23 übersprungen, 0 Fehler (3:45 min) |
| e2e Firefox (`make e2e-firefox`) | 249 bestanden, 16 übersprungen, 0 Fehler (3:41 min) |
| e2e WebKit, nur Live-Wall und Admin-Live-Wall | 20 bestanden, 2 übersprungen, 0 Fehler (48 s inkl. Container) |
| `make docker-smoke` | nicht gelaufen (siehe offene Punkte) |

Kein Wackler.

### Offene Punkte

1. **Docker-Smoke lokal blockiert:** Die IVPN-Firewall dieses Rechners lässt keinen
   Verkehr zu Dockers Bridge-Netzen durch. Abhilfe (Entscheidung des Hosts):
   `ivpn firewall -exceptions '172.16.0.0/12'` oder `-lan_allow`. Der ECONNRESET von
   `pnpm install` im `docker build` hat dieselbe Ursache. Das Image wurde für diesen
   Nachtrag nicht gebaut.
2. **Vor einem Push** (das Repo ist öffentlich): `docs/overhaul/design/shots/wave2-gp/`
   mit echtem Partynamen und Handle steckt in der lokalen Historie. Historie umschreiben
   oder das Repo privat stellen (siehe Punkt 11 oben).
3. **Gast-Viewer beim Ausblenden:** Er schließt sich erst beim nächsten Abgleich, also
   bis zu 60 s später.
4. **Zurück-Taste des Browsers:** Die Rückfrage bei ungespeicherten Live-Wall-Einstellungen
   greift bei Links in der App, bei Neuladen und beim Schließen, nicht bei der
   Zurück-Taste.
5. **Schwellen der Analyse** (z. B. „ab 50 %“ beim Ausdruck, Schärfe für den
   Action-Shot) sollten an echten Partyfotos nachjustiert werden.
6. **Kategorien-Ansicht:** Mit einer hohen QR-Ecke unten wird das Layout eng.
7. **Alte Analysen** zeigen rohe Filter-IDs statt Namen, bis sie neu analysiert werden.

## Nachtrag 15./16.10.: Nachtrunde (Fotoanalyse, Kategorien, externe KI, Admin, Gäste)

Die Wünsche des Hosts vom 15.10. (`.worktrees/_plans/REQUIREMENTS-2026-10-15.md`), in
einer Nacht gebaut, während der Host schlief. Erst vier kleine Branches direkt in
`main` (Weißer Kasten auf der Wall, neue Fotobox-Filter, Sicherheitsreview 3, CI),
dann die Schema-Migration 11 auf `main`, dann vier Funktionsbranches parallel (`night/d1-data`,
`night/d2-llm`, `night/ui2-admin`, `night/ui1-ml`), zusammengeführt und verdrahtet in
`night/int2`. Das neue Aussehen (`night/identity`) ist ein eigener Branch zur Ansicht und
nicht gemerged. Funktionen im Detail: `docs/FEATURES.md`.

### Was gebaut wurde

- **Weißer Kasten auf der Live-Wall:** kein WebGL-Rest, sondern eine von einer
  Browser-Erweiterung (Bitwarden) eingeblendete Leiste; die Wall blendet solche Leisten
  aus (`night/wall-whitebox`).
- **Fotobox:** vier neue Filter: „Wärmebild“, „Disco“, „Kaleidoskop“, „Neonlinien“.
- **Fotoanalyse eingefroren:** Jedes Foto wird einmal ausgewertet; Werte, Rahmen und die
  neue **Objektliste** (Name, Sicherheit, Rahmen, Quelle) ändern sich danach nie mehr
  (Datenbank-Trigger). „Neu analysieren“ und die automatische Neu-Analyse nach Updates
  sind weg. Dazukommen kann nur etwas: Objekte der externen KI werden angehängt.
- **Detektor:** EfficientDet-Lite2 bleibt, jetzt mit allen 80 COCO-Klassen (vorher eine
  Auswahl) und deutschen Namen, einstellbar („Mindest-Sicherheit“, „Höchstens
  Objekte“). Begründung unten.
- **Kategorien als Regeln:** Bedingungen auf jedem Analysewert, auf der Objektliste und auf
  den Werten der Eigenschaften, Auswahl Top/Bottom X, Titel, Zeile, Emoji, an/aus,
  anlegen, löschen, Reihenfolge, Vorschau der aktuellen Gewinner. Die 19 bisherigen
  Kategorien sind Vorlagen mit denselben Gewinnern (Golden-Test gegen die alte
  Berechnung), dazu „Das coolste Objekt“ mit Urteil der KI (aus).
- **ML-Pipeline** (neuer Tab): Analysen mit Beschreibung, Größe, Einstellungen und
  Zahlen, Warteschlange, Testbild (ganze Pipeline oder einzelne Analysen, ohne
  Speichern), Einstellungen der externen KI, Eigenschaften, Budget mit Verbrauch.
- **Externe KI (optional, aus):** Anthropic (offizielles SDK; Standard Claude Haiku 5.5,
  wählbar Sonnet und Opus 5.5) oder Mistral AI (EU). Erkennung beim Hochladen
  (verkleinertes Foto), Abfrage der Eigenschaften alle 1–60 Minuten (nur Text), Urteil
  pro Kategorie unter dem Gewinner auf der Wall. API-Schlüssel nur in der ML-Pipeline,
  verschlüsselt gespeichert, nie wieder angezeigt, nie in Exporten oder Logs. Budget pro
  Party und Tag in USD und/oder Aufrufen; am Limit stoppt alles.
- **Gäste:** Anzeigename (Standard: Instagram-Name, sonst Zufallsname; geprüft gegen
  Steuerzeichen, Doppelgänger und „Admin“ & Co.), festes „@“ im Instagram-Feld,
  „Keine Weitergabe an externe KI“ beim Beitritt und im Du-Sheet, eigene Fotos löschen.
  „Meine Fotos nicht automatisch auswerten“ schaltet jetzt nur noch um (siehe unten).
- **Admin:** „Allgemeines“ (Eventname, Admin-Passwort, öffentliche Adresse) und
  „Fotobox“ (Filter) als eigene Tabs; der QR-Bogen ist aus „Export“ verschwunden.
  **Öffentliche Adresse** mit automatischer Prüfung (`/healthz` mit signierter Antwort,
  so dass nur dieser Server besteht); der Tab QR-Codes warnt, solange sie nicht geprüft
  oder nicht erreichbar ist.
- **Sicherheitsreview 3 (PSA)** und **Sicherheitsdurchgang 2** über den Schlüssel- und
  KI-Pfad, siehe unten.

### Lasttest der Warteschlange

20 Gäste laden je 3 Fotos gleichzeitig hoch (`virtubooth wall burst`, echter
Analyse-Prozess, x86-Laptop):

| Lauf | Upload-p95 ohne → mit Analyse | höchstens in Arbeit | Warteschlange leer nach |
|---|---|---|---|
| nur Bildwerte | 266 → 279 ms | 1 Foto | 2,3 s |
| volle ML-Pipeline | 301 → 286 ms | 1 Foto | 9,2 s |
| volle ML, 4 Kerne, 20 × 10 Fotos | 503 → 326 ms | 1 Foto | 24,8 s |

Uploads werden durch die Analyse nicht langsamer, die Analyse arbeitet streng ein Foto
nach dem anderen (neueste zuerst) und holt den Rückstand danach auf; jedes Foto genau
einmal. Auf einem Pi 5 (geschätzt 1,5 s pro Foto) wären 60 Fotos nach etwa 1,5 Minuten
durch. Gemessen nur auf x86; auf dem Pi bitte `virtubooth wall burst` laufen lassen.

### Entscheidungen, die der Host vielleicht anders erwartet

- **Detektor mit mehr Klassen abgelehnt (Lizenz):** D-FINE-S mit Objects365 (365
  Klassen, auf dem Pi 5 etwa 0,9–1,4 s) wäre technisch der beste. Objects365 ist laut
  eigener Seite „nur für akademische Zwecke“, und das D-FINE-README warnt selbst davor;
  das widerspricht „keine Nicht-kommerziell-Lizenzen“. Die saubere Alternative (Open
  Images, 600 Klassen) gibt es nicht als ONNX und ist schlechter. Darum EfficientDet-Lite2
  mit allen 80 Klassen. Für eine private Party wäre D-FINE vertretbar; der Umstieg ist in
  `night/d1/DETECTOR.md` beschrieben (eine Modelldatei, ein Decoder, eine Namensliste).
- **Externer Dienst in der EU:** Mistral AI ist eingebaut (EU-gehostet, ein Schlüssel wie
  bei Anthropic). Azure, Google und AWS in EU-Regionen wären auch möglich, brauchen aber
  Cloud-Konto, IAM und Freischaltungen: zu viel für einen Party-Host. Mistrals Preise
  stammen aus Vergleichsseiten (die offizielle Seite nannte keine), Rahmen sind dort
  ungenauer, getestet nur gegen einen nachgebauten Server. Erster echter Versuch: Testbild
  mit „Auch an … schicken“.
- **N3 Absturz-Wiederholung:** „Einmal analysieren“ heißt: einmal erfolgreich. Stürzt
  der Analyse-Prozess mitten im Foto ab, wird es bis zu dreimal versucht, bevor es als
  fehlgeschlagen gilt.
- **N4 Analyse-Opt-out:** Umschalten löscht nichts mehr und stellt nichts neu an. Solange
  der Schalter an ist, fallen alle Fotos des Gasts aus allen Kategorien, Abfragen,
  Urteilen und der externen Erkennung; schon Gefundenes bleibt gespeichert und ist für
  den Admin mit „Gast möchte keine Auswertung“ markiert. Wer die Fotos wirklich weg haben
  will, löscht sie (Gast oder Admin).
- **N7 Eigenschaften:** wie gewünscht nur archivieren, nie löschen (sonst hängen Regeln
  und alte Urteile in der Luft); Name und Prompt sind unveränderlich, archivierte lassen
  sich zurückholen.
- **N12 Geld in USD:** Budgets und Kosten in US-Dollar, weil Anthropic in USD abrechnet.
  Die Kosten sind Schätzungen aus einer Preistabelle im Code.
- **N14 CSRF unverändert:** Die öffentliche Adresse gilt für QR-Codes, Plakate und die
  Wall, nicht für die CSRF-Prüfung und Cookies; die bleiben bei `VB_PUBLIC_BASE_URL`
  bzw. `VB_ALLOWED_ORIGINS`. Eine falsch eingetippte Adresse kann so niemanden aussperren.
- **N16 QR-Bogen:** aus dem Admin entfernt, die Kommandozeile
  (`python -m virtubooth.tools.qr`) bleibt.
- **Name des Schlüssels:** Review 3 empfahl einen Einstellungs-Schlüssel auf `.secret`;
  der Plan legte `x.llm.key` fest. Das Archiv löscht jetzt beides.
- **Gäste gegenüber der KI:** Die Abfrage nennt Gäste so wie die Wall
  (Anzeigename, „@Instagram“ nur, wenn die Wall Instagram-Namen zeigt, sonst
  Zufallsname), weil das Urteil auf der Wall erscheint.
- **„Mehr dazu“** nennt den eingestellten Anbieter („Anthropic, USA“ oder „Mistral AI,
  EU“). Die Beitrittstexte haben sich geändert: **beim Deploy `VB_CONSENT_VERSION`
  erhöhen.**

### Sicherheit

- **Review 3 (PSA)**, Details in `SECURITY_REVIEW.md`: 0 kritisch, 0 hoch, 1 mittel
  (REPO-01: alte Screenshots mit echtem Partynamen in der öffentlichen Git-Historie,
  braucht ein Umschreiben der Historie durch den Host), 5 niedrig (behoben oder
  akzeptiert), 6 Info.
- **Durchgang 2** über Schlüssel, KI-Pfad, Adressprüfung und Prompt-Injection: keine
  offenen hohen oder mittleren Befunde. Behoben: Ein Urteil, das einen Gast nennt,
  verschwindet sofort von der Wall, wenn der Gast „Keine Weitergabe an externe KI“
  einschaltet; Instagram-Namen gehen nur an die KI, wenn die Wall sie zeigt; das
  Schwärzen des Schlüssels in Logs greift auch für später angelegte Logger; die
  Adressprüfung nennt bei einer Umleitung nur noch das Ziel ohne Pfad. Ein Test zeichnet
  jeden Aufruf an den KI-Dienst über Erkennung, Abfrage und Urteil mit gemischten Gästen
  auf: nichts von Gästen mit Opt-out, gesperrten Gästen oder ausgeblendeten Fotos geht
  hinaus.

### Tests

INT2 (`night/int2`), gezielt:

| Lauf | Ergebnis |
|---|---|
| `make lint typecheck openapi-check` | sauber |
| Backend, die Testlisten der vier Briefs plus die neuen Integrationstests (pytest, 4 Prozesse) | 836 bestanden, 6 übersprungen (33 s) |
| Vitest: admin/ml, admin/wall, wall, admin/manage, admin/settings, admin/booth, admin/codes, guest, sdk, api | 435 bestanden in 51 Dateien |
| e2e Chromium (2 Prozesse, unter dem Lock): ML-Pipeline, Live-Wall-Admin, Einstellungen, Bereiche, Beitritt, Wall-Bildschirm, Wall live, Export, neu `test_ml_live_e2e.py` | 88 bestanden, 1 übersprungen (1:30 min; dazu Dashboard) |

Neu gegen den echten Server (ohne nachgebaute Antworten): ML-Pipeline mit Schlüssel,
Eigenschaft, Erkennung und „Jetzt abfragen“, Vorlage im Kategorie-Editor einschalten,
das Urteil im Admin und auf dem Fernseher, Testbild durch den echten Analyse-Prozess;
dazu ein API-Test des ganzen KI-Wegs mit Ereignis `categories.changed`.

### CI wieder grün (`night/ci-fix`, gemerged)

Alle fünf Jobs grün (Run 38675229579, gleicher Stand wie `main` nach dem Merge). Ursachen:

- **Backend:** Der Runner hat kein ffmpeg (der Zeitraffer-Test bekommt jetzt ein
  Ersatz-ffmpeg), und `FORCE_COLOR=1` färbte die `--help`-Ausgabe von Python 3.14
  (Tests setzen `PYTHON_COLORS=0`).
- **Firefox ohne WebGL:** Headless-Firefox ohne Bildschirm fiel auf Canvas2D zurück. Die
  Firefox-e2e laufen jetzt unter `xvfb-run` mit Software-GL, dazu `webgl.force-enabled`.
- **e2e hingen bis zum Timeout** (auch vorher auf `main`): Playwright 1.63 stirbt intern,
  wenn der Treiber auf einen Aufruf doppelt antwortet. Die e2e-`conftest` verwirft solche
  Antworten (Patch an einer privaten Playwright-API, wie schon `fastpoll.py`); nach einem
  Playwright-Update prüfen, ob er noch nötig ist.
- **Vitest:** Timer, die nach dem Ende einer Testdatei feuerten, werden jetzt
  aufgeräumt.
- Dazu einige Tests, die nach dem Merge von INT2 veraltet waren (14 statt 10 Filter,
  Anzeigename im Gast-Sheet, ein flackernder Ereignis-Test).

### Abschluss-Testlauf auf `main`

Einmal alles, nach dem Merge von `night/int2` und `night/ci-fix`:

| Lauf | Ergebnis |
|---|---|
| pytest (Unit + API) | 1231 bestanden, 9 übersprungen (36 s) |
| Vitest | 645 bestanden in 75 Dateien |
| e2e Chromium (4 Prozesse) | 282 bestanden, 37 übersprungen (4:28 min) |
| CI (backend, frontend, docker, e2e Chromium, e2e Firefox) | grün |

### Kurzer QA-Durchgang auf der Vorschau

Alle Wünsche einmal im Browser gegen den echten Server (Port 8100) durchgeklickt: 13 von
13 bestanden (Navigation, Allgemeines mit Adressprüfung OK/kaputt, Warnung im QR-Tab,
kein QR-Bogen, Fotobox-Filter, ML-Pipeline mit Testbild und Schlüssel nur „gesetzt“ und
nirgends in Seite oder API-Antworten, Eigenschaft archivieren, Kategorie-Editor mit 19+1
Vorlagen, Objektliste ohne „Neu analysieren“, Anzeigename zurücksetzen, „@“ fest im
Instagram-Feld, KI-Opt-out sichtbar beim Beitritt, neue Filter in der Fotobox, Wall mit
Passwort und ohne weißen Kasten). Danach behoben:

- Fotos, die **vor dem Update** ausgewertet wurden, haben keine Objektliste (eingefroren,
  kein Nachholen). Das Analyse-Panel sagt das jetzt, statt „Keine Objekte erkannt.“.
- Das Testbild zeigte „Aufgenommen 01.01.1970“; jetzt die aktuelle Zeit.
- Die Zähler der Analysen sind als „seit Serverstart“ beschriftet.

Bewusst so gelassen: Ein „@“ **mitten** im Anzeigenamen („anna@party“) ist erlaubt; nur
am Anfang ist es verboten, damit niemand wie ein Instagram-Name aussieht.

### Neues Aussehen: drei Stile, „Party“ als Standard (gemerged)

Drei Runden mit dem Host, alle in `main`:

1. **`night/identity`** (PR #1): Themen-Farben im Admin („Allgemeines → Erscheinungsbild“,
   Kontrastprüfung im Server), wirken ohne Neustart auf Gäste-Seiten und Wall; der Admin
   bleibt wie er ist. Vorlagen „Neon Nacht“ (Palette des Hosts) und „Klassisch“. Der erste
   Wurf war dem Host **zu schlicht**; danach kamen zurück: langsam wandernde Farblichter
   hinter der Startseite, ein Glanz über dem Partynamen, Emojis an den Aktivitätskarten
   (🍺, 📸; aus dem Manifest der Erweiterung, Feld `emoji`), auf der Wall wieder größere,
   sanft wackelnde Emojis und schräge Verlaufs-Badges.
2. **`night/goofy`** (PR #2): absichtlich übertriebene Variante „Rummel“ (Jahrmarkt 1994,
   Bungee-Schrift, Markise, Suchscheinwerfer). Durchgehender Gag: die Kamera hat
   Kulleraugen (Federphysik, folgen Finger/Neigung, blinzeln, schielen beim Countdown,
   kneifen beim Foto zu).
3. **`night/combo`** (PR #3): der Stil **„Party“** = Neon Nacht plus die besten Gags:
   Kulleraugen-Auslöser in Violett mit Lime-Lichtern, ein Gucker über der ersten Karte und
   dem QR-Code der Wall, dezentes Wackelpudding-Drücken, Ticket-Lochung an Sheets und
   Gästepass, der Partyname pendelt an seinem Haken ein, auf der Wall pendeln Fotos an
   einer Nadel ein, Werte stehen auf Preisbändern, oben eine dezente Lichterkette.

Im Admin: „Stil“ = **Ruhig · Party · Verspielt**; „Party“ ist Standard (auch für
gespeicherte Themen ohne Stil, „Rummel“ bringt „Verspielt“). Alle Gags sind dekorativ
(`aria-hidden`), bewegen nur `transform`/`opacity`, und „weniger Bewegung“ schaltet sie ab.
Screenshots: `.worktrees/_plans/night/{id,goofy,combo}/`.

Offene Geschmacksfragen: „Klassisch“ auch mit „Party“ oder „Ruhig“; Lichterring am
Auslöser blinkend oder still; Gucker in Periwinkle oder Lime; Nadel an jedem
Spotlight-Foto oder nur an Gewinnern; Lichterkette auf der Wall behalten.

Dazu zwei CI-Fehler behoben: `docker-smoke` meldete ein fehlendes sauberes Herunterfahren,
obwohl es im Log stand (`grep -q` mit `pipefail` → SIGPIPE), und ein Theme-e2e-Test nutzte
`wait_for_function`, das die CSP blockiert.

### Offene Punkte

1. **Detektor mit mehr Klassen:** Entscheidung des Hosts (siehe oben).
2. **Mistral:** Preise und Rahmenqualität am echten Dienst prüfen.
3. **Raspberry Pi 5:** Analysezeiten und Lasttest am echten Gerät messen.
4. **REPO-01:** Git-Historie umschreiben (Filter + Force-Push von `main`), nur auf
   ausdrückliche Entscheidung des Hosts.
5. **EXP-01 (akzeptiert):** Schon erstellte Export-Archive enthalten später gelöschte
   Fotos weiter; ein Hinweis im Lösch-Dialog wäre die kleine Folgearbeit.
6. **Urteile der KI** werden nicht moderiert; der Host kann nur die Kategorie
   ausschalten.
7. **Aussehen:** die offenen Geschmacksfragen oben.
8. **Docker lokal:** Die VPN-Firewall dieses Rechners (IVPN, „LAN erlauben“ aus) blockt
   Docker-Netzwerke; Docker-Smoke läuft darum nur in CI. Lösung beim Host:
   `ivpn firewall -lan_allow` oder eine Ausnahme für `172.16.0.0/12`.
9. **Beim Deploy `VB_CONSENT_VERSION` erhöhen** (geänderte Beitrittstexte; für eine neue Party-Datenbank egal).
10. **Nach jedem frischen Server:** im Admin „Modelle herunterladen“ und ein Live-Wall-Passwort (≥ 12 Zeichen) setzen.
11. **Firefox-e2e** zum Verlassen der Startseite ist gelegentlich rot (siehe Nachtrag Tag).

## Nachtrag 15.10. (Tag): online, Härtung, Admin, Admin-Gast

Alles in `main`, CI grün, ausgerollt auf dem Server des Hosts (Coolify, eigene Domain).

- **Sicherheitsprüfung vor dem Online-Gang** (`.worktrees/_plans/online-review.md`): Raten
  von Token, Passwörtern, Sessions und Foto-IDs aussichtslos; kein Weg zur
  Code-Ausführung; gefälschte Proxy-Header wirkungslos. Gefunden und behoben
  (`hardening/online`): kein Speicherlimit → Uploads stoppen unter `VB_MIN_FREE_MB`
  (2048, 503 `storage_full`, das Foto bleibt im Handy-Ausgang) und höchstens
  `VB_MAX_PHOTOS_PER_GUEST` (300, 403 `photo_limit`); CPU/RAM-Limits im Coolify-Compose
  (2 Kerne, 1,5 GB); Scans ohne Cookie legen höchstens `VB_SCANS_PER_IP_PER_10MIN` (120)
  Besucherzeilen an, lassen aber jeden rein; Live-Wall-Passwort mindestens 12 Zeichen.
  Bekannt und akzeptiert: Mit ein paar IPs lässt sich der Admin-Login für alle sperren
  (laufende Sessions bleiben gültig, vor der Party einloggen).
- **Deploy auf Coolify:** Fehler war die Domain-Eingabe (Pfad `/` → Traefik-Regel
  `PathPrefix("/:8000")`). Das Zertifikat kam nach wenigen Minuten.
- **ML auf dem Server** (`fix/ml-deploy`): Das Coolify-Compose baute ohne `VB_ML`; jetzt
  `VB_ML=1`, `VB_BAKE_MODELS=0` (Wunsch des Hosts), Modelle per „Modelle herunterladen“
  nach `/data/wall/models` (143,6 MB, ~15 s, SHA256 geprüft). Image 427 MB komprimiert /
  1,17 GB entpackt; RAM 143 MB ohne, 638 MB mit Modellen, Spitze 659 MB. Der
  Analyse-Schalter ließ sich nicht wieder einschalten (UI-Sperre), behoben.
  onnxruntime schickte Telemetrie an Microsoft: `ORT_DISABLE_TELEMETRY=1`.
- **Responsiveness** (`fix/responsive`): überlappende Felder in der ML-Pipeline
  (Textfelder konnten nicht schrumpfen), gedrückte Admin-Spalten (Karten richten sich
  jetzt nach ihrer eigenen Breite), Ergebnisknöpfe nach dem Foto liefen auf Android aus
  dem Bild, dazu Kleinkram; Regressionstests bei 320–1280 px.
- **Admin neutral weiß** (`design/admin-neutral`): Login, Live, Foto-Betrachter,
  Fehlerseiten im Stil der Verwaltung. Die Upload-Schalter gibt es nur noch einmal und
  direkt sichtbar („Hochladen für alle stoppen“, „Anmeldung stoppen“, „Neue Gäste
  pausieren“), gleich in Sidebar und Live. Live zeigt die Analyse (Chips, Rahmen im
  geöffneten Foto, Schalter „Analyse zeigen“, Aktualisierung per Ereignis
  `photo.analyzed`).
- **Admin-Gast** (`feat/admin-guest`, Migration 12 `users.is_host`): „Als Gast
  teilnehmen“ öffnet die Gäste-App als markierter Gast, ohne QR-Code (`code_id` NULL,
  zählt bei keinem Code mit; Zugang über das signierte Gast-Cookie dieses Nutzers). Ein
  Admin-Gast pro Party; ausgenommen von Foto-Limit, Neue-Gäste-Pause und Anmeldestopp,
  nicht sperrbar; „Hochladen stoppen“ gilt auch für ihn. Gäste sehen nichts davon.
- **Nach dem Foto** (`ux/uploaded-state`): große Upload-Zeile („Wird hochgeladen…“ →
  „Hochgeladen“, Gründe bei Problemen), „Herunterladen“ statt „Speichern“. Kamera-Fehler
  raten zu einem anderen Browser und dazu, den QR-Code dort nochmal zu scannen (ein
  kopierter Link hätte keinen Zugang).
- **Tests:** volle Suite vor jedem Merge (zuletzt 1313 Backend, 701 Vitest, 299 e2e
  Chromium), CI grün. Ein Firefox-e2e (`test_leaving_start_while_its_cards_load_goes_where_asked`)
  war einmal rot und im zweiten Lauf grün; zeitabhängig, im Auge behalten.

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
