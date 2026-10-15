# virtubooth: Funktionen

Was Gäste und Host mit virtubooth machen können. Wörter in „…“ stehen so in
der App. Betrieb und Einstellungen: [DEPLOY.md](DEPLOY.md). Technik und
Sicherheit: [ARCHITECTURE.md](ARCHITECTURE.md).

**Inhalt:**
[Für Gäste](#für-gäste) ·
[Für den Host](#für-den-host) ·
[Live-Wall](#live-wall) ·
[Was über Gäste gespeichert wird](#was-über-gäste-gespeichert-wird) ·
[Bewusst nicht enthalten](#bewusst-nicht-enthalten)

## Für Gäste

Die Gast-App ist deutsch, fürs Handy gebaut und läuft im Browser, ohne
Installation (iOS Safari und Android Chrome, dazu Firefox und Desktop; ab
Chrome/Edge 111, Firefox 114, Safari/iOS 16). Die Kamera braucht HTTPS.

### Zugang

- Jeder [QR-Code](#qr-codes) trägt ein geheimes Token (`?t=`) und führt zu
  Start oder direkt zu einer Aktivität. Der Server prüft es, setzt ein
  Zugangs-Cookie (30 Tage) und leitet auf dieselbe Adresse ohne Token um.
- Ohne gültigen Zugang zeigt jede Seite „Scan den QR-Code“ (HTTP 404), jede
  API antwortet 404. In den Browsern von Instagram, Facebook, WhatsApp,
  Snapchat und TikTok steht dort zusätzlich: lieber mit der Kamera-App scannen.
- Wird ein Code gelöscht oder bekommt er ein neues Token, kommt darüber
  niemand Neues mehr herein. Wer schon beigetreten ist, bleibt.
- Mehr als 60 falsche Tokens pro Minute und IP: das Gate kommt 1 s verzögert.
  Ein richtiger Code öffnet immer sofort.

### Beitreten

- Beim ersten Besuch erscheint das Beitritts-Sheet: „Willkommen bei
  <Eventname>!“, was mit den Fotos passiert (mit `VB_INSTAGRAM_ACCOUNT`) und
  „Wenn du das nicht möchtest, mach hier bitte keine Fotos.“
- „Mehr dazu“ erklärt die Gerätewiedererkennung, den anonymen
  Besucherzähler, die kleine Statistik pro Gast (Fotos, Online-Zeit, QR-Code),
  mit geladener Live-Wall die Fotoanalyse samt Schalter „Meine Fotos nicht
  automatisch auswerten“ und immer die mögliche externe KI mit dem
  eingestellten Anbieter. Solange der Host externe KI nutzt, steht dort auch
  „Keine Weitergabe an externe KI“.
- „Instagram-Name (freiwillig)“: nimmt einen Namen oder Profil-Link, das „@“
  steht fest davor, Fehler werden konkret erklärt.
- Ein einziger Knopf: „Alles klar, los geht’s!“. Kein „Nein“: wer nicht will,
  nutzt die Seite nicht. Kam der Gast über den Code einer Aktivität, öffnet
  sie sich danach; die Kamera fragt erst nach dem Beitritt.
- Kein Konto, kein Passwort. Jedes Gerät bekommt ein Pseudonym wie „Durstige
  Giraffe #17“ und wird per signiertem Cookie wiedererkannt (mit einer Kopie in
  localStorage, falls Safari das Cookie verliert).
- Ein erhöhtes `VB_CONSENT_VERSION` zeigt neuen Geräten „Die Hinweise haben
  sich gerade geändert. …“; Beigetretene werden nicht neu gefragt.

### Gästepass und Du-Sheet

- Der Gästepass (Start oben links, Kamera-Seiten oben rechts) zeigt Monogramm,
  Namen und Instagram-Namen; ein Punkt markiert Pause oder Stopp (bernstein)
  und Sperre (rot).
- Ein Tipp öffnet das Du-Sheet:
  - „Anzeigename“: 2 bis 24 Zeichen, nicht der Name eines anderen Gasts, nicht
    „Admin“, „Gastgeber“ o. ä. oder der Eventname. Leer = Standard (der
    Instagram-Name, sonst das Pseudonym).
  - Instagram-Namen eintragen, ändern oder entfernen (auch während einer Pause).
  - Ob man gerade hochladen kann, in einem Satz.
  - „Meine Fotos nicht automatisch auswerten“ (mit Live-Wall) und „Keine
    Weitergabe an externe KI“, jederzeit änderbar.

### Start und „Deine Bilder“

- Eventname, Gästepass, „Hilfe“ (Fotos, Kamera startet nicht, Link in
  Instagram/WhatsApp geöffnet, „Warum heiße ich so?“).
- Eine Statuszeile nur bei Ausnahmen: „Gesperrt“, „Hochladen pausiert“,
  „Hochladen ist kurz angehalten“, „Offline“, „1 Foto wartet“.
- Die Aktivitäten in der Reihenfolge von `VB_EXTENSIONS`, mit Live-Zeile
  (Beer Cam: Biere „von 1 Mio.“; Fotobox: Zahl der Filter).
- „Deine Bilder“: die eigenen sichtbaren Fotos, neueste zuerst, höchstens 60
  (8 offen, der Rest hinter „Alle … zeigen“). Groß geöffnet mit „Herunterladen“
  (iOS: Teilen-Menü, sonst Download), „Teilen“ (wo möglich, nicht iOS) und
  „Foto löschen“ (mit Rückfrage). Fotos anderer Gäste sieht ein Gast nie.
- Fußzeile: „Was passiert mit meinen Fotos?“ (die Beitrittstexte).

### Beer Cam (`/x/beer/`)

Alle fotografieren ihr Getränk im selben Umriss; zusammen ergibt das einen
Zeitraffer der Party.

- Rückkamera, Umriss „Flasche“ oder „Becher“ (das Gerät merkt sich die Wahl).
  Der Umriss ist nur eine Hilfe, nicht im Foto.
- Jedes Foto ist genau 1080 × 1440 px.
- Jedes Bier bekommt eine Nummer, die nie neu vergeben wird: „Bier Nr. 24
  gezählt“, „Noch … bis zur Million.“ (nur sichtbare zählen), jedes hundertste
  ist ein „Jubiläumsbier!“. Weiter mit „Noch ein Bier“.

### Fotobox (`/x/booth/`)

Selfies mit Live-Filtern.

- Frontkamera, gespiegelt; „Kamera wechseln“ per Knopf oder Doppeltipp.
- 14 Filter: Normal, Schwarz-Weiß, Sepia, Color Pop, Party-Rahmen (mit dem
  Eventnamen), Emoji-Props, Neon, Vintage/VHS, Retro-Pixel, Comic, Wärmebild,
  Disco, Kaleidoskop, Neonlinien. Wählen per Leiste, Wischen oder
  Pfeiltasten. WebGL-Shader mit Canvas2D-Ersatz; das Foto ist genau die
  Vorschau, 1080 × 1440 px. Der Host kann Filter abschalten
  ([Fotobox-Filter](#fotobox-filter)).
- Countdown „aus“ / „3 s“. Ergebnis als Abzug mit „Herunterladen“, „Teilen“ (nicht
  iOS) und „Neues Foto“; der Filmrand zeigt die Nummer und „Hochgeladen“.

### Auf beiden Kamera-Seiten

- Kopfzeile: zurück, der Titel als Menü „Aktivität wechseln“, der Gästepass.
- Die 3:4-Bühne ist das Foto; der Filmrand zeigt die Bildnummer, seine
  Perforation den Upload-Fortschritt. Leertaste oder Enter lösen aus.
- Darf der Gast gerade nicht hochladen, ist der Auslöser gesperrt und erklärt
  den Grund, bevor jemand ein Foto macht.
- Kamerafehler nennen den Grund (kein HTTPS, In-App-Browser, Zugriff
  verweigert mit Anleitung, keine Kamera, Kamera belegt).
- **Outbox:** Jedes Foto liegt zuerst im Gerät (IndexedDB), bis der Server es
  hat. Neue Versuche kommen von selbst (Netz zurück, Tab sichtbar, alle 30 s,
  nächster Besuch) oder mit „Erneut senden“. Ein Upload bricht nach 60 s ab,
  das Foto bleibt. Verworfen werden nur Fotos, die der Server nie annimmt.
  Ohne IndexedDB (privater Modus) liegen Fotos nur im Speicher, und der Browser
  fragt vor dem Schließen.

### Wenn etwas gesperrt ist

| Zustand | Was der Gast sieht |
|---|---|
| Kein oder altes Token | „Scan den QR-Code“ (404) |
| Anmeldung gestoppt | im Beitritts-Sheet „Gerade kann niemand neu beitreten.“, der Knopf kommt von selbst wieder |
| Gast gesperrt | ganze Seite „Gesperrt“ |
| Hochladen pausiert / für alle gestoppt | Statuszeile, Auslöser gesperrt; Fotos warten und gehen danach raus |
| Zu viele Uploads | „Langsam! Zu viele Fotos auf einmal. In … s nochmal.“ |
| Zu viele Fotos (`VB_MAX_PHOTOS_PER_GUEST`) | „Du hast schon sehr viele Fotos gemacht …“, das Foto wartet |
| Content-Blocker hat die Seite kaputt gemacht | nach 6 s „Die Seite startet nicht“ |
| Server nicht erreichbar | „Keine Verbindung“ bzw. „Keine Antwort vom Server“ |

Die App prüft den Status alle 30 s und beim Zurückkehren zur Seite; eine
Freigabe wirkt ohne Neuladen („Du kannst wieder hochladen.“). `?debug=1`
zeigt auf jeder Gast-Seite ein Protokoll, `?renderer=canvas2d` erzwingt die
Canvas2D-Vorschau.

## Für den Host

Der Admin-Bereich liegt unter `/admin`, braucht keinen QR-Code und läuft auf
Laptop und Handy. Jede offene Admin-Seite aktualisiert sich live, jede Aktion
steht im „Protokoll“.

### Anmeldung

- Ein gemeinsames Passwort, keine Admin-Konten: zuerst `VB_ADMIN_PASSWORD`,
  nach einer Änderung unter [Allgemeines](#allgemeines) nur noch das neue.
- Eine Sitzung hält 12 h (`VB_ADMIN_SESSION_HOURS`): kurz vor der Party auf
  jedem Gerät anmelden. „Abmelden“ beendet die Sitzung und ihre
  Live-Verbindungen sofort.
- Login-Sperre: pro IP 5 Versuche pro Minute und 20 pro Stunde; nach 20
  falschen Passwörtern in 15 Minuten, egal von wo, ist jeder Login 5 Minuten
  gesperrt („Zu viele Fehlversuche“). Angemeldete arbeiten weiter. Passwort
  vergessen oder ausgesperrt: [DEPLOY.md](DEPLOY.md#secrets-and-the-admin-password).

### Live

`/admin/live`, die Party-Ansicht fürs Handy.

- Die neuesten Fotos in einem dichten Raster, sie erscheinen sofort; ältere
  laden beim Scrollen.
- **Nur Aus- und Einblenden, kein Löschen:** ein Knopf pro Foto, „Rückgängig“
  im Toast. Ein Fehltipp löscht nie etwas.
- Ein Tipp öffnet das Foto groß mit Details, „Ausblenden“ und „Gast öffnen“.
- Darunter die [drei Schalter](#die-drei-schalter) und sechs
  [Live-Zahlen](#übersicht).
- **Analyse** (mit der Live-Wall): Chips unter jeder Kachel („3 Personen“, „2
  lächeln“, Objekte, gewonnene Kategorien, die Wünsche des Gasts) und Rahmen
  über dem Vorschaubild: Objekte pink, Gesichter orange, Hände grün. Das große
  Foto zeigt die volle Analyse. Fertige Analysen erscheinen ohne Neuladen.
  „Analyse zeigen“ blendet alles aus; der Browser merkt es sich.

### Die drei Schalter

Auf Live und in der Verwaltung immer sichtbar, ein Tipp schaltet ohne
Rückfrage, alle Admin-Geräte sehen es sofort. Alles bleibt über einen
Neustart erhalten.

- **„Hochladen für alle stoppen“** (rot): niemand kann hochladen, auch der
  [Admin-Gast](#als-gast-teilnehmen) nicht. Für kurze Notfälle.
- **„Anmeldung stoppen“** (bernstein): niemand Neues kann beitreten; wer dabei
  ist, macht weiter.
- **„Neue Gäste pausieren“:** wer ab jetzt beitritt, kann erst hochladen, wenn
  ihr freigebt. Beim Ausschalten fragt ein Dialog, ob die in der Pause
  Beigetretenen freigeschaltet werden oder pausiert bleiben.

Einzelne Gäste pausiert man auf der [Gästeseite](#gästeseite). „3 Gäste
pausiert“ unter den Schaltern führt zur gefilterten Gästeliste. Pausierte
Gäste können sich weiter umsehen und ihren Instagram-Namen ändern.

### Übersicht

Sechs Zahlen auf Live, alle im Tab „Übersicht“, neu alle 10 s und bei
passenden Ereignissen. „Wie wird gezählt?“ erklärt sie in der App.

- **Jetzt (letzte 5 min):** „Aktiv“ (Seite offen; sie meldet sich jede Minute,
  solange sie sichtbar ist), „Laden gerade hoch“, „Gescannt, noch nicht dabei“.
- **Scans:** „Gescannt“ (Browser mit gültigem QR-Link, per zufälliger
  Besucher-ID), „Beigetreten“, „Nicht beigetreten“.
- **Gäste:** gesamt, mit Instagram, pausiert, gesperrt.
- **Fotos:** gesamt, sichtbar, ausgeblendet, letzte 15 und 60 min, letzter
  Upload.
- Tabellen pro Aktivität und pro QR-Code (gescannt, Personen, beigetreten,
  Fotos, aktiv).

### Verwaltung

`/admin/manage`, der helle Leuchttisch, für den Desktop gedacht. Der Tab
steht in der Adresse (`?tab=…`).

| Tab | `?tab=` | Inhalt |
|---|---|---|
| Übersicht | `uebersicht` | die Zahlen oben |
| Allgemeines | `allgemein` | Eventname, Passwort, Erscheinungsbild, öffentliche Adresse ([unten](#allgemeines)) |
| Fotos | (Standard) | der Kontaktbogen ([unten](#fotos-gäste-protokoll)) |
| Gäste | `gaeste` | die Gästeliste |
| Instagram | `instagram` | wen markieren, welche Fotos posten ([unten](#instagram)) |
| Fotobox | `fotobox` | Filter an und aus |
| Live-Wall | `livewall` | Wall und Kategorien ([unten](#live-wall)) |
| ML-Pipeline | `ml` | Analysen, Modelle, Testbild, externe KI, Budget |
| Sperren | `sperren` | gesperrte Gäste und Gerätemerkmale |
| Protokoll | `protokoll` | wer wann was gemacht hat |
| QR-Codes | `qr` | die Codes, ihre Zahlen und Ausdrucke |
| Plakat | `plakat` | die Plakat-Vorlage |
| Export | `export` | Archiv und Zeitraffer |

Desktop: Seitenleiste mit den Tabs, Verbindungsanzeige, den drei Schaltern,
„Live öffnen“, „Als Gast teilnehmen“ und „Abmelden“. Handy: Tab-Leiste oben,
die Schalter darüber.

### Fotos, Gäste, Protokoll

- **Fotos:** alle Fotos als Raster; Fettstift-X = ausgeblendet, Kreis =
  ausgewählt. Filter Aktivität, Gast und Sichtbarkeit. Mehrfachauswahl (auch
  Shift-Klick, Strg+A), „Ausblenden“, „Einblenden“, „Löschen…“, höchstens 200
  Fotos pro Aktion. Tastatur: Pfeile, Enter, X, Entf, Esc. Ein Inspektor zeigt
  Details, Analyse, „Herunterladen“ und „Instagram-Namen kopieren“. Löschen
  entfernt die Dateien endgültig; die Nummer bleibt vergeben.
- **Gäste:** Nummer, Name, Status, Instagram, Fotos, „Online“ (sichtbare
  Seitenzeit, grüner Punkt = gerade offen), QR-Code, zuletzt gesehen, Gerät.
  Suche nach Name, @instagram oder #Nummer; Filter nach Status und QR-Code.
  Abzeichen für Sperre, automatische Sperre, Pause und die Wünsche des Gasts.
- **Protokoll:** jede Admin-Aktion mit Zeit, Ziel und Sitzung („Admin-Sitzung
  3f2a“), auch Logins und falsche Passwörter mit IP; 100 pro Seite.

### Gästeseite

`/admin/user?id=<Nr.>`, erreichbar von überall, wo ein Gast steht.

- Pseudonym, Anzeigename (zurücksetzbar), Instagram mit Kopier-Knopf und eine
  Statuszeile („Darf hochladen. 12 Fotos, davon 2 ausgeblendet.“, mit Grund bei
  Pause oder Sperre).
- **„Hochladen pausieren“** für diesen Gast (keine Sperre, seine Fotos bleiben
  sichtbar) und **„Sperren…“**.
- **Statistik:** Online-Zeit und Besuche (ein Besuch endet, wenn die Seite
  verborgen wird oder sich 150 s nicht meldet), der QR-Code des Beitritts,
  Fotos pro Aktivität, erstes und letztes Foto.
- Die Fotos des Gasts. „Technische Details“ (eingeklappt): Gerät, Bildschirm,
  erste und letzte IP, Einwilligung mit Version, Gerätemerkmale mit anderen
  Geräten desselben Merkmals.

### Als Gast teilnehmen

Der Host kann ohne QR-Code mitmachen: **„Als Gast teilnehmen“** in der
Seitenleiste und im Tab Gäste (danach „Als Gast öffnen“) meldet diesen
Browser als **Admin-Gast** an und öffnet die Gäste-App in einem neuen Tab.

- Es gibt einen Admin-Gast pro Party; jedes Admin-Gerät meldet sich als
  derselbe an. War der Browser schon ein anderer Gast, wird das ersetzt (der
  andere Gast bleibt bestehen).
- Ein normaler Gast mit dem Anzeigenamen „Gastgeber“; nur sein eigener
  Gästepass zeigt „Admin-Gast · nur du siehst das“.
- Kein Foto-Limit, nicht betroffen von „Neue Gäste pausieren“ und „Anmeldung
  stoppen“; „Hochladen für alle stoppen“ gilt auch für ihn. Er lässt sich
  pausieren, aber nicht sperren.
- Kein QR-Code: er zählt bei keinem Code und nicht bei „Gescannt“, aber bei
  „Gäste“. In der Verwaltung trägt er das Abzeichen „Admin-Gast“, im Export die
  Spalte `is_host`.

### QR-Codes

- Mehrere Codes, jeder mit fester Nummer und Tiernamen („Gorilla 2“), eigenem
  Token, Ziel (Start oder eine Aktivität), Notiz (bis 60 Zeichen) und Zahlen:
  gescannt, Personen, beigetreten, Fotos, online, zuletzt gescannt. Nummern
  und Namen werden nie neu vergeben.
- **Code 1** entsteht beim ersten Start aus `VB_PARTY_TOKEN` (oder mit einem
  neuen Token). Danach verwaltet man Tokens nur noch hier.
- **„Neuer QR-Code“**, **„Token ändern…“**, **„Bearbeiten…“** (Ziel, Notiz),
  **„Löschen…“** (der Code bleibt grau mit seinen Zahlen). Ein altes Token
  funktioniert sofort nicht mehr; Beigetretene bleiben.
- **Gedruckten Code übernehmen:** bei „Eigenes“ den Link des gedruckten Codes
  einfügen; Token und Ziel kommen daraus. Eigene Tokens: 16 bis 128 Zeichen aus
  `A–Z a–z 0–9 _ -`, mindestens 6 verschiedene. Kein Token wird je zweimal
  vergeben.
- **Ausdrucke pro Code**, sofort im Browser: „QR als PNG“ (mindestens
  1600 px), „QR groß (PDF)“ (A4, etwa 17 cm) und „Plakat (PDF)“. Jedes PDF trägt
  klein den Namen des Codes; das Token steht nur im Code.
- Alle Codes nehmen die [öffentliche Adresse](#allgemeines); ist sie nicht
  geprüft, warnt der Tab vor dem Drucken.

### Plakate

Tab „Plakat“: eine eigene PDF-Vorlage (höchstens 8 MB, bei mehreren Seiten
eine wählen) und ein grünes Feld, wo der QR-Code hinkommt: verschieben und
skalieren mit Maus, Finger oder Tastatur, „Speichern“. „Probedruck (PDF)“
zeigt das Plakat mit einem echten Code oder dem Muster-Code. Ohne Vorlage gibt
es ein Standard-Plakat mit Eventname, QR-Code und „Handy-Kamera drauf halten
und los!“. Der Server speichert nur Vorlage und Feld; die PDFs entstehen im
Browser.

### Sperren

- **„Sperren…“** auf der Gästeseite: das Sheet sagt vorher, was passiert
  („Alle 4 sichtbaren Fotos werden ausgeblendet …“), mit freiwilligem Grund.
  Gesperrte sehen „Gesperrt“ und können nichts hochladen.
- **„Gerätemerkmal auch sperren“:** neue Geräte mit demselben Merkmal starten
  gesperrt („Automatisch gesperrt“). Gleiche Handymodelle haben oft dasselbe
  Merkmal; das Sheet nennt, wie viele Geräte es teilen.
- **„Entsperren…“** holt nur die Fotos zurück, die die Sperre ausgeblendet hat,
  optional mit der Merkmal-Sperre.
- Tab „Sperren“: gesperrte Gäste und Merkmale, je mit „Entsperren“.

### Instagram

Die Liste für nach der Party: eine Zeile pro Instagram-Name mit Profil-Link,
Fotozahlen und den neuesten Fotos. **„Erledigt“** abhaken, wenn gepostet und
markiert ist. **„Fotos als ZIP“** pro Name (alle sichtbaren Fotos, nie von
gesperrten Gästen), „Alle Namen kopieren“.

### Exporte

Tab „Export“, als Hintergrund-Jobs auf dem Server (man kann die Seite
verlassen; pro Art höchstens einer gleichzeitig; die neuesten 10 Dateien
bleiben).

- **„Archiv erstellen“:** ZIP mit den Fotos pro Aktivität, `photos.csv`,
  `users.csv` (mit Anzeigename, Online-Zeit, QR-Code, `is_host`),
  `instagram.csv`, `manifest.json`, `README.txt`. Optional die ausgeblendeten
  Fotos und eine konsistente Kopie der Datenbank als Backup (ohne
  Admin-Sitzungen, Export-Jobs, Besucher-IDs und den KI-Schlüssel, so
  bereinigt, dass Gelöschtes nicht mehr lesbar ist; mit IPs, Gerätemerkmalen,
  QR-Tokens und dem Hash des Admin-Passworts).
- **„Zeitraffer erstellen“:** MP4 (H.264, 1080 × 1440) einer Aktivität in
  Upload-Reihenfolge, 6 bis 30 Fotos pro Sekunde (Standard 12), optional weich
  überblendet und mit ausgeblendeten Fotos; gelöschte nie.
- Den QR-Bogen für alle Aktivitäten gibt es nur noch auf der Kommandozeile;
  sie kann auch die Exporte mit mehr Optionen
  ([DEPLOY.md → Command line](DEPLOY.md#command-line)).

### Allgemeines

- **„Eventname“** (1 bis 60 Zeichen): auf Start, im Beitritts-Sheet, im
  Party-Rahmen, auf Plakaten und im Archiv; ohne eigenen gilt
  `VB_PARTY_NAME`. Gäste sehen ihn spätestens nach einer Minute.
- **„Admin-Passwort“:** mit dem aktuellen Passwort, neu mindestens 12 Zeichen.
  Danach sind alle anderen Geräte abgemeldet.
- **„Erscheinungsbild“** der Gästeseiten und der Live-Wall (die Verwaltung
  bleibt hell):
  - **Vorlage:** „Neon Nacht“, „Klassisch“, „Rummel“ oder „Eigene“ Farben
    (Text muss auf Hintergrund und Fläche 4,5:1 erreichen).
  - **Stil:** „Ruhig“, „Party“ (ruhig plus ein paar Gags) oder „Verspielt“
    (Rummel-Look: Schilder, Lauflichter, Wackelaugen, ein Buzzer als
    Auslöser, Eintrittskarten; auf der Wall Glühbirnen und Preisschleifen).
  - **Standard: „Neon Nacht“ im Stil „Verspielt“.** Eine Vorlage bringt ihren
    Stil mit (Klassisch: Party, die anderen: Verspielt), danach ist er frei
    wählbar. „Zurücksetzen“ führt zum Standard. Bei reduzierter Bewegung
    stehen die Animationen still.
- **„Öffentliche Adresse“** (z. B. `https://party.example.com`, leer =
  automatisch): in QR-Codes, Plakaten und der Ecke der Live-Wall, vor
  `VB_PUBLIC_BASE_URL`. Beim Speichern prüft der Server, dass genau er unter
  `<Adresse>/healthz` antwortet: „Erreichbar ✓“ oder eine Warnung, die nichts
  blockiert.

### Fotobox-Filter

Ein Schalter pro Filter, jeder Klick speichert sofort, mindestens einer
bleibt an. Gäste haben die Änderung spätestens nach 30 s.

## Live-Wall

Die Fotos auf einem Fernseher oder Beamer: `/livewall` im Browser öffnen.
Einstellungen im Tab „Live-Wall“; „Speichern“ wirkt sofort auf allen offenen
Wänden.

- **Zugang:** ein eigenes Passwort (mindestens 12 Zeichen); der Bildschirm
  merkt sich die Anmeldung 30 Tage. Ein angemeldeter Admin braucht keins.
  Passwort ändern oder „Alle Wände abmelden“ beendet jede offene Wand. Login
  begrenzt wie beim Admin.
- **Ablauf:** drei Modi im Wechsel, Reihenfolge und Dauer frei (10 s bis 1 h):
  - **Einzelbild:** ein Foto groß mit „von <Name>“, alle 3 bis 120 s, mit
    sieben Auswahl-Verfahren (Standard „Neue Fotos sofort, sonst gemischt“,
    dazu z. B. „Fair: jeder Gast reihum“, „Kategorie-Highlights“).
  - **Galerie:** eine endlose Fotowand, 2 bis 6 Reihen.
  - **Kategorien:** die Gewinner der [Kategorien](#kategorien), 4 bis 60 s je
    Kategorie, darunter das Urteil der KI, wenn es eins gibt.
- **Aussehen:** elf Übergänge (Überblenden, Glitch, Polaroid-Fall,
  Spielautomat, Konfetti, …) oder Zufall; animierte Hintergründe („Farbblasen“,
  „Polarlicht“, „Disco-Gitter“, „Konfetti-Regen“, „Ruhig“); die Farben folgen
  dem [Erscheinungsbild](#allgemeines), wenn nicht eigene gesetzt sind.
- **Einblendungen:** Eventname, Fotozähler, ein QR-Code in einer Ecke.
- **Fotos:** neue erscheinen nach einer Verzögerung (Standard 20 s, 0 bis
  600 s), damit der Host vorher ausblenden kann. Ausblenden, Löschen und
  Sperren nehmen Fotos sofort von jeder Wand. Es zählen die neuesten 1000.
  Instagram-Namen nur, wenn eingeschaltet.
- Der Bildschirm bleibt wach (über https), verbindet sich nach einem Abbruch
  selbst neu und holt Verpasstes nach.

### Fotoanalyse

Für die Kategorien wertet ein eigener Prozess auf dem Server jedes Foto
**einmal** aus. Ohne externe KI verlässt nichts den Server.

- **Immer:** Helligkeit, Farbigkeit, Schärfe.
- **Mit dem ML-Paket** (`VB_ML=1`, auf Coolify Standard) und den Modellen
  (ML-Pipeline → „Modelle herunterladen“): Gesichter, Gesichtsausdruck, Hände
  und Gesten, Objekte (80 Klassen mit deutschen Namen, z. B. „Weinglas“),
  Brillen, Hüte, Altersgruppe, und optional „Alter (FairFace)“.
- Gespeichert werden Zahlen pro Foto, die Objektliste und Rahmen um Objekte,
  Gesichter und Hände: keine Gesichtsmerkmale, nichts, was eine Person
  wiedererkennt. Gelöschte Fotos verlieren ihre Analyse.
- **Eingefroren:** eine Analyse wird nie wiederholt; neue Einstellungen gelten
  für danach analysierte Fotos. Ein abgestürzter Versuch wird bis zu dreimal
  wiederholt. Externe KI kann der Objektliste nur etwas anhängen.
- Der Prozess läuft mit niedriger Priorität, ein Foto nach dem anderen, das
  neueste zuerst; Uploads werden dadurch nicht langsamer.
- **Abschalten durch den Gast** („Meine Fotos nicht automatisch auswerten“):
  neue Fotos bekommen nur die Bildwerte, und solange der Schalter an ist,
  fallen alle seine Fotos aus allen Kategorien und Abfragen.

### Kategorien

Kategorien sind Regeln. Die Karte „Kategorien“ im Tab „Live-Wall“ zeigt jede
mit Schalter, Reihenfolge, den aktuellen Gewinnern und, wenn nichts gewinnen
kann, warum.

- **Eine Kategorie:** Emoji, Titel, Zeile, bis zu 8 Bedingungen, Auswahl
  „Top“ oder „Bottom“ nach einem Wert, 1 bis 10 Gewinner, „Ein Foto pro Gast“,
  die Beschriftung auf der Wall und optional ein „Urteil der KI (Prompt)“. Der
  Editor zeigt die Gewinner schon beim Tippen.
- **Werte:** jeder Analysewert, „Anzahl von <Objekt>“, die Werte der
  [Eigenschaften](#ml-pipeline-und-externe-ki), Aufnahmezeit, Fotos des Gasts.
- **Vorlagen:** Volles Haus, Hände hoch!, Grinsekatzen, Herzschmerz-Pose,
  Ach du Schreck!, Brillenbande, Generationen-Foto, Dream-Team, Solo-Star,
  Peace!, Rock'n'Roll, Daumen hoch, Prost!, Hutparade, Gesangseinlage,
  Farbexplosion, Action-Shot, Eröffnungsfoto, Dauerauslöser und (aus) „Das
  coolste Objekt“ mit KI-Urteil. Änderbar und löschbar; „Vorlagen
  wiederherstellen“ holt sie zurück. Keine nennt die älteste oder jüngste
  Person oder bewertet Aussehen.
- Gewinner sind nur sichtbare Fotos nach der Verzögerung, nie von Gästen, die
  die Auswertung abgeschaltet haben.

### ML-Pipeline und externe KI

Tab „ML-Pipeline“:

- **„Modelle“:** jede Analyse mit Größe, an/aus, Einstellungen und Zahlen
  (Dauer, Fotos, Fehler), die Warteschlange und der Herzschlag des Prozesses.
  Fehlen Modelle, steht oben **„Modelle herunterladen“** (mit Fortschritt).
  Fehlt das ML-Paket, sagt die Karte, wie man es behebt.
- **„Testbild“:** ein JPEG hochladen und sehen, was die Pipeline findet (auf
  Wunsch auch der KI-Dienst). Nichts wird als Partyfoto gespeichert;
  höchstens 6 pro Minute.
- **„Claude (KI-Dienst)“** (aus): Anbieter Anthropic (USA) oder Mistral AI
  (EU), Modell (Standard Claude Haiku 5.5; Sonnet 5.5, Opus 5.5; Mistral Small
  3.2, Medium 3.1), „Abfrage alle … Minuten“ (1 bis 60), Erkennung beim
  Hochladen lokal und/oder per KI. Der API-Schlüssel wird verschlüsselt
  gespeichert und nie wieder angezeigt.
- **„Eigenschaften“:** z. B. `coolness` mit Prompt. Name und Prompt sind fest;
  statt Löschen „Archivieren“.
- **„Budget“:** Grenzen in USD und/oder Aufrufen, für die Party und pro Tag,
  mit Verbrauch. Am Limit stoppt jeder Aufruf.

Was die externe KI tut, wenn sie an ist:

- **Erkennung beim Hochladen:** das Foto geht verkleinert (≤ 1024 px, ohne
  Metadaten) an den Dienst; die gefundenen Objekte werden angehängt.
- **Abfrage** (nur Text): pro Eigenschaft die Objektlisten der erlaubten Fotos;
  zurück kommt ein Wert pro Objekt. Danach ein Urteil (höchstens 160 Zeichen)
  pro Kategorie mit Prompt, das auf der Wall unter dem Gewinner steht. Ohne
  Änderung keine Abfrage.
- **Nie hinaus** gehen Fotos, Objekte und Namen von Gästen mit „Keine
  Weitergabe an externe KI“ oder abgeschalteter Auswertung, von gesperrten
  Gästen sowie ausgeblendete und gelöschte Fotos, geprüft direkt vor jedem
  Aufruf. Gastnamen sind für die KI als Daten markiert, nie als Anweisung.

## Was über Gäste gespeichert wird

| Daten | Wozu |
|---|---|
| Gast-Nr., Pseudonym, optional Anzeigename und Instagram-Name | Anzeige, Markieren beim Posten |
| Zeit und Textversion des Beitritts | Nachweis, was der Gast gesehen hat |
| Erstes und letztes Mal gesehen, Online-Zeit und Besuche | Gästeliste, Statistik |
| Erste und letzte IP, User-Agent | Moderation |
| Gerätemerkmal (Hash und Bestandteile wie Bildschirm, Grafik, Sprachen) | nur ein Hinweis für Sperren, keine Identität |
| Sperre mit Grund, Pause mit Quelle | Moderation |
| Fotos (neu kodiert, ohne EXIF/GPS) mit Vorschaubild, Aktivität, Nummer, Zeit, Filter bzw. Gefäß | die Party |
| Anonyme Besucher-ID mit erstem und letztem Besuch, welcher QR-Code wie oft geöffnet wurde; keine IP | „Gescannt“, Zahlen pro Code |
| Mit Live-Wall: Analysewerte, Objektliste und Rahmen pro Foto; die Wünsche des Gasts | Kategorien |
| Mit externer KI: Werte der Eigenschaften, Urteile, Verbrauch. Beim Anbieter landen das verkleinerte Foto und Objekt- und Anzeigenamen | Kategorien |

Auf dem Gerät liegen die Cookies, in localStorage eine Kopie der Gast-ID und
die Wahl von Gefäß und Countdown, in IndexedDB die Outbox. Ausgeblendete Fotos
bleiben auf der Platte; nur Löschen in der Verwaltung oder das Löschen des
Volumes entfernt Dateien. Wie das alles geschützt ist:
[ARCHITECTURE.md → Security model](ARCHITECTURE.md#security-model).

## Bewusst nicht enthalten

- **Keine Konten:** Gäste haben ein Pseudonym, Admins teilen ein Passwort.
- **Kein „Nein“ im Beitritt:** wer nicht fotografiert werden will, nutzt die
  Seite nicht.
- **Kein Löschen auf Live:** nur Aus- und Einblenden; Löschen und Sperren in
  der Verwaltung und auf der Gästeseite.
- **Kein Service Worker,** keine Offline-App; die Outbox hält Fotos trotzdem.
- **Nur ein Prozess:** Limits und Live-Ereignisse liegen im Speicher, also
  nie mehrere Worker oder Container.
- **Keine Laufzeit-API-Doku:** das Schema entsteht mit
  `virtubooth export-openapi`.
