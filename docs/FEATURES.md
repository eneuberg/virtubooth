# virtubooth: alle Funktionen

Was man mit virtubooth machen kann, nach Rolle und Bereich. Für Gastgeber und für
Entwickler. Jede Zeile ist gegen den Code geprüft. Wörter in „…“ stehen genau so in
der App.

**Stand:** 15.10.2026, Branch `night/int2` (mit QR-Codes, Plakaten, Online-Zeit und
der Nachtrunde: eingefrorene Fotoanalyse, Kategorien als Regeln, ML-Pipeline mit
optionaler externer KI, Allgemeines/Fotobox, öffentliche Adresse, Anzeigenamen).

**Inhalt:**
[1. Kurzüberblick](#1-kurzüberblick) ·
[2. Für Gäste](#2-für-gäste) ·
[3. Für den Host](#3-für-den-host) ·
[4. Betrieb](#4-betrieb) ·
[5. Sicherheit und Datenschutz](#5-sicherheit-und-datenschutz) ·
[6. Erweiterbarkeit](#6-erweiterbarkeit) ·
[7. Bewusst nicht enthalten](#7-bewusst-nicht-enthalten)

## 1. Kurzüberblick

virtubooth ist eine selbst gehostete Web-App für eine Party. Gäste scannen einen
QR-Code und sind mit einem Tipp dabei, ohne App und ohne Konto. Auf dem eigenen Handy
spielen sie Foto-Aktivitäten: die Beer Cam für einen gemeinsamen Zeitraffer und die
Fotobox für Selfies mit Filtern. Der Host moderiert live im Admin-Bereich, steuert
Hochladen und Anmeldung, verwaltet mehrere QR-Codes mit Zahlen pro Code, druckt
Plakate und nimmt nach der Party Archiv, Zeitraffer und Instagram-Liste mit. Eine
Live-Wall zeigt die Fotos auf einem großen Bildschirm, mit lustigen Kategorien aus
einer Fotoanalyse auf dem eigenen Server.

## 2. Für Gäste

Die Gast-App ist deutsch und für das Handy gebaut. Sie läuft im Browser, ohne
Installation.

### Zugang

- **QR-Code scannen.** Es gibt mehrere QR-Codes (Admin → QR-Codes), jeder mit eigenem
  geheimen Token (`?t=`). Ein Code führt zu Start oder direkt zu einer Aktivität
  (`/x/beer/`, `/x/booth/`).
- Der Server prüft das Token, setzt ein Zugangs-Cookie (30 Tage) und leitet auf
  dieselbe Adresse ohne Token um. Danach steht das Token nicht mehr in der
  Adresszeile. Der Scan zählt für diesen Code.
- **Löscht der Host einen Code oder ändert sein Token,** funktioniert der alte Code
  sofort nicht mehr: Neue Scans und Browser, die damit gescannt, aber noch nicht
  beigetreten sind, sehen das Gate und brauchen einen gültigen Code. Wer schon
  beigetreten ist, bleibt dabei.
- **Ohne gültigen Zugang** zeigt jede Seite „Scan den QR-Code“ (HTTP 404). Jede
  API-Anfrage antwortet ebenfalls 404.
  - In den Browsern von Instagram, Facebook, WhatsApp, Snapchat und TikTok steht dort
    zusätzlich: den Code lieber mit der Kamera-App scannen.
- **Mit Zugang, aber falscher Adresse:** „Hier ist nichts.“ mit „Zum Start“.
- Beide Seiten sind statisch und funktionieren ohne JavaScript.
- Wer zu oft ein falsches Token probiert (mehr als 60 pro Minute und IP), bekommt
  das Gate nur noch verzögert (1 s) und landet im Log. Ein richtiger Code öffnet
  trotzdem sofort, auch für alle anderen Gäste im selben WLAN.

### Beitreten

- Beim ersten Besuch erscheint das Beitritts-Sheet über dem Partynamen. Auch der Code
  einer Aktivität führt zuerst hierher; die Kamera startet erst danach.
- Die Texte kommen vom Server: Titel „Willkommen bei <Partyname>!“, was mit den Fotos
  passiert (mit `VB_INSTAGRAM_ACCOUNT`), und „Wenn du das nicht möchtest, mach hier
  bitte keine Fotos.“
- Unter „Mehr dazu“: die Gerätewiedererkennung, der Hinweis auf den anonymen
  Besucherzähler und was die Gastgeber pro Gast sehen („eine kleine Statistik“: Fotos,
  wie lange die Seite offen war, über welchen QR-Code der Gast kam). Wer den Satz als
  Teil der Einwilligung festhalten will, erhöht `VB_CONSENT_VERSION`.
- Ist die [Live-Wall](#live-wall) geladen, steht unter „Mehr dazu“ auch, dass Fotos
  für sie automatisch auf dem Server ausgewertet werden, und darunter der Schalter
  „Meine Fotos nicht automatisch auswerten“ (siehe [Fotoanalyse](#fotoanalyse)).
- Unter „Mehr dazu“ steht immer, dass Fotos und erkannte Dinge zusätzlich von einem
  externen KI-Dienst ausgewertet werden können, wenn der Gastgeber es einschaltet. Der
  Text nennt den eingestellten Anbieter („Anthropic, USA“ oder „Mistral AI, EU“).
  Solange der Host externe KI wirklich nutzt, steht darunter der Schalter „Keine
  Weitergabe an externe KI“ (siehe [ML-Pipeline](#ml-pipeline-und-externe-ki)).
- Feld „Instagram-Name (freiwillig)“ mit „Dann können wir dich markieren.“
  - Ein festes „@“ steht vorn im Feld; ein getipptes oder eingefügtes „@“ fällt weg.
  - Nimmt `name` oder einen Profil-Link.
  - Fehler werden konkret erklärt: Umlaute, Akzente, Leerzeichen, zwei Punkte, mehr
    als 30 Zeichen.
- Ein einziger Knopf: „Alles klar, los geht’s!“. Es gibt kein „Nein“ und kein
  Schließen. Wer nicht will, nutzt die Seite nicht.
- Kam der Gast über den Code einer Aktivität, nennt das Sheet sie und öffnet sie nach
  dem Beitritt.
- **Kein Konto, kein Passwort, keine E-Mail.** Jedes Gerät bekommt ein Pseudonym aus
  Adjektiv, Tier und Gast-Nr., z. B. „Durstige Giraffe #17“.
- Das Gerät wird per signiertem Cookie wiedererkannt. Eine Kopie liegt in
  localStorage, falls das Cookie verloren geht (z. B. durch Safari ITP).
- Beitritt in einem zweiten Tab: ein Toast sagt, unter welchem Namen man schon dabei
  ist. Ein anderer Instagram-Name ersetzt den gespeicherten dort nicht.
- Hat der Host die Hinweise geändert (`VB_CONSENT_VERSION`), sagt das Sheet „Die
  Hinweise haben sich gerade geändert. …“. Wer schon beigetreten ist, wird nicht neu
  gefragt.
- Hat der Host die Anmeldung gestoppt, siehe [Anmeldung stoppen](#anmeldung-stoppen).

### Gästepass und Du-Sheet

- Der Gästepass steht auf Start oben links, auf den Kamera-Seiten kompakt oben rechts.
  - Er zeigt Monogramm und Kurznamen, auf Start darunter den Instagram-Namen mit @
    oder „Instagram hinzufügen“.
  - Ein Punkt am Monogramm markiert Pause oder Stopp (bernstein) und Sperre (rot).
- Ein Tipp öffnet das Du-Sheet. Titel ist der angezeigte Name, darunter „Dein Name auf
  dieser Party“.
  - „Anzeigename“: „So sehen dich die anderen. Standard: dein Instagram-Name, sonst
    dein Zufallsname.“ 2 bis 24 Zeichen; keine Steuer- oder unsichtbaren Zeichen, kein
    „@“ vorn, nicht der Name eines anderen Gasts, nicht „Admin“, „Gastgeber“ o. ä. oder
    der Eventname („Dieser Name ist schon vergeben.“, „Dieser Name geht leider
    nicht.“). Leeren stellt den Standard wieder her. Die interne Nummer bleibt.
  - Instagram-Namen eintragen oder ändern („Speichern“) oder löschen („Entfernen“).
    Geht auch, während Hochladen pausiert ist.
  - Abschnitt „Hochladen“: ob man gerade hochladen kann, in einem Satz.
  - Mit der Live-Wall: der Schalter „Meine Fotos nicht automatisch auswerten“. Er
    gilt sofort, auch für schon hochgeladene Fotos (sie fallen aus allen Kategorien).
  - „Keine Weitergabe an externe KI“: jederzeit änderbar, gilt ab dem nächsten Aufruf
    der KI.

### Start

- Partyname als Überschrift und im Tab-Titel, Gästepass, Knopf „Hilfe“ (Fragezeichen).
- Statuszeile, nur bei Ausnahmen: „Gesperrt“, „Hochladen pausiert“, „Hochladen ist
  kurz angehalten“, „Offline“, „1 Foto wartet“. Ein Tipp erklärt den Zustand, „Alles
  klar“ schließt.
- In In-App-Browsern: Hinweis „Hier geht die Kamera oft nicht“ mit „Verstanden“.
- Die Aktivitäten als Filmstreifen, in der Reihenfolge aus `VB_EXTENSIONS`, je mit
  Titel, Untertitel und Live-Zeile:
  - Beer Cam: die Zahl der sichtbaren Biere „von 1 Mio. Bieren“, alle 30 s neu.
  - Fotobox: fünf feste Beispielbilder und die Zahl der Filter („14 Filter“).
- „Deine Bilder“ (nächster Abschnitt).
- Fußzeile: „Was passiert mit meinen Fotos?“ (die Beitrittstexte zum Nachlesen) und,
  wenn gesetzt, „Die Gastgeber posten ausgewählte Fotos auf <Account>.“
- „Hilfe“ enthält „Was passiert mit meinen Fotos?“, „Die Kamera startet nicht“
  (Anleitung für iOS und für andere Handys), „Link in Instagram oder WhatsApp
  geöffnet?“ und „Warum heiße ich so?“.
- Layout: Handy hochkant einspaltig, Handy quer und Desktop zweispaltig.

### „Deine Bilder“

- Auf Start: die eigenen Fotos, die sichtbar sind (nicht ausgeblendet, nicht
  gelöscht), neueste zuerst, höchstens 60.
- Die ersten 8 sind zu sehen, der Rest hinter „Alle … zeigen“ und „Weniger zeigen“.
- Jedes Bild mit Bildnummer („Bier 0032“, „Foto 0018“) und Uhrzeit.
- Ein gerade gesendetes Foto erscheint sofort. Die Liste lädt außerdem jede Minute neu.
- Ein Tipp öffnet „Dein Bild“ groß, mit „Vorheriges Bild“ und „Nächstes Bild“ (auch
  Pfeiltasten).
  - „Speichern“: auf iOS das Teilen-Menü, über das man das Bild in die Fotos sichert,
    sonst ein Download wie `beer-00032.jpg`.
  - „Teilen“: zusätzlich, wenn der Browser Dateien teilen kann und es kein iOS ist.
- Ohne Fotos: leere Rahmen und eine Einladung zu den Aktivitäten.
- Fotos anderer Gäste sieht ein Gast nie.

### Beer Cam

Alle fotografieren ihr Getränk im selben Umriss. So entsteht ein Zeitraffer der
Party. Adresse: `/x/beer/`.

- Rückkamera als Standard. „Kamera wechseln“, wenn das Gerät mehrere Kameras hat.
- Umriss: Auswahl „Gefäß“ mit „Flasche“ (Standard) oder „Becher“. Das Gerät merkt sich
  die Wahl.
  - Hinweis: „Halte die Flasche in den Umriss.“ bzw. „Halte den Becher in den Umriss.“
  - Der Umriss ist nur eine Hilfe. Er ist nicht im Foto.
- Jedes Foto ist genau 1080 × 1440 px (3:4), damit alle Bilder deckungsgleich sind.
- **Nummerierung:** Jedes Bier bekommt seine eigene Nummer, die nie neu vergeben wird,
  auch nicht nach dem Löschen.
  - Vor dem Foto zeigt der Filmrand „Nächstes Bier“ mit der Nummer und „Ziel 1 Mio.“.
  - Nach dem Foto: „Wird gezählt…“, dann „Bier Nr. 24 gezählt“ und „Gezählt“ auf dem
    Filmrand.
- **Zähler:** „Noch … bis zur Million.“ bzw. „Die Million ist voll!“. Es zählen nur
  sichtbare Biere. Ausgeblendete und gelöschte zählen nicht.
- Jedes hundertste Bier ist ein „Jubiläumsbier!“, sonst kommt ein zufälliger Spruch
  („Prost!“, „Zum Wohl!“, …).
- Weiter mit „Noch ein Bier“.
- Kann das Foto gerade nicht hoch: „Dein Bier wartet“ mit „Erneut senden“. Geht es nie
  (z. B. kaputtes Bild): „Das Bier lässt sich nicht hochladen“.

### Fotobox

Selfies mit Live-Filtern. Adresse: `/x/booth/`.

- Frontkamera als Standard, gespiegelt wie ein Spiegel. „Kamera wechseln“ per Knopf
  oder Doppeltipp auf das Bild.
- **14 Filter** in dieser Reihenfolge: „Normal“, „Schwarz-Weiß“, „Sepia“, „Color Pop“,
  „Party-Rahmen“ (mit dem Partynamen), „Emoji-Props“, „Neon“, „Vintage/VHS“,
  „Retro-Pixel“, „Comic“, „Wärmebild“, „Disco“ (Farbversatz, Spots, Glitzer),
  „Kaleidoskop“ (ein Ring aus Gesichtern), „Neonlinien“ (leuchtende Kanten).
  - Wählen per Filterleiste, Wischen über das Bild oder Pfeiltasten.
  - Die Filter sind WebGL-Shader. Ohne WebGL läuft eine Canvas2D-Variante; Filter, die
    dort nicht gehen, fehlen dann in der Leiste.
  - Das gespeicherte Foto ist genau das Vorschaubild, mit Filter, in 1080 × 1440 px.
  - Der Host kann einzelne Filter unter [Fotobox-Filter](#fotobox-filter) ausschalten,
    mindestens einer bleibt an. Sie verschwinden spätestens nach 30 s aus der Leiste;
    war einer davon gewählt, gilt der erste Filter.
- **Countdown:** Schalter „aus“ / „3 s“, das Gerät merkt sich die Wahl. Ein Tipp auf
  den Auslöser oder Esc bricht den Countdown ab.
- **Ergebnis** als Abzug, der sich langsam entwickelt:
  - „Speichern“ (danach „Gespeichert“): auf iOS das Teilen-Menü, sonst ein Download
    wie `fotobox-18.jpg`.
  - „Teilen“: zusätzlich, wenn der Browser Dateien teilen kann und es kein iOS ist.
  - „Neues Foto“.
- **Nummer:** Der Filmrand zeigt „Nächstes Foto“ mit der Nummer, danach „Foto“ mit der
  eigenen Nummer und „Hochgeladen“.
- Kann das Foto gerade nicht hoch: „Dein Foto wartet.“ Geht es nie: „Nicht
  hochgeladen.“ mit „Speichern geht trotzdem.“

### Auf beiden Kamera-Seiten

- Der Browser fragt erst nach dem Beitritt nach der Kamera.
- Kopfzeile: zurück zum Start, der Titel als Umschalter (Menü „Aktivität wechseln“ mit
  den anderen Aktivitäten und „Start“), der Gästepass.
- Die 3:4-Bühne ist das Foto. Nur die Frontkamera wird gespiegelt.
- Der Filmrand zeigt die Bildnummer. Seine Perforation ist der Upload-Fortschritt.
- **Auslöser gesperrt**, solange der Gast nicht hochladen darf. Ein Tipp darauf
  vibriert und erklärt den Grund, bevor jemand ein Foto macht.
- Rückmeldung beim Auslösen: Blitz und Vibration.
- Tastatur: Leertaste oder Enter löst aus, Esc schließt das Ergebnis.
- Kamerafehler: „Die Kamera geht nicht“ mit dem konkreten Grund (kein HTTPS,
  In-App-Browser, Zugriff verweigert mit Anleitung für iOS, Touch-Geräte oder Desktop,
  keine Kamera, Kamera von einer anderen App belegt).
- Layouts für Handy hochkant, kurze Bildschirme, Handy quer und Desktop.
- Endet eine Pause oder ein Stopp: Toast „Du kannst wieder hochladen.“, wartende Fotos
  gehen sofort raus.

### Outbox: kein Foto geht verloren

- Jedes Foto landet zuerst im Gerät (IndexedDB) und bleibt dort, bis der Server es
  hat.
- Neue Versuche kommen von selbst: wenn das Netz zurück ist, wenn der Tab wieder
  sichtbar wird, alle 30 s, solange etwas wartet, und beim nächsten Besuch.
- Von Hand: „Erneut senden“ am Filmrand oder in der Statuszeile. Bei „Langsam! Zu
  viele Fotos auf einmal.“ zählt der Knopf die Wartezeit des Servers herunter.
- Darf der Gast gerade nicht hochladen (pausiert, gestoppt, gesperrt), wartet das Foto
  („Wartet“) und geht raus, sobald es wieder darf.
- Nur Fotos, die der Server nie annehmen wird (falsches Format, zu groß), werden
  verworfen, mit Toast „Ein Foto lässt sich nicht hochladen: …“.
- Kommt ein wartendes Foto später an: Toast „Dein Bier von vorhin ist jetzt gezählt.“
  bzw. „Foto 0019 von vorhin ist jetzt hochgeladen.“
- Ohne IndexedDB (privater Modus, manche In-App-Browser) liegen Fotos nur im Speicher.
  Dann fragt der Browser vor dem Schließen des Tabs nach.

### Was ein Gast sieht, wenn etwas gesperrt ist

| Zustand | Was der Gast sieht |
|---|---|
| Kein oder altes QR-Token | Seite „Scan den QR-Code“ (404) |
| Anmeldung gestoppt | Im Beitritts-Sheet statt des Knopfs: „Gerade kann niemand neu beitreten.“ und „Nochmal versuchen“ |
| Gast gesperrt | Ganze Seite „Gesperrt“: „Dieses Gerät ist gesperrt. Sprich die Gastgeber an, wenn das ein Versehen ist.“ mit „Seite neu laden“ |
| Hochladen für diesen Gast pausiert | Statuszeile „Hochladen pausiert“, Auslöser gesperrt. Umsehen und Instagram ändern geht weiter |
| Hochladen für alle gestoppt | Statuszeile „Hochladen ist kurz angehalten“, Auslöser gesperrt |
| Zu viele Uploads | „Langsam! Zu viele Fotos auf einmal. In … s nochmal.“ |
| Kamera nicht erlaubt oder nicht da | „Die Kamera geht nicht“ mit Anleitung |
| Content-Blocker hat Teile der Seite blockiert | Nach 6 s: „Die Seite startet nicht“ mit „Seite neu laden“ |
| Server nicht erreichbar | „Keine Verbindung“ bzw. „Keine Antwort vom Server“ mit „Seite neu laden“ |

Gesperrte und pausierte Gäste prüft die App alle 30 s und bei jedem Zurückkehren zur
Seite neu. Eine Freigabe wirkt also ohne Neuladen.

### Offline und wackliges Netz

- Statuszeile „Offline“, solange das Handy kein Netz hat.
- Fotos warten in der Outbox („1 Foto wartet“, „3 Fotos warten“) und gehen später raus.
- Ein Upload bricht nach 60 s ab. Das Foto bleibt in der Outbox.
- Fehlerseiten unterscheiden „Keine Verbindung“ (Handy offline) und „Keine Antwort vom
  Server“ (Server oder Blocker).
- Beim Zurückkehren zum Tab prüft die App den Status neu.

### Browser und Geräte

- Gebaut für iOS Safari und Android Chrome, dazu Firefox und Desktop-Browser.
- Mindestversionen: Chrome und Edge 111, Firefox 114, Safari und iOS 16.
- Die Browser-Tests laufen in Chromium, Firefox und WebKit (Safaris Engine).
- Die Kamera braucht HTTPS.
- In-App-Browser (Instagram, WhatsApp, Facebook und andere) bekommen oft keine Kamera.
  Die App erkennt sie und rät, den Code mit der Kamera-App zu scannen.
- `?renderer=canvas2d` erzwingt die Canvas2D-Vorschau statt WebGL.
- `?debug=1` blendet auf den Gast-Seiten ein Protokoll ein (für die Fehlersuche am
  Handy).

## 3. Für den Host

Der Admin-Bereich liegt unter `/admin` und braucht keinen QR-Code. Er läuft auf
Laptop und Handy.

### Anmeldung und Sitzungen

- `/admin` führt zu `/admin/live`. Ohne Sitzung geht es zu `/admin/login` und danach
  zurück zur gewünschten Seite.
- Login-Seite: ein Feld „Passwort“, Knopf „Anmelden“.
- **Ein gemeinsames Passwort**, keine Admin-Konten: zuerst das aus
  `VB_ADMIN_PASSWORD`. Ändert der Host es unter [Allgemeines](#allgemeines), gilt
  nur noch das neue; der Server speichert es als scrypt-Hash in der Datenbank, nie im
  Klartext. Im „Protokoll“ hat jede Sitzung eine eigene Kennung („Admin-Sitzung 3f2a“).
- Eine Sitzung hält `VB_ADMIN_SESSION_HOURS` (12 h). Tipp: kurz vor der Party
  anmelden, auf jedem Gerät, mit dem man moderiert.
- „Abmelden“ beendet die Sitzung und ihre Live-Verbindungen sofort.
- Ein neues Passwort im Admin beendet alle anderen Sitzungen samt Live-Verbindungen
  sofort; das Gerät, auf dem es geändert wurde, bleibt angemeldet. Solange keins im
  Admin gesetzt ist, beendet ein geändertes `VB_ADMIN_PASSWORD` alle Sitzungen.
- Passwort vergessen: `virtubooth reset-admin-password` auf dem Server (siehe
  [Kommandozeile](#kommandozeile)) setzt es zurück und meldet alle Geräte ab.
- **Login-Sperre:**
  - Pro IP höchstens 5 Versuche pro Minute und 20 pro Stunde.
  - Nach 20 falschen Passwörtern in 15 Minuten, egal von wo, ist 5 Minuten lang jeder
    Login gesperrt, auch mit dem richtigen Passwort.
  - Die Seite sagt das in Worten: „Zu viele Fehlversuche. Login ist kurz gesperrt.
    Versuch es in … nochmal (um …).“ Der Knopf bleibt so lange aus.
  - Wer angemeldet ist, arbeitet weiter. Ein Neustart des Containers hebt die Sperre
    auf. Logins direkt vom Server (ohne Proxy) sind ausgenommen.

### Live

Die Party-Ansicht für das Handy des Hosts (`/admin/live`), hell wie die Verwaltung.

- Die neuesten Fotos in einem dichten Raster, sie erscheinen sofort.
  - Oben angekommen, rutschen neue Fotos von selbst hinein. Weiter unten erscheint
    „1 neues Foto“ bzw. „… neue Fotos“.
  - Ältere Fotos laden beim Scrollen oder mit „Ältere Fotos laden“.
- Jede Kachel zeigt Bildnummer und Gast. Ausgeblendete tragen ein Fettstift-X.
- **Nur Aus- und Einblenden, kein Löschen.** Ein 44-px-Knopf pro Foto blendet aus oder
  ein. Der Toast („Bier 0012 ausgeblendet“) bietet „Rückgängig“. Ein Fehltipp löscht
  also nie etwas.
- Ein Tipp auf das Foto öffnet es groß: Wischen oder Pfeiltasten für das nächste,
  Details (Gast, Zeit, Gefäß, Filter, Kamera), „Ausblenden“ bzw. „Einblenden“, „Gast
  öffnen“.
- Kopfzeile: „Live“, die Verbindungsanzeige, die Zahl der Fotos und der ausgeblendeten.
- Darunter die [drei Schalter](#die-drei-schalter) und die
  [Live-Zahlen](#übersicht-und-live-zahlen). Auf dem Handy scrollen die Schalter mit;
  ein eingeschalteter Stopp steht dann als Abzeichen in der Kopfzeile.
- [Analyse](#analyse-auf-live) unter jeder Kachel und im großen Foto, mit dem Schalter
  „Analyse zeigen“ in der Kopfzeile.
- Handy: Leiste unten mit „Live“ und „Verwaltung“. Desktop: Knopf „Verwaltung“ oben.

### Die drei Schalter

- **„Hochladen für alle stoppen“** (rot, wenn an), **„Anmeldung stoppen“** (bernstein,
  wenn an) und **„Neue Gäste pausieren“** (bernstein getönt, wenn an): drei echte
  Schalter, immer sichtbar, nie hinter einem Menü.
- Ein Tipp (oder die Leertaste) schaltet sofort, ohne Rückfrage; derselbe Schalter
  schaltet zurück. Schlägt es fehl, kommt ein Toast und der Zustand bleibt.
- Nur das Beenden von „Neue Gäste pausieren“ fragt, falls in der Pause jemand
  beigetreten ist (siehe [Hochladen steuern](#hochladen-steuern)).
- Unter jedem Schalter steht sein Zustand („Alle können hochladen.“, „Gestoppt seit
  22:41.“, „Seit 22:41, 2 Gäste betroffen.“). Sind Gäste pausiert, führt „3 Gäste
  pausiert“ zur gefilterten Gästeliste.
- Wo: auf Live (Desktop in der Kopfzeile nebeneinander, Handy darunter) und in der
  Verwaltung (Desktop unten in der Seitenleiste, Handy oben). Nirgends doppelt, die
  Übersicht hat keine eigene Kopie; sie erklärt die drei unter „Hochladen und
  Anmeldung: was passiert dabei?“.
- Schaltet ein anderes Gerät um, ändern sich alle offenen Admin-Seiten sofort;
  Screenreader sagen es an.

### Analyse auf Live

Nur mit der Live-Wall (sie bringt die Analyse mit).

- Unter jeder Kachel kurze Chips: „3 Personen“, „2 lächeln“, „fröhlich“, „4 Hände“,
  Gesten, Brillen, Hüte, die erkannten Objekte („Flasche, Becher +2“), die Kategorien,
  die das Foto gerade gewinnt, und die Wünsche des Gasts („Keine Auswertung (Gast)“,
  „Keine externe KI“). Solange nichts fertig ist: „Analyse wartet“ bzw. „Analyse
  läuft…“, sonst „Analyse fehlgeschlagen“ oder „Nicht ausgewertet“.
- **Rahmen auf den Kacheln:** jede Kachel zeigt die erkannten Objekte (pink), Gesichter
  (orange) und Hände (grün) als Rahmen über dem Vorschaubild, richtig auf den
  3:4-Ausschnitt umgerechnet (was außerhalb liegt, fällt weg). Große Rahmen tragen
  ihren Namen („Flasche“), kleine nur den Rahmen. Die Legende steht unter dem Schalter.
- Das große Foto zeigt die volle Analyse wie in der Verwaltung: Rahmen für Objekte,
  Gesichter und Hände auf dem Foto, die Objektliste mit Wert und Quelle (Zeigen auf
  ein Objekt hebt seinen Rahmen hervor), Details, Eigenschaftswerte, Kategorien.
- Fertige Analysen kommen über den Ereignisstrom (`photo.analyzed`): die Kachel ändert
  sich ohne Neuladen und ohne Abfragen im Takt. Die Chips laden gebündelt (bis zu 100
  Fotos pro Anfrage, mit den Rahmen: Objekte mit Name, Wert und Rahmen, Gesichter und
  Hände nur als Rahmen, auf drei Stellen gerundet), die volle Analyse erst beim Öffnen.
- „Analyse zeigen“ in der Kopfzeile blendet Chips, Rahmen (auch auf den Kacheln) und
  Analyse aus; der Browser merkt es sich.

### Übersicht und Live-Zahlen

- **Auf Live** stehen sechs Zahlen: „Aktiv jetzt“, „Laden hoch“, „Fotos in 15 min“,
  „Gescannt“, „Nicht beigetreten“, „Gäste“. „Alle Zahlen“ öffnet die Übersicht.
- **Tab „Übersicht“** in der Verwaltung (`?tab=uebersicht`): vier Gruppen und zwei
  Tabellen.
  - „Jetzt (letzte 5 min)“: „Aktiv“, „Laden gerade hoch“, „Gescannt, noch nicht
    dabei“.
  - „Scans“: „Gescannt“, „Beigetreten“, „Nicht beigetreten“, dazu seit wann gezählt
    wird.
  - „Gäste“: „Gesamt“, „Mit Instagram“, „Pausiert“, „Gesperrt“.
  - „Fotos“: „Gesamt“, „Sichtbar“, „Ausgeblendet“, „Letzte 15 min“, „Letzte 60 min“,
    „Letzter Upload“.
  - Tabelle „Aktivitäten“ mit „Fotos“, „Sichtbar“, „Letzte 60 min“ pro Aktivität.
  - Tabelle „QR-Codes“ darunter: „QR-Code“, „Gescannt“, „Personen“, „Beigetreten“,
    „Fotos“, „Aktiv jetzt“ pro Code (die aktiven und gelöschte, die gescannt wurden).
    Eine Zeile öffnet den Code im Tab „QR-Codes“. Nicht auf Live.
  - „Wie wird gezählt?“ erklärt die Zahlen in der App.
- Die Zahlen laden alle 10 s neu, solange die Seite sichtbar ist, und bei passenden
  Ereignissen (z. B. neues Foto, neuer Gast, Sperre, Pause). Eine Zeile nennt das
  Zeitfenster und den Stand.

| Zahl | Bedeutung |
|---|---|
| „Aktiv“, „Aktiv jetzt“ | Gäste, nicht gesperrt, deren Seite in den letzten 5 min offen war. Die Seite meldet sich jede Minute, solange sie sichtbar ist, auch wenn der Gast nichts tut; dazu zählt jede Gast-Anfrage (gespeichert höchstens einmal pro Minute und Gerät) |
| „Laden gerade hoch“, „Laden hoch“ | verschiedene Gäste mit einem Upload in den letzten 5 min |
| „Gescannt, noch nicht dabei“ | Browser mit gültigem QR-Link, nicht beigetreten, in den letzten 5 min gesehen |
| „Gescannt“ | Browser, die einen gültigen QR-Link geöffnet haben (zufällige Besucher-ID) |
| „Beigetreten“ | davon die, die beigetreten sind |
| „Nicht beigetreten“ | gescannt, aber nie beigetreten |
| „Gäste“, „Gesamt“ (Gäste) | alle beigetretenen Geräte, gesperrte eingeschlossen |
| „Mit Instagram“ | Gäste mit Instagram-Namen |
| „Pausiert“ | Gäste mit pausiertem Hochladen, von Hand oder durch „Neue Gäste pausieren“ |
| „Gesperrt“ | gesperrte Gäste |
| „Gesamt“, „Sichtbar“, „Ausgeblendet“ (Fotos) | Fotos, die nicht gelöscht sind |
| „Fotos in 15 min“, „Letzte 15 min“, „Letzte 60 min“ | Uploads in diesem Zeitraum, auch später ausgeblendete oder gelöschte |
| „Letzter Upload“ | Uhrzeit des neuesten Uploads |

- Besucher zählen erst seit dem Update, das den Zähler bringt. Gäste von davor zählen
  erst, wenn ihr Browser wiederkommt. Anfangs kann „Gescannt“ daher kleiner sein als
  „Gäste“.

### Verwaltung

Der Leuchttisch (`/admin/manage`), hell, für den Desktop gedacht, geht aber auch am
Handy.

- Desktop: Seitenleiste mit den Tabs und ihren Zahlen, Verbindungsanzeige, den
  [drei Schaltern](#die-drei-schalter), „Live öffnen“ und „Abmelden“.
- Handy: Kopfzeile mit „Verwaltung“, „Abmelden“ und den drei Schaltern, darunter die
  Tab-Leiste (sie bleibt oben stehen). Unten dieselbe Leiste wie auf Live.
- Reihenfolge: Übersicht · Allgemeines · Fotos · Gäste · Instagram · Fotobox ·
  Live-Wall · ML-Pipeline · Sperren · Protokoll · QR-Codes · Plakat · Export.
- Der Tab steht in der Adresse (`?tab=…`), alte Lesezeichen funktionieren weiter.

| Tab | Adresse | Inhalt |
|---|---|---|
| „Übersicht“ | `?tab=uebersicht` | alle Live-Zahlen, siehe [oben](#übersicht-und-live-zahlen) |
| „Allgemeines“ | `?tab=allgemein` (alt: `einstellungen`) | Eventname, Admin-Passwort, öffentliche Adresse, siehe [Allgemeines](#allgemeines) |
| „Fotos“ | Standard | der Kontaktbogen, siehe unten |
| „Gäste“ | `?tab=gaeste` | die Gästeliste, siehe unten |
| „Instagram“ | `?tab=instagram` | die Liste zum Markieren, siehe [Instagram](#instagram) |
| „Fotobox“ | `?tab=fotobox` | die Fotobox-Filter an und aus, siehe [Fotobox-Filter](#fotobox-filter) |
| „Live-Wall“ | `?tab=livewall` | siehe [Live-Wall](#live-wall) und [Kategorien](#kategorien) |
| „ML-Pipeline“ | `?tab=ml` | Analysen, Testbild, externe KI, Eigenschaften, Budget, siehe [ML-Pipeline](#ml-pipeline-und-externe-ki) |
| „Sperren“ | `?tab=sperren` | gesperrte Gäste und Gerätemerkmale, siehe [Sperren](#sperren-und-gerätemerkmale) |
| „Protokoll“ | `?tab=protokoll` | wer wann was gemacht hat, siehe unten |
| „QR-Codes“ | `?tab=qr` | die QR-Codes mit ihren Zahlen und Exporten, siehe [QR-Codes](#qr-codes) |
| „Plakat“ | `?tab=plakat` | die Plakat-Vorlage und das QR-Feld, siehe [Plakate](#plakate) |
| „Export“ | `?tab=export` | Archiv und Zeitraffer, siehe [Exporte](#exporte) |

**„Fotos“, der Kontaktbogen:**

- Alle Fotos als dichtes Raster. Fettstift-X = ausgeblendet, Kreis = ausgewählt.
- Filter „Aktivität“, „Gast“ (mit Fotozahl) und „Sichtbarkeit“ („Alle“, „Sichtbar“,
  „Ausgeblendet“). Sie stehen in der Adresse.
- Neue Fotos: „1 neues Foto anzeigen“ bzw. „… neue Fotos anzeigen“. „Mehr laden“ für
  ältere.
- **Auswahl:** „Alle auswählen“, Kästchen, Leertaste, Shift-Klick für einen Bereich,
  Strg+A. Solange etwas ausgewählt ist, wählt ein Klick aus, statt zu öffnen.
- Leiste „… ausgewählt“: „Ausblenden“, „Einblenden“ (beide mit „Rückgängig“ im Toast),
  „Löschen…“, „Auswahl aufheben“. Höchstens 200 Fotos pro Aktion.
- **Tastatur:** Pfeiltasten bewegen, Enter öffnet, X blendet aus oder ein, Entf
  löscht (mit Rückfrage), Esc hebt die Auswahl auf.
- **Inspektor** (Desktop, rechts): großes Foto, Gast als Link, Instagram,
  „Aufgenommen“, Gefäß, Filter und Kamera, dazu „Ausblenden“/„Einblenden“,
  „Herunterladen“, „Instagram-Namen kopieren“, „Löschen…“. Am Handy öffnet das Foto
  groß, mit „Ausblenden“/„Einblenden“, „Löschen…“ und „Gast öffnen“.
- **Löschen** fragt immer nach (Knopf „Endgültig löschen“). Die Dateien sind dann weg,
  die Nummer bleibt vergeben.

**„Gäste“:**

- Tabelle mit „Nr.“, „Name“, „Status“, „Instagram“, „Fotos“, „Online“, „QR-Code“,
  „Zuletzt“, „Gerät“. Sortierbar nach Nummer, Name, Fotos, Online, QR-Code und
  Zuletzt.
- „Online“: wie lange die Seite des Gasts sichtbar offen war, zusammengezählt („–“,
  „unter 1 min“, „12 min“, „1 h 05 min“). Ein grüner Punkt heißt: die Seite ist gerade
  offen. Am Handy ausgeblendet.
- „QR-Code“: der Name des Codes, über den der Gast beigetreten ist („Gorilla 2“; „–“
  ohne). Am Handy ausgeblendet.
- Suche nach Name, @instagram oder #Nummer. Filter „Status“: „Alle“, „Gesperrt“,
  „Nicht gesperrt“, „Hochladen pausiert“. Filter „QR-Code“: alle Codes, gelöschte mit
  „(gelöscht)“; er steht in der Adresse (`&code=<Nr.>`).
- Status als Abzeichen: „Gesperrt“, „Automatisch gesperrt“, „Hochladen pausiert“,
  dazu die eigenen Wünsche des Gasts: „Gast möchte keine Auswertung“ und „Keine externe
  KI“.
- „Name“ ist der angezeigte Name; die Gästeseite zeigt Nummer, Zufallsname und
  Anzeigenamen und kann einen Anzeigenamen zurücksetzen.
- Ein Klick auf eine Zeile öffnet die [Gästeseite](#gästeseite).

**„Protokoll“:**

- Jede Admin-Aktion mit „Zeit“, „Aktion“, „Ziel“, „Details“ und „Wer“, neueste zuerst,
  100 pro Seite, „Ältere Einträge“.
- Erfasst werden: Fotos aus- und einblenden und löschen, Gäste und Gerätemerkmale
  sperren und entsperren, Pausen und Stopps, Anmeldung stoppen und öffnen,
  Instagram-„Erledigt“, Exporte starten und löschen, QR-Codes anlegen, ändern und
  löschen, Eventname, Fotobox-Filter, Plakat-Vorlage und QR-Feld, Admin-Logins,
  Abmeldungen, Passwortänderungen und falsche Passwörter (mit IP).
- Ziele sind Links: „Gast #12“, „Foto ansehen“, „QR-Code 2“. Gelöschte Fotos heißen
  „Foto (gelöscht)“.

### Gästeseite

Ein Gast im Detail: `/admin/user?id=<Nr.>`, erreichbar aus Live, Fotos, Gäste,
Instagram, Sperren und dem Protokoll.

- Pseudonym, Instagram-Name als Link zum Profil mit Kopier-Knopf, seit wann dabei.
- Eine Statuszeile, z. B. „Darf hochladen. 12 Fotos, davon 2 ausgeblendet.“, „Hochladen
  pausiert. …“, „Gesperrt seit 22:41: Grund. …“, „Automatisch gesperrt seit …“.
  - Bei Pausen: warum (von Hand oder durch „Neue Gäste pausieren“).
  - Ist Hochladen gerade für alle gestoppt, steht das darunter.
  - Bei automatischer Sperre: über welches Gerätemerkmal und welchen Gast.
- Schalter **„Hochladen pausieren“** für diesen Gast. Keine Sperre: seine Fotos
  bleiben sichtbar.
- **„Sperren…“** bzw. **„Entsperren…“** öffnen ein Sheet, siehe
  [Sperren](#sperren-und-gerätemerkmale).
- **„Statistik“:** „Online“ („1 h 12 min in 3 Besuchen“, dazu „gerade online“; ein
  Besuch endet, wenn die Seite verborgen wird oder sich 150 s nicht meldet),
  „QR-Code“ (der Code des Beitritts, z. B. „Gorilla 2“, als Link zum Code; mit
  „gelöscht“, wenn er gelöscht ist; „unbekannt“ ohne), „Fotos“
  pro Aktivität („12: Beer Cam 8, Fotobox 4“), „Ausgeblendet“ und „Gelöscht“ (wenn es
  welche gibt), „Erstes Foto“, „Letztes Foto“, „Dabei seit“, „Zuletzt gesehen“.
- Die Fotos des Gasts; groß mit „Ausblenden“/„Einblenden“ und „Löschen…“.
- „Technische Details“, eingeklappt: Gerät, Bildschirm, Grafik, Sprache, Zeitzone,
  Leistung, IP-Adresse (erste und letzte), „Zuletzt gesehen“, „Erstmals da“,
  „Einwilligung“ (Zeit und Version), „Gast-Nr.“, „Gerätemerkmale“ mit den anderen
  Geräten, die dasselbe Merkmal haben, und „User-Agent“.

### Als Gast teilnehmen (Admin-Gast)

Der Host kann selbst als Gast mitmachen, ohne QR-Code: **„Als Gast teilnehmen“** in der
Seitenleiste der Verwaltung (unter „Live öffnen“) und in „Gäste“ (unter den Filtern, mit
Erklärung). Gibt es den Admin-Gast schon, heißt der Knopf **„Als Gast öffnen“**.

- Der Knopf meldet diesen Browser in der Gäste-App als **Admin-Gast** an und öffnet sie in
  einem neuen Tab; die Verwaltung bleibt offen (dieselbe Domain: dieselben Cookies).
  Kein Token in der URL: Die Admin-Sitzung ist der Nachweis.
- Es gibt **einen** Admin-Gast pro Party (das Admin-Passwort ist geteilt, es gibt keine
  einzelnen Admins). Er wird beim ersten Druck angelegt; jeder weitere Druck, auch auf
  einem anderen Gerät, meldet diesen Browser als denselben Gast an.
- Er ist ein normaler Gast: Fotos, „Deine Bilder“, Live-Wall, Kategorien, Opt-outs.
  Anzeigename „Gastgeber“ (für andere Gäste reserviert; er darf ihn ändern und
  zurückholen), kein Instagram-Name. Auf der Live-Wall und für andere Gäste sieht er aus
  wie jeder Gast; nur sein eigener Gästepass zeigt „Admin-Gast · nur du siehst das“.
- Ausnahmen: kein Foto-Limit (`VB_MAX_PHOTOS_PER_GUEST`), nie von „Neue Gäste
  pausieren“ erfasst, „Anmeldung stoppen“ hält ihn nicht auf. **„Hochladen stoppen“
  gilt auch für ihn** (der Stopp ist für alle; der Hinweis unter dem Knopf sagt das).
  Von Hand pausieren lässt er sich wie jeder Gast.
- **Nicht sperrbar:** Auf seiner Gästeseite ist „Sperren…“ aus, daneben steht warum;
  die API antwortet 409 `host_guest`.
- **Kein QR-Code:** `code_id` bleibt leer, er bekommt kein Zugangs-Cookie und keine
  Besucher-ID. Er zählt bei keinem Code (Gescannt, Personen, Beigetreten, Fotos) und
  nicht bei „Gescannt“/„Beigetreten“ der Übersicht; bei „Gäste“ zählt er mit. Löschen
  oder neue Tokens für QR-Codes sperren ihn nie aus: Die signierte Gast-ID genügt.
- In der Verwaltung markiert: Abzeichen „Admin-Gast“ in der Gästeliste und auf der
  Gästeseite, „über die Verwaltung (beigetreten)“ statt des QR-Codes, „<Name> ·
  Admin-Gast“ an seinen Fotos (Live, Fotos, Inspektor, Großansicht), Spalte `is_host`
  in `users.csv` des Exports.
- War dieser Browser schon als anderer Gast angemeldet, wird diese Anmeldung ersetzt
  (der andere Gast bleibt bestehen). Der Hinweis unter dem Knopf sagt das vorher, ein
  Toast danach.
- Protokoll: `host_guest.sign_in` mit „created“ und, wenn ersetzt, der vorherige Gast.

### Hochladen steuern

Die Hebel, unabhängig voneinander und von Sperren (die ersten beiden sind
[Schalter](#die-drei-schalter) auf Live und in der Verwaltung):

- **„Hochladen für alle stoppen“** (Notschalter): Niemand kann hochladen, auch bekannte
  Gäste nicht. Für kurze Pausen, etwa bei einer Flut unpassender Fotos. Einzelne Pausen
  bleiben, wie sie sind.
- **„Neue Gäste pausieren“:** Wer ab jetzt beitritt, kann erst hochladen, wenn ihr
  freigebt. Bekannte Gäste laden weiter hoch.
  - Beim Ausschalten fragt ein Dialog, falls jemand in der Pause beigetreten ist:
    „Freischalten“ bzw. „Alle … freischalten“, „Pausiert lassen“ bzw. „Alle …
    pausiert lassen“, oder „Pause weiterlaufen lassen“.
  - Freischalten gilt nur für die Gäste aus dieser Pause. Von Hand pausierte bleiben
    pausiert.
- **Einzelne Gäste:** auf der Gästeseite mit „Hochladen pausieren“.
- „3 Gäste pausiert“ unter den Schaltern führt zur Gästeliste, gefiltert auf
  „Hochladen pausiert“; freigegeben wird auf der Gästeseite.
- Pausierte Gäste können sich weiter umsehen und ihren Instagram-Namen ändern.
- Ein Gast, der selbst pausiert ist, hört von seiner Pause, nicht vom allgemeinen Stopp.
- Alles bleibt über einen Neustart erhalten.

### Anmeldung stoppen

- Der Schalter „Anmeldung stoppen“: Niemand Neues kann beitreten.
- Wer schon dabei ist, macht weiter: Fotos, Hochladen, „Deine Bilder“, ein zweiter
  Tab. Hochladen folgt nur den Hochladen-Schaltern.
- Neue Geräte sehen im Beitritts-Sheet statt des Knopfs „Gerade kann niemand neu
  beitreten.“ und „Versuch es gleich noch mal. Sobald es wieder geht, erscheint der
  Knopf von selbst.“ mit „Nochmal versuchen“.
- Das Sheet prüft alle 15 s und bei jedem Zurückkehren zur Seite neu. Ist die
  Anmeldung wieder offen, erscheint der Knopf ohne Neuladen.
- Derselbe Schalter beendet den Stopp. Der Zustand bleibt über einen
  Neustart erhalten und steht im Protokoll („Anmeldung gestoppt“, „Anmeldung wieder
  offen“).

### QR-Codes

- **Tab „QR-Codes“** (`?tab=qr`): alle Codes mit „Nr.“, „Name“, „Ziel“, „Notiz“,
  „Gescannt“, „Personen“, „Beigetreten“, „Fotos“, „Online“ (die Online-Zeit seiner
  Gäste zusammen; nur auf breiten Bildschirmen), „Zuletzt gescannt“ und „Status“.
  Oben die Zahl, z. B. „3 aktiv · 1 gelöscht“. Die Zahlen laufen alle 15 s und bei
  jeder Änderung mit.
- **Nummer und Name:** Jeder Code hat eine feste Nummer und einen Tiernamen, z. B.
  „Gorilla 2“. Nummern werden nie neu vergeben, Namen ändern sich nie. Die Tiere
  kommen aus einer Liste von 100, ohne die Tiere der Gast-Pseudonyme.
- **Code 1** entsteht beim ersten Start aus `VB_PARTY_TOKEN` (ohne die Variable mit
  einem neuen Token). Alle Gäste und Scans von vorher zählen für ihn. Danach liest der
  Server die Variable nicht mehr: Tokens ändert man nur noch hier.
- **„Neuer QR-Code“:** „Ziel“ (Start oder eine Aktivität), „Notiz (freiwillig)“, bis 60
  Zeichen, z. B. „Eingang“, und das Token: „Neu erzeugen“ oder „Eigenes“.
- **Token ändern:** „Token ändern…“ im Code. Der bisherige Code (gedruckt oder
  geteilt) funktioniert danach nicht mehr; wer darüber beigetreten ist, bleibt dabei.
- **Gedruckten Code übernehmen:** Bei „Eigenes“ den gedruckten Code mit dem Handy
  scannen und den Link einfügen. Das Token kommt aus dem Link, ein Ziel wie
  `/x/booth/` auch. Zeigt der Link auf eine andere Adresse als die Party, warnt das
  Sheet. Ein eigenes Token braucht 16 bis 128 Zeichen aus A–Z, a–z, 0–9, `_` und `-`,
  mindestens 6 verschiedene. Kein Token wird je zweimal vergeben, auch keins, das ein
  Code früher hatte.
- **„Bearbeiten…“:** Ziel und Notiz. Sie ändern nur den Link, den Exporte drucken, und
  die Tabelle. Ist eine Aktivität nicht mehr geladen, steht „Ziel nicht verfügbar“ da
  und der Link führt zu Start.
- **„Löschen…“** fragt nach. Der Code bleibt grau in der Liste, mit Nummer, Name und
  Zahlen, sein Token funktioniert nicht mehr. „Gelöschte zeigen“ blendet gelöschte
  Codes ein. Auch den letzten aktiven Code kann man löschen, das Sheet warnt dann:
  Danach kommt niemand Neues mehr auf die Party.
- **Code-Sheet:** Klick auf eine Zeile oder `?tab=qr&code=<Nr.>` öffnet den Code mit
  Link („Link kopieren“), Token, Ziel, Notiz, „Angelegt“ und den Zahlen: „Gescannt“
  (z. B. „12-mal von 9 Personen“), „Beigetreten“, „Noch nicht beigetreten“, „Fotos“
  (ihrer Gäste), „Aktiv jetzt“, „Online-Zeit zusammen“, „Gerade online“, „Zuerst
  gescannt“, „Zuletzt gescannt“. „Gäste über diesen Code anzeigen“ öffnet die
  gefilterte Gästeliste (`?tab=gaeste&code=<Nr.>`).
- **Exporte pro Code** (nur aktive Codes), im Sheet: „QR als PNG“ (mindestens
  1600 px), „QR groß (PDF)“ (A4, etwa 17 cm) und „Plakat (PDF)“, mit der Vorlage aus
  dem Tab „Plakat“, sonst das Standard-Plakat (siehe [Plakate](#plakate)). Die Dateien
  heißen z. B. `qr-02-gorilla.png`, `qr-02-gorilla-gross.pdf`, `plakat-02-gorilla.pdf`.
  Ist das Ziel eine Aktivität, steht ihr Titel als Untertitel auf dem großen QR und
  dem Standard-Plakat.
- Alle Codes und Plakate nehmen die [öffentliche Adresse](#allgemeines). Ist sie
  nicht geprüft oder nicht erreichbar, warnt der Tab: „Die öffentliche Adresse ist
  nicht geprüft oder nicht erreichbar. Prüfe sie unter „Allgemeines“, bevor du
  druckst.“
- Jeder Gast gehört zu dem Code, über den er beigetreten ist, und bleibt dabei.
- Anlegen, Bearbeiten, Token ändern und Löschen stehen im Protokoll, nie mit dem
  ganzen Token (nur „Token endet auf“).

### Sperren und Gerätemerkmale

- **Gast sperren:** „Sperren…“ auf der Gästeseite öffnet ein Sheet mit dem Namen und
  der Frage.
  - Das Sheet sagt vorher, was passiert, z. B. „Alle 4 sichtbaren Fotos werden
    ausgeblendet, weitere Uploads sind blockiert.“
  - Feld „Grund (freiwillig, nur für euch)“, höchstens 200 Zeichen.
  - Option „Gerätemerkmal auch sperren“, mit Warnung und der Zahl anderer Geräte mit
    demselben Merkmal. Knopf dann „Gast und Merkmal sperren“, sonst „Sperren“.
  - Gesperrte Gäste sehen „Gesperrt“, können nichts hochladen und keinen
    Instagram-Namen ändern.
- **Gerätemerkmal-Sperre:** Neue Geräte mit diesem Merkmal starten gesperrt
  („Automatisch gesperrt“). Bereits bekannte Gäste sind nicht betroffen. Gleiche
  Handymodelle haben oft dasselbe Merkmal, das kann also Unbeteiligte treffen.
- **Entsperren:** „Entsperren…“ öffnet ein Sheet mit dem Namen und der Frage.
  - Nur die Fotos, die durch die Sperre ausgeblendet wurden, kommen zurück. Von Hand
    ausgeblendete bleiben ausgeblendet.
  - Option „Gerätemerkmal-Sperre auch aufheben“. Das entsperrt auch alle Geräte, die
    nur wegen dieses Merkmals gesperrt sind.
  - Bei automatisch gesperrten Gästen gilt Entsperren nur für dieses Gerät.
- **Tab „Sperren“:** „Gesperrte Gäste“ (Gast, Grund, Seit, Fotos) und „Gesperrte
  Gerätemerkmale“ (Merkmal, Grund, Seit, „Gesperrt über“, Geräte, davon nur deshalb
  gesperrt), je mit „Entsperren“. „Was ist ein Gerätemerkmal?“ erklärt es.
- Auf der Gästeseite lässt sich ein einzelnes gesperrtes Merkmal unter „Technische
  Details“ mit „Gerätemerkmal entsperren“ aufheben.
- Ein Foto, das eine Sperre ausgeblendet hat, kann man von Hand wieder einblenden. Der
  Gast bleibt gesperrt.

### Instagram

Der Tab „Instagram“ ist die Liste für nach der Party: wen markieren, welche Fotos
posten.

- Eine Zeile pro Instagram-Name, mit Link zum Profil, Zahl der sichtbaren und
  ausgeblendeten Fotos, letztem Upload, den Gästen dahinter und den 8 neuesten
  sichtbaren Fotos.
- Anzeige „Offen“, „Erledigt“ oder „Alle“.
- **„Erledigt“** abhaken, wenn gepostet und markiert ist. Der Toast bietet
  „Rückgängig“. Die Marke bleibt über einen Neustart erhalten.
- **„Fotos als ZIP“** pro Name: alle sichtbaren Fotos in Upload-Reihenfolge
  (`fotos-<name>.zip`). Fotos gesperrter Gäste sind nie dabei.
- „Kopieren“ pro Name, „Alle Namen kopieren“ für alle (ohne Namen, hinter denen nur
  gesperrte Gäste stehen).
- Fotos öffnen sich groß, mit „Ausblenden“/„Einblenden“.

### Exporte

Im Tab „Export“. Die Dateien entstehen als Hintergrund-Jobs auf dem Server, einer nach
dem anderen. Man kann die Seite verlassen.

| Export | Optionen | Ergebnis |
|---|---|---|
| „Archiv erstellen“ | „Ausgeblendete Fotos mitnehmen“, „Datenbank mitnehmen (für ein Backup)“ | ZIP: Fotos pro Aktivität (ausgeblendete im Unterordner `hidden/`), `photos.csv`, `users.csv`, `instagram.csv`, `manifest.json`, `README.txt`, optional eine Kopie der Datenbank |
| „Zeitraffer erstellen“ | „Aktivität“, „Fotos pro Sekunde“ (6, 8, 12, 15, 24, 30; Standard 12), „Weich überblenden“, „Ausgeblendete Fotos mitnehmen“ | MP4 (H.264), 1080 × 1440, Fotos in Upload-Reihenfolge, das letzte 2 s lang. Gelöschte Fotos nie |

- Liste „Erstellte Exporte“ mit Status („Wartet…“, Fortschrittsbalken „Wird
  erstellt…“, Fehler in Worten), „Herunterladen“, „Abbrechen“ (solange er wartet) und
  Löschen (mit Rückfrage; nicht, solange er läuft).
- Pro Art läuft höchstens ein Job. Ein zweiter Start sagt „Läuft schon: … ist bereits
  in Arbeit.“
- Die neuesten 10 fertigen Dateien bleiben, ältere werden gelöscht.
- Vor dem Schreiben prüft der Server den freien Platz.
- Ohne ffmpeg: „Auf dem Server fehlt ffmpeg, darum geht der Zeitraffer gerade nicht.“
  Im Docker-Image ist ffmpeg dabei.
- Ein Neustart beendet laufende Jobs mit „Server wurde neu gestartet.“
- **Kein QR-Bogen mehr** im Admin (alte Jobs dieser Art sind ausgeblendet); der Bogen
  bleibt über die Kommandozeile (`virtubooth qr`).
- **Einzelne Codes und Plakate** gibt es im Tab „QR-Codes“: „QR als PNG“, „QR groß
  (PDF)“, „Plakat (PDF)“ im Sheet jedes Codes (siehe [QR-Codes](#qr-codes)). Sie
  entstehen sofort im Browser, ohne Job.
- **`users.csv`** hat pro Gast auch den Anzeigenamen (`display_name`), die Online-Zeit
  (`online_seconds`, `online_sessions`) und den QR-Code des Beitritts (`code`, der
  Name); `photos.csv` hat den Anzeigenamen ebenfalls.
- **Datenbank im Archiv** ohne den API-Schlüssel der externen KI (`x.llm.key`) und ohne
  jeden Einstellungs-Schlüssel auf `.secret`.
- **Datenbank im Archiv:** eine konsistente Kopie, ohne Admin-Sitzungen, Export-Jobs
  und Besucher-IDs (auch nicht pro QR-Code), so bereinigt, dass früher Gelöschtes
  nicht mehr lesbar ist. Sie enthält Gäste mit IPs und Gerätemerkmalen, die QR-Codes
  mit ihren Tokens und den Hash des Admin-Passworts.
- Die Kommandozeile kann dasselbe mit mehr Optionen, siehe
  [Kommandozeile](#kommandozeile).

### Plakate

Im Tab „Plakat“ (`/admin/manage?tab=plakat`). Hier entsteht das Plakat, auf dem der
QR-Code hängt.

- **Eigene Vorlage:** „PDF-Vorlage hochladen“ (am Computer auch „PDF hierher ziehen“),
  höchstens 8 MB. Die PDF liegt auf dem Server, jedes Admin-Gerät sieht dieselbe. Hat
  sie mehrere Seiten, wählt man unter „Seite“ die eine, die das Plakat wird. Eine neue
  Vorlage ersetzt die alte, „Vorlage entfernen…“ löscht sie (mit Rückfrage).
- **Das grüne Feld** zeigt, wo der QR-Code hinkommt: ziehen verschiebt es, die Ecke
  unten rechts ändert die Größe. Es bleibt quadratisch und ganz auf der Seite. Das geht
  mit der Maus, mit dem Finger auf dem Handy (nur das Feld fängt die Berührung, die
  Seite scrollt sonst normal) und mit der Tastatur: Pfeiltasten verschieben um 1 %, mit
  Umschalt um 5 %, Plus und Minus ändern die Größe. „Speichern“ merkt sich das Feld,
  „Änderungen verwerfen“ holt das gespeicherte zurück, „Nicht gespeichert“ zeigt
  offene Änderungen.
- **Probedruck (PDF):** das Plakat mit dem Eventnamen, auch mit ungespeicherten
  Änderungen. „Code für den Probedruck“ wählt einen aktiven QR-Code oder „Muster“
  (Standard): Der Muster-Code („Muster 0“) führt nur zur Startseite ohne Zugang.
- **Ohne Vorlage** gibt es das Standard-Plakat im Kontaktbogen-Stil: Filmstreifen oben
  und unten, der Name der Party groß, der QR-Code im Rahmen mit Fettstift-Kreis,
  „Handy-Kamera drauf halten und los!“. „Standard-Plakat ansehen (PDF)“ zeigt es mit
  dem Muster-Code.
- **Exporte pro Code:** der Code als PNG (mindestens 1600 px), der große QR-Code als
  PDF (A4, etwa 17 cm) und das Plakat als PDF (eine Seite: die Vorlage mit dem Code im
  grünen Feld, sonst das Standard-Plakat). Die Knöpfe „QR als PNG“, „QR groß (PDF)“
  und „Plakat (PDF)“ stehen im Sheet jedes aktiven Codes im Tab
  [„QR-Codes“](#qr-codes). Ohne gespeichertes QR-Feld gibt es das Standard-Plakat.
- Jedes PDF trägt klein unten rechts den Namen des Codes („Gorilla 2“), damit man die
  Ausdrucke auseinanderhält. Das Token steht nur im Code, nie als Text.
- Alles entsteht im Browser des Admins; der Server speichert nur die Vorlage und das
  Feld. Hochladen, Feld setzen und Entfernen stehen im Protokoll.

### Live-Wall

Die Fotos der Party auf einem großen Bildschirm: ein Fernseher oder Beamer öffnet
`/livewall` im Browser. Die Live-Wall ist eine Erweiterung (`wall`) ohne eigene
Aktivität; sie steht nicht auf Start. Einstellungen im Tab „Live-Wall“ der Verwaltung
(`/admin/manage?tab=livewall`).

- **Zugang:** Unter „Zugang“ setzt der Host ein Live-Wall-Passwort (mindestens 12
  Zeichen; ein früher gesetztes kürzeres gilt weiter, sollte aber vor einer Party im
  Internet geändert werden). Der Bildschirm fragt einmal danach („Live-Wall starten“) und merkt sich das
  30 Tage (Cookie nur für `/livewall`). Ohne Passwort zeigt `/livewall` „Für die
  Live-Wall ist noch kein Passwort gesetzt.“ Ein eingeloggter Admin sieht die Wall auch
  ohne Passwort. Passwort ändern, entfernen oder „Alle Wände abmelden“ meldet jede
  offene Wand sofort ab. „Live-Wall öffnen“ öffnet sie in einem neuen Tab; die Zahl der
  offenen Wände steht daneben. Falsche Passwörter: höchstens 5 pro Minute und 20 pro
  Stunde je Adresse, jedes im Protokoll. Nach 20 falschen Passwörtern in 15 Minuten,
  egal von wo, ist die Anmeldung 5 Minuten lang für alle gesperrt („Zu viele
  Fehlversuche“), auch mit dem richtigen Passwort; angemeldete Wände laufen weiter.
- **Ablauf:** drei Modi im Wechsel, Reihenfolge und Dauer frei (10 s bis 1 h, mindestens
  einer an):
  - **Einzelbild:** ein Foto groß mit „von <Name>“ (Anzeigename, sonst „@Instagram“,
    wenn die Wall Instagram-Namen zeigt, sonst der Zufallsname), optional dem Instagram-Namen
    und dem Alter („vor 3 Min.“). Wechsel alle 3 bis 120 s, eine Runde zeigt N Fotos.
  - **Galerie:** eine endlose Fotowand, 2 bis 6 Reihen, langsam, mittel oder schnell.
  - **Kategorien:** die Gewinner der lustigen [Kategorien](#kategorien), je 4 bis 60 s,
    1 bis 10 Gewinner in der Reihenfolge des Servers, darunter das Urteil der KI, wenn
    die Kategorie eins hat.
- **Auswahl im Einzelbild:** „Die neuesten N im Kreis“, „Zufällig“, „Gemischt, ohne
  Wiederholung“, „Fair: jeder Gast reihum“, „Selten gezeigte zuerst“, „Neue Fotos
  sofort, sonst gemischt“ (Standard) und „Kategorie-Highlights“.
- **Übergänge:** Überblenden, Langsamer Zoom, Federnd, Pixelrauschen, Verpixeln,
  Glitch, Polaroid-Fall, Spielautomat, Wackelpudding, Stempel, Konfetti oder „Zufall
  (alle gemischt)“; Dauer 0,3 bis 4 s. Kann ein Fernseher kein WebGL, wird überblendet.
- **Aussehen:** Hintergrund „Farbblasen“ (Standard), „Polarlicht“, „Disco-Gitter“,
  „Konfetti-Regen“ oder „Ruhig (ohne Animation)“; Haupt-, Zweit- und Hintergrundfarbe;
  30 oder 60 Bilder pro Sekunde; „ruhig“ dämpft die Bewegung. Die Vorschau im Admin
  zeigt den Hintergrund.
- **Einblendungen:** Eventname, Fotozähler und ein QR-Code in einer wählbaren Ecke.
  Der QR-Code ist einer der [QR-Codes](#qr-codes) („Erster aktiver Code“ oder ein
  bestimmter); wird er gelöscht, verschwindet er von der Wall. Eventname und Code
  ändern sich auf offenen Wänden sofort mit.
- **Fotos:** neue Fotos erscheinen nach einer Verzögerung (Standard 20 s, 0 bis 600 s),
  damit der Host vorher ausblenden kann. Quellen: alle Aktivitäten oder eine Auswahl;
  eine ausgewählte Aktivität, die nicht mehr geladen ist, zählt nicht (bleibt keine
  übrig, gelten alle). Instagram-Namen nur, wenn eingeschaltet; ändert ein Gast seinen
  Namen, ändern ihn offene Wände sofort mit. Ausblenden, Löschen und Sperren nehmen
  Fotos sofort von jeder Wand; die 1280-px-Kopie eines gelöschten Fotos verschwindet
  mit ihm. Es zählen die neuesten 1000 Fotos.
- „Speichern“ übernimmt alle Einstellungen auf allen offenen Wänden sofort;
  „Verwerfen“ holt die gespeicherten zurück.
- Der Bildschirm: Vollbild-Knopf (verschwindet ohne Bewegung), hält den Bildschirm
  wach, wo der Browser es erlaubt (nur über https oder localhost; sonst den
  Bildschirmschoner des Fernsehers ausschalten). Bricht die Verbindung ab, verbindet er
  sich selbst neu und holt nach, was er verpasst hat; hat der Server selbst Ereignisse
  verpasst, laden alle offenen Wände ihre Fotos neu.
- Grenzen je Wand (Cookie): höchstens 4 offene Verbindungen (eine fünfte schließt die
  älteste), 120 Abrufe pro Minute und 1200 Bilder pro Minute.

### Fotoanalyse

Für die Kategorien der Live-Wall wertet ein eigener Prozess auf dem Server jedes Foto
**einmal** aus. Ohne [externe KI](#ml-pipeline-und-externe-ki) verlässt nichts davon den
Server.

- **Immer:** Bildwerte mit Pillow (Helligkeit, Farbigkeit, Schärfe), dazu die Details
  „Aufgenommen“, „Quelle“, Filter bzw. Gefäß, „Gast“, „QR-Code“ und „Größe“.
- **Mit dem KI-Paket** (Docker-Image mit `VB_ML=1`, auf Coolify Standard, lokal
  `make models`) und den Modellen (Admin → ML-Pipeline → „Modelle herunterladen“;
  [DEPLOY.md → Live-Wall](DEPLOY.md#live-wall-and-photo-analysis)):
  „Gesichter“, „Gesichtsausdruck“, „Hände und Gesten“, „Objekte“ (EfficientDet-Lite2,
  alle 80 COCO-Klassen mit deutschen Namen, z. B. „Weinglas“, „Sonnenbrille“),
  „Brillen, Hüte, Altersgruppe“ und „Alter (FairFace)“ (aus, bis der Host es
  einschaltet). Gespeichert werden nur Zahlen pro Foto, die **Objektliste** (Name,
  Sicherheit, Rahmen, Quelle) und Rahmen um Gesichter und Hände: keine
  Gesichtsmerkmale, nichts, was eine Person wiedererkennt. „Personen“ zählt der
  Objekt-Detektor, ohne ihn die Gesichter.
- **Eingefroren:** „Analysen werden einmal gemacht und danach nicht mehr verändert.“
  Kein „Neu analysieren“, keine Neu-Analyse nach Updates. Eine abgestürzte Analyse wird
  bis zu dreimal versucht, bevor das Foto als fehlgeschlagen gilt. Analysen an/aus und
  ihre Einstellungen (z. B. beim Objekt-Detektor „Mindest-Sicherheit“ und „Höchstens
  Objekte“) gelten nur für danach analysierte Fotos. Dazukommen kann nur etwas: Objekte
  der externen KI werden an die Liste angehängt.
- **Analyse im Foto-Inspektor** (Verwaltung): Zustand, gefundene Werte, die Objektliste
  mit Quelle („lokal“ oder der KI-Dienst), die Rahmen, die Details und die Werte der
  [Eigenschaften](#ml-pipeline-und-externe-ki) pro Objekt. Die aktuellen Wünsche des
  Gasts stehen dabei („Gast möchte keine Auswertung“, „Keine externe KI“).
- Der Prozess läuft mit niedriger Priorität, ein Foto nach dem anderen, das neueste
  zuerst, startet bei einem Absturz neu und beginnt nach 200 Fotos oder 900 MB frisch.
  Uploads werden dadurch nicht langsamer (Lasttest: 20 Gäste × 3 Fotos gleichzeitig,
  Upload-p95 mit und ohne Analyse gleich, nie mehr als ein Foto in Arbeit). Gelöschte
  Fotos verlieren ihre Analyse, Objekte, Werte und Urteile.
- **Abschalten durch den Gast:** „Meine Fotos nicht automatisch auswerten“ im
  Beitritts-Sheet unter „Mehr dazu“ und im Du-Sheet. Fotos aus dieser Zeit bekommen nur
  die Bildwerte. Solange der Schalter an ist, fallen **alle** Fotos des Gasts aus allen
  Kategorien, Abfragen, Urteilen und der externen Erkennung; schon Gefundenes bleibt
  gespeichert, der Admin sieht es mit „Gast möchte keine Auswertung“. Umschalten ändert
  nur den Schalter. Gäste können eigene Fotos unter „Deine Bilder“ löschen.

### Kategorien

Kategorien sind Regeln, keine feste Liste. Im Tab „Live-Wall“ zeigt die Karte
„Kategorien“ jede mit Schalter, Reihenfolge (↑/↓), den aktuellen Gewinnern und, wenn
nichts gewinnen kann, warum (z. B. „Braucht die Analyse …“).

- **Eine Kategorie:** Emoji, Titel (1–40 Zeichen), Zeile (bis 80), „Bedingungen“ (bis
  8, alle müssen gelten), „Auswahl: Top / Bottom“ nach einem Wert, „Anzahl“ (1–10),
  bis zu zwei Werte bei Gleichstand, „Ein Foto pro Gast“, die Beschriftung auf der Wall
  (Anzahl, Prozent, Zahl, Uhrzeit, fester Text oder der Name des besten Objekts) und
  optional „Urteil der KI (Prompt)“. Bei Gleichstand gewinnt das neuere Foto.
- **Werte:** jeder Analysewert (Personen, Lächeln, Hände, Gesten, Schärfe, Farbigkeit
  …), die Objektliste, „Anzahl von <Objekt>“, die Werte der Eigenschaften (höchster,
  niedrigster, Summe, Durchschnitt, Anzahl bewerteter Objekte, Wert eines bestimmten
  Objekts), Aufnahmezeit und Fotos des Gasts.
- **Vergleiche:** > < ≥ ≤ = ≠, „zwischen“, „existiert“, „existiert nicht“, „enthält“,
  „enthält nicht“, „enthält eins von“.
- „Kategorie bearbeiten“ zeigt „Vorschau: aktuelle Gewinner“ und wie viele Fotos
  passen, während man tippt. Fehler stehen am Feld.
- **Vorlagen:** die 19 bisherigen Kategorien als Regeln mit denselben Gewinnern
  (geprüft gegen die alte Berechnung), dazu „Das coolste Objekt“ 🏆 (aus; braucht die
  Eigenschaft `coolness` und hat ein Urteil der KI). Vorlagen lassen sich ändern und
  löschen; „Vorlagen wiederherstellen“ holt gelöschte zurück. Beim ersten Start wurden
  die früher ausgeschalteten Kategorien übernommen.
- Gewinner sind nur sichtbare Fotos nach der Verzögerung, nie von Gästen mit
  „Meine Fotos nicht automatisch auswerten“.
- Keine Vorlage nennt die älteste oder jüngste Person oder bewertet Aussehen.

| | Vorlage | Zeile | Gewinnt |
|---|---|---|---|
| 👥 | Volles Haus | Die meisten Leute auf einem Foto | die meisten Personen (ab 3) |
| 🙌 | Hände hoch! | Die meisten Hände in der Luft | die meisten Hände (ab 3) |
| 😁 | Grinsekatzen | Die meisten Lächeln auf einem Bild | die meisten Lächeln (ab 2) |
| 🥺 | Herzschmerz-Pose | Der dramatischste Schmollblick des Abends | der traurigste Ausdruck (ab 50 %) |
| 😱 | Ach du Schreck! | Das überraschteste Gesicht | der überraschteste Ausdruck (ab 50 %) |
| 🤓 | Brillenbande | Die meisten Brillen auf einem Foto | die meisten Brillen (ab 1) |
| 🎂 | Generationen-Foto | Die größte Altersspanne auf einem Bild | die meisten Altersgruppen (ab 2), dann die Spanne |
| 👯 | Dream-Team | Zwei Leute, doppelt gute Laune | 2 Personen, 2 Lächeln |
| 🌟 | Solo-Star | Ganz nah dran | ein Gesicht, möglichst groß (ab 12 % des Bildes) |
| ✌️ | Peace! | Die meisten Victory-Zeichen | Peace-Zeichen (ab 1) |
| 🤘 | Rock'n'Roll | Die meisten Pommesgabeln | Pommesgabeln (ab 1) |
| 👍 | Daumen hoch | Die meisten Daumen nach oben | Daumen hoch (ab 1) |
| 🥂 | Prost! | Die meisten Gläser im Bild | Gläser (ab 2) |
| 🎩 | Hutparade | Die meisten Hüte und Kappen | Hüte (ab 1) |
| 🎤 | Gesangseinlage | Die meisten offenen Münder | offene Münder (ab 2) |
| 🌈 | Farbexplosion | Das bunteste Foto | die höchste Farbigkeit (ab 40) |
| 💨 | Action-Shot | So viel Bewegung, die Kamera kam kaum mit | das unschärfste, nicht zu dunkle oder helle Foto |
| 🎬 | Eröffnungsfoto | Das allererste Foto des Abends | das erste Foto |
| 📸 | Dauerauslöser | Die meisten Fotos von einer Person (hier das neueste) | der Gast mit den meisten Fotos (ab 5) |
| 🏆 | Das coolste Objekt | Was die KI am coolsten findet | höchster `coolness`-Wert eines Objekts, mit Urteil der KI (aus) |

### ML-Pipeline und externe KI

Tab „ML-Pipeline“ (`?tab=ml`), fünf Karten:

- **„Modelle“:** jede Analyse mit Beschreibung, Größe, an/aus, ihren Einstellungen und
  Zahlen (Ø und letzte Dauer, Fotos, Fehler), dazu die Warteschlange und der
  Herzschlag des Analyse-Prozesses. Fehlen Modelldateien, steht oben **„Modelle
  herunterladen“**: der Server lädt die fehlenden Modelle (die Standard-Modelle und die
  eingeschalteter Analysen, z. B. FairFace erst, wenn „Alter“ an ist) von festen,
  versionierten Adressen, prüft ihre SHA256-Summe und legt sie ins Daten-Volume
  (`/data/wall/models`), wo sie Redeploys überstehen; mit Fortschritt und Fehlertext,
  ein zweiter Klick startet nichts doppelt. Fehlt das KI-Paket selbst (Image mit
  `VB_ML=0`), sagt die Karte das und wie man es behebt (in Coolify `VB_ML=1`,
  Redeploy). Der Schalter einer Analyse, die gerade nicht laufen kann („läuft nicht“
  mit Grund), geht in beide Richtungen: er speichert den Wunsch, und sie läuft, sobald
  ihre Modelle da sind.
- **„Testbild“:** ein JPEG hochladen und sehen, was die ganze Pipeline oder einzelne
  Analysen finden (Werte, Objekte mit Rahmen, Dauer, was nicht lief und warum), auf
  Wunsch auch der KI-Dienst („kostet“). Nichts wird als Partyfoto gespeichert;
  höchstens 6 pro Minute.
- **„Claude (KI-Dienst)“** (optional, aus): „Externe KI verwenden“, Anbieter
  (Anthropic, USA, oder Mistral AI, EU), Modell (Standard Claude Haiku 5.5; Sonnet 5.5,
  Opus 5.5; bei Mistral Small 3.2 und Medium 3.1), „Abfrage alle … Minuten“ (1–60),
  „Erkennung beim Hochladen: lokal / Claude“ (beides geht; „lokal“ aus schaltet den
  Objekt-Detektor ab). „API-Schlüssel“: wird verschlüsselt gespeichert und nie wieder
  angezeigt, danach steht nur „gesetzt“ („Schlüssel ersetzen“, „Schlüssel löschen“,
  Test). Nach einem neuen `VB_SECRET_KEY`: „Schlüssel ungültig, bitte neu eingeben“.
  „Jetzt abfragen“ startet eine Abfrage sofort.
- **„Eigenschaften“:** z. B. `coolness` mit Prompt („Bewerte, wie cool jedes Objekt
  ist“). „Name und Prompt lassen sich später nicht ändern. Für eine Änderung legst du
  eine neue Eigenschaft an.“ Statt Löschen: „Archivieren“ (keine Abfragen mehr, die
  letzten Werte bleiben lesbar; zurückholbar).
- **„Budget“:** Grenzen in USD und/oder Aufrufen für die ganze Party und pro Tag, der
  Verbrauch (Aufrufe, Tokens, geschätzte Kosten) gesamt und je Erkennung, Eigenschaft,
  Urteil und Testbild. Am Limit stoppt jeder Aufruf: „Budget erreicht – externe KI
  pausiert“.

Was die externe KI tut, wenn sie an ist:

- **Erkennung beim Hochladen:** nach der lokalen Analyse geht das Foto verkleinert
  (≤ 1024 px, ohne Metadaten) an den Dienst; seine Objekte werden an die Liste
  angehängt. Ältere Fotos werden nachgeholt, die neuesten zuerst.
- **Abfrage** (alle 1–60 Minuten, nur Text): pro Eigenschaft die Objekte aller
  erlaubten Fotos als Liste („P… von <Name>: [0] Hut, [1] Weinglas“); zurück kommt
  pro Foto ein Wert je Objekt in derselben Reihenfolge. Nur die neuesten Werte bleiben.
  Danach ein Urteil pro Kategorie mit Prompt; der Text (höchstens 160 Zeichen) steht
  auf der Wall unter dem Gewinner. Hat sich nichts geändert, wird nicht abgefragt.
- **Nie hinaus** gehen Fotos, Objekte und Namen von Gästen mit „Keine Weitergabe an
  externe KI“ oder „Meine Fotos nicht automatisch auswerten“, von gesperrten Gästen und
  ausgeblendete oder gelöschte Fotos; geprüft direkt vor jedem Aufruf. Ein Urteil, das
  einen solchen Gast nennt, verschwindet sofort von der Wall.
- Gäste werden so benannt wie auf der Wall (Anzeigename, „@Instagram“ nur, wenn die
  Wall Instagram-Namen zeigt, sonst der Zufallsname), immer als Daten markiert: was in
  Namen steht, ist für die KI keine Anweisung.

### Deep Links

| Adresse | Öffnet |
|---|---|
| `/admin/live?photo=<id>` | ein Foto groß auf Live |
| `/admin/manage?photo=<id>` | ein Foto im Kontaktbogen |
| `/admin/manage?ext=<id>&status=hidden&user=<Nr.>` | den Kontaktbogen gefiltert |
| `/admin/manage?tab=gaeste&q=<Suche>&show=paused` | die Gästeliste gefiltert (`banned`, `ok`, `paused`) |
| `/admin/manage?tab=gaeste&code=<Nr.>` | die Gäste, die über diesen QR-Code beigetreten sind |
| `/admin/manage?tab=qr&code=<Nr.>` | das Sheet eines QR-Codes (`&deleted=1`: mit den gelöschten) |
| `/admin/manage?tab=<Tab>` | einen Tab der Verwaltung (z. B. `allgemein`, `fotobox`, `livewall`, `ml`; `einstellungen` öffnet „Allgemeines“) |
| `/livewall` | die Live-Wall (Bildschirm) |
| `/admin/user?id=<Nr.>&photo=<id>` | einen Gast, optional mit einem Foto groß |
| `/admin/login?next=<Pfad>` | den Login, danach den Pfad |

Ein geöffnetes Foto steht in der Adresse. Am Handy schließt die Zurück-Taste die große
Ansicht.

### Live-Abgleich zwischen Geräten

- Jede offene Admin-Seite aktualisiert sich live (Server-Sent Events): neue Fotos,
  Aus- und Einblenden, Löschen, neue Gäste, Sperren, Pausen, Stopps von Hochladen und
  Anmeldung, Instagram-Marken, Export-Fortschritt, QR-Codes (neu, bearbeitet, neues
  Token, gelöscht), Eventname und Fotobox-Filter.
- Die Plakat-Vorlage lädt neu, wenn man zur Seite zurückkehrt. Gäste haben keinen
  Live-Kanal: Sie sehen einen neuen Eventnamen spätestens nach einer Minute, neue
  Fotobox-Filter spätestens nach 30 s.
- Was ein Host am Laptop tut, sieht der andere sofort am Handy.
- Verbindungsanzeige: „verbunden“, „verbindet…“, „nur Abfrage“, „getrennt“.
- Fällt die Verbindung aus, fragt die Seite alle 5 s nach und holt verpasste
  Ereignisse beim Wiederverbinden nach. Kommt der Tab zurück in den Vordergrund, gleicht
  sie alles neu ab.
- Ein Login hält höchstens 4 Live-Verbindungen. Ein fünfter Tab ersetzt den ältesten,
  der sich dann neu verbindet.

### Allgemeines

„Allgemeines“ (`/admin/manage?tab=allgemein`; das alte `?tab=einstellungen` führt
hierher) ist ein Tab der Navigation. Jede Änderung steht im „Protokoll“, andere
Admin-Geräte sehen sie sofort.

- **„Eventname“:** „Name des Events“, 1 bis 60 Zeichen (mehrere Leerzeichen werden zu
  einem). Er steht auf Start, im Beitritts-Sheet („Willkommen bei …!“), im
  „Party-Rahmen“ der Fotobox, auf Plakaten und großen QR-Codes und
  im Archiv; auch `python -m virtubooth.tools.qr` nimmt ihn. Ohne eigenen Namen gilt
  `VB_PARTY_NAME`; „Zurück zu „…““ löscht den eigenen wieder. Gäste sehen den neuen
  Namen spätestens nach einer Minute.
- **„Admin-Passwort“:** sagt, welches gilt („Gerade gilt das Passwort aus
  VB_ADMIN_PASSWORD.“ oder „Hier geändert am …“). Ändern mit „Aktuelles Passwort“,
  „Neues Passwort“ (mindestens 12 Zeichen, besser 16 oder mehr) und „Neues Passwort
  wiederholen“. Danach sind alle anderen Geräte abgemeldet („Passwort geändert. 1
  anderes Gerät abgemeldet.“), dieses bleibt angemeldet. Es gelten die Limits des
  Logins; ein falsches aktuelles Passwort zählt wie ein falscher Login. „Passwort
  vergessen?“ nennt den Befehl für den Server.
- **„Erscheinungsbild“:** Farben und Stil der Gästeseiten und der Live-Wall (die
  Verwaltung behält ihr Aussehen). „Vorlage“: „Neon Nacht“, „Klassisch“, „Rummel“ oder
  „Eigene“ Farben (Text muss auf Hintergrund und Fläche 4,5:1 erreichen). „Stil“:
  „Ruhig“, „Party“ (ruhig plus ein paar Gags) oder „Verspielt“ (Rummel-Look:
  Schilder in Bungee, Lauflichter, Wackelaugen, ein Buzzer als Auslöser,
  Eintrittskarten, eine Markise über Start; auf der Wall Glühbirnen-Girlande und
  Preisschleifen). **Standard: „Neon Nacht“ im Stil „Verspielt“** (die Karte sagt es
  unter dem Stil). Eine Vorlage bringt ihren Stil mit (Neon Nacht und Rummel:
  Verspielt, Klassisch: Party), danach ist er frei wählbar. Ein gespeicherter Stil
  bleibt, wie der Host ihn gewählt hat; ein Theme, das vor den Stilen gespeichert
  wurde, bekommt den Stil seiner Vorlage, eigene Farben den Standard. „Zurücksetzen“
  führt zum Standard zurück. Bei reduzierter Bewegung stehen alle Animationen still.
- **„Öffentliche Adresse“** (z. B. `https://party.example.com`; „Leer lassen =
  automatisch aus dem Aufruf“): sie steht in allen QR-Codes, auf Plakaten und in der
  Ecke der Live-Wall und geht vor `VB_PUBLIC_BASE_URL`. Beim Speichern (und mit
  „Prüfen“) ruft der Server `<Adresse>/healthz` auf und prüft, dass genau dieser Server
  antwortet: „Erreichbar ✓“ oder „Nicht erreichbar – QR-Codes würden ins Leere
  führen.“ (auch bei Umleitungen oder einem anderen Server). Eine Warnung blockiert
  nichts: hinter manchen Routern erreicht der Server sich selbst nicht.

### Fotobox-Filter

Tab „Fotobox“ (`?tab=fotobox`, nur mit der Fotobox):

- Ein Schalter pro Filter, jeder Klick
  speichert sofort („„Neon“ ist aus.“, „„Neon“ ist wieder an.“). Mindestens ein Filter
  bleibt an: der letzte Schalter ist gesperrt. Gäste in der Fotobox haben die Änderung
  spätestens nach 30 s, die Fotobox-Zeile auf Start zählt nur die eingeschalteten.
  Fotos, die schon unterwegs sind, kommen trotzdem an. Filter, die ein Update neu
  bringt, sind an.

## 4. Betrieb

Details zu allem hier: [DEPLOY.md](DEPLOY.md).

### Docker, Compose, Coolify

- **Ein Image** (`Dockerfile`): baut das Frontend in einer Node-Stufe, läuft auf
  Python 3.14 slim mit ffmpeg, als Benutzer 10001, Daten im Volume `/data`,
  Health-Check auf `/healthz`.
- **Ein Container, ein Prozess.** Rate-Limits und Live-Ereignisse liegen im
  Speicher. Nie skalieren, nie mehrere Worker.
- **Compose** (`compose.yaml`): schreibgeschütztes Dateisystem, keine Linux-Rechte,
  `no-new-privileges`, Grenzen für CPU, Speicher und Prozesse, Logs rotieren
  (5 × 10 MB), Port standardmäßig nur auf `127.0.0.1:8000`.
- **Coolify** (`docker-compose.coolify.yaml`): kein eigener Port, die Domain kommt von
  Coolify, die drei Geheimnisse erzeugt Coolify beim ersten Deploy (das Party-Token
  wird nur zu QR-Code 1). Keine `.env` nötig.
- **HTTPS ist Pflicht**, sonst gibt es keine Kamera. Ein Reverse Proxy davor (Caddy,
  Traefik, nginx oder Coolify) muss TLS beenden, den `Host` weitergeben,
  `X-Forwarded-For`/`-Proto` setzen, SSE nicht puffern und Uploads bis 8 MB erlauben.
- Erste Einrichtung:

```bash
docker compose run --rm -T app virtubooth gen-env > .env   # neue Geheimnisse
docker compose up -d --build
docker compose ps                                           # warten auf "(healthy)"
```

### Umgebungsvariablen

Alles, was nicht im Admin unter [Allgemeines](#allgemeines) oder
[QR-Codes](#qr-codes) steht, über `VB_*`-Umgebungsvariablen (Compose: `.env`,
Coolify: Environment Variables). Fehlt ein Pflichtwert oder ist einer ungültig,
startet der Server nicht und nennt die Variable. Die Limits stehen unter
[Limits](#limits).

| Variable | Standard | Wofür |
|---|---|---|
| `VB_PARTY_TOKEN` | leer | optional; nur beim ersten Start gelesen: wird das Token von QR-Code 1 (16 bis 128 Zeichen aus `A-Z a-z 0-9 _ -`; leer: ein neues). Danach im Admin verwalten; ein späteres Ändern bewirkt nichts außer einer Warnung im Log |
| `VB_ADMIN_PASSWORD` | Pflicht | Start-Passwort, mindestens 12 Zeichen; sobald im Admin geändert, gilt das dort gesetzte (zurücksetzen: `virtubooth reset-admin-password --from-env`). Unter 16 oder eintönig: Warnung im Log. Solange keins im Admin gesetzt ist, beendet Ändern alle Admin-Sitzungen |
| `VB_SECRET_KEY` | Pflicht | Signiert die Cookies, mindestens 32 Zeichen. Ändern vergisst alle Gast-Geräte |
| `VB_PARTY_NAME` | `Party` | Standard-Eventname; im Admin überschreibbar. Auf Start, im Beitritts-Sheet, im Party-Rahmen und auf Plakaten |
| `VB_INSTAGRAM_ACCOUNT` | leer | der Account, auf dem gepostet wird; steht im Beitritts-Sheet und auf Start |
| `VB_PUBLIC_BASE_URL` | leer | öffentliche Adresse, z. B. `https://party.example.com`: QR-Codes, CSRF-Prüfung, Secure-Cookies |
| `VB_EXTENSIONS` | alle | Aktivitäten und ihre Reihenfolge, z. B. `beer,booth,wall` (`wall` = Live-Wall). Unbekannte IDs verhindern den Start |
| `VB_TIMEZONE` | `Europe/Berlin` | Uhrzeit in Foto- und Exportdateinamen |
| `VB_CONSENT_VERSION` | `1` | Version der Beitrittstexte; erhöhen, wenn sich das Versprechen ändert, z. B. damit der Satz zur Statistik pro Gast als neue Textversion festgehalten wird |
| `VB_COOKIE_SECURE` | `auto` | `auto`, `true` oder `false`. Hinter TLS-Proxy `true` |
| `VB_FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxys, deren `X-Forwarded-*` gelten (IPs oder Netze). `*` wird abgelehnt. Coolify-Datei: private Netze |
| `VB_ALLOWED_ORIGINS` | leer | zusätzliche Origins für die CSRF-Prüfung |
| `VB_ADMIN_SESSION_HOURS` | `12` | Dauer einer Admin-Sitzung |
| `VB_DATA_DIR` | `./data` | Datenbank, Fotos, Exporte. Docker: `/data` |
| `VB_WEB_DIR` | `frontend/dist` | das gebaute Frontend. Docker: `/app/web` |
| `VB_DEV` | aus | `1`: ohne Frontend-Build Platzhalterseiten (nur Entwicklung) |
| `VB_HOST`, `VB_PORT` | `127.0.0.1`, `8000` | Adresse von `virtubooth serve`. Docker: `0.0.0.0`, `8000` |
| `VB_PUBLISH_PORT` | `127.0.0.1:8000` | nur `compose.yaml`: Port auf dem Host |
| `VB_IMAGE` | `virtubooth:local` | nur `compose.yaml`: Name des Images |
| `VB_CPU_LIMIT`, `VB_MEM_LIMIT` | `1.0`, `1g` | nur `compose.yaml`: Grenzen des Containers (`docker-compose.coolify.yaml`: fest 2 CPUs, 1536 MB) |
| `VB_WALL_WORKER` | an | `off`: der Server startet den Analyse-Prozess der Live-Wall nicht (z. B. weil er in einem anderen Container läuft) |
| `VB_WALL_MODELS_DIR` | leer | Ordner der Analyse-Modelle; sonst `<data>/wall/models` und `/opt/vb-models` (im KI-Image) |
| `VB_WALL_THREADS` | `3` | Threads je Analyse (0 = alle Kerne) |

### Kommandozeile

| Befehl | Was |
|---|---|
| `virtubooth serve` | der Server (Standard). `--host`, `--port`, `--forwarded-allow-ips`, `--reload` |
| `virtubooth gen-env` | gibt eine `.env` mit neuen Geheimnissen aus |
| `virtubooth reset-admin-password` | Admin-Passwort vergessen: `--from-env` löscht das im Admin gesetzte, dann gilt wieder `VB_ADMIN_PASSWORD`; ohne Option fragt es zweimal nach einem neuen (oder `--password-stdin`). Meldet alle Admins ab. Im Container: `docker compose exec app virtubooth reset-admin-password --from-env` |
| `virtubooth export-openapi -o <Datei>` | schreibt das OpenAPI-Schema (für den typisierten Frontend-Client) |
| `python -m virtubooth.tools.qr` | QR-Codes und Druckbogen. `--base-url`, `--code <Nr.>` (Token dieses QR-Codes), `--token` (ein bestimmtes Token), `--extensions`, `--party-name` (Standard: der Eventname aus der Datenbank, ohne Datenbank `VB_PARTY_NAME`), `--no-home`, `--out`. Ohne `--code` und `--token`: der aktive QR-Code mit der kleinsten Nummer aus der Datenbank von `--data-dir`, ohne Datenbank `VB_PARTY_TOKEN` |
| `python -m virtubooth.tools.timelapse` | Zeitraffer. `--extension`, `--fps`, `--crossfade`, `--fade`, `--out-fps`, `--size`, `--hold-last`, `--crf`, `--preset`, `--include-hidden`, `--limit` (Vorschau), `--dry-run`, `--out` |
| `python -m virtubooth.tools.export` | alles als `.tar.gz`, auch im laufenden Betrieb. `--no-hidden`, `--no-db`, `--out` |
| `virtubooth wall` (lang: `python -m virtubooth.extensions.wall.enrich`) | Fotoanalyse der Live-Wall: `models fetch` (Modelle laden, SHA256-geprüft; `--with-age` auch FairFace), `models list`, `status`, `run-once` (wartende Fotos jetzt auswerten), `worker`, `bench <Ordner>` |

- Alle Werkzeuge haben `--data-dir` und `--help`. Sie schreiben nach `<data>/exports/`
  und behalten ihre Dateien, bis man sie löscht.
- Im Container: `docker compose exec app python -m virtubooth.tools.<werkzeug> …`.
- Für Entwickler listet `make help` alle Aufgaben (`setup`, `dev`, `dev-web`,
  `build-web`, `openapi`, `lint`, `typecheck`, `test`, `e2e`, `docker-smoke`,
  `check`, `check-all` u. a.).

### Daten und Backups

- Alles liegt in einem Ordner bzw. Volume (`/data`): `virtubooth.db` (SQLite im
  WAL-Modus), ein Ordner pro Aktivität mit Fotos und `thumbs/`, `exports/` und
  `poster/` (die Plakat-Vorlage).
- Ausgeblendete Fotos bleiben auf der Platte. Nur Löschen entfernt Dateien.
- **Backup im laufenden Betrieb:** „Archiv erstellen“ mit „Datenbank mitnehmen (für
  ein Backup)“, oder `python -m virtubooth.tools.export`. Die Datenbank-Kopie ist
  konsistent. Nach einer Wiederherstellung melden sich Admins neu an.
- **Vollständiges Backup:** Container stoppen, Volume archivieren, wieder starten
  (Befehle in [DEPLOY.md → Backups](DEPLOY.md#backups)).
- Backups enthalten Fotos, IPs und Gerätemerkmale, dazu die QR-Tokens und den Hash
  des Admin-Passworts: so sicher aufbewahren wie die Fotos.
- Nach der Party: exportieren, kopieren, dann `docker compose down -v` (löscht alles).

### Updates und Migrationen

- `git pull` und `docker compose up -d --build`. In Coolify: Redeploy.
- Das Volume bleibt bei Updates unberührt.
- Datenbank-Migrationen laufen beim Start von selbst. Es sind nummerierte Schritte,
  neue werden nur angehängt. Auch eine Datenbank von vor der Überarbeitung wird so
  aktualisiert. Schritt 4 bringt die Tabelle `visitors` für den Besucherzähler,
  Schritt 5 die QR-Codes: Beim ersten Start danach wird `VB_PARTY_TOKEN` zu QR-Code 1,
  gedruckte Codes funktionieren weiter, alle bisherigen Gäste und Scans zählen für
  ihn. Schritt 6 bringt die Online-Zeit pro Gast.
- Sicherheitsupdates der Basis-Images: `docker compose build --pull`.
- Kein Update am Party-Abend.

### Sauberes Herunterfahren

- Offene Live-Verbindungen werden nach 5 s geschlossen. Compose wartet bis zu 15 s.
- Ein laufender Export wird abgebrochen und als fehlgeschlagen markiert („Server wurde
  neu gestartet.“). Halbfertige Dateien werden entfernt.
- Der Server schreibt die WAL-Datei in `virtubooth.db` zurück. Ein kopierter
  Datenordner enthält dann alles in dieser einen Datei.
- Fotos werden atomar geschrieben. Auch ein harter Abbruch hinterlässt keine halben
  Fotos.

## 5. Sicherheit und Datenschutz

Jede Schicht im Detail: [ARCHITECTURE.md → Security model](ARCHITECTURE.md#security-model).

### Zugang und Cookies

- **Kein QR-Code, kein Zutritt.** Jede Gast-Seite und jede Gast-API braucht das
  Zugangs-Cookie aus dem QR-Link. Ohne gibt es nur das Gate und wenige feste Dateien
  (Icons, `boot-check.js`, `gate-hint.js`, `robots.txt`). Einzige Ausnahme: der
  [Admin-Gast](#als-gast-teilnehmen-admin-gast). Seine signierte Gast-ID setzt nur eine
  Admin-Sitzung (`POST /api/admin/guest`, mit CSRF-Prüfung), ein Gast kann nie zu ihm
  werden.
- Das Token wird im Zugriffslog maskiert (`?t=***`), und Seiten senden
  `Referrer-Policy: no-referrer`.
- Fotos liegen außerhalb des Web-Ordners. Ein Foto bekommt nur der Gast, der es gemacht
  hat, und der Admin. Alle anderen bekommen 404.

| Cookie | Inhalt | Dauer | Eigenschaften |
|---|---|---|---|
| `vb_access` | signierte Code-Nummer mit der Token-Generation des gescannten QR-Codes | 30 Tage | HttpOnly, SameSite=Lax |
| `vb_uid` (mit Secure: `__Host-vb_uid`) | signierte Gast-ID | 30 Tage | HttpOnly, SameSite=Lax |
| `vb_vid` | zufällige Besucher-ID, signiert | 30 Tage | HttpOnly, SameSite=Lax |
| `vb_admin` | zufälliges Sitzungstoken, in der DB nur als SHA-256 | `VB_ADMIN_SESSION_HOURS` (12 h) | HttpOnly, SameSite=Strict |

Secure setzt `VB_COOKIE_SECURE`. Bei `auto`: wenn die Anfrage über HTTPS kam oder
`VB_PUBLIC_BASE_URL` mit `https://` beginnt.
Mit Secure heißt das Gast-ID-Cookie `__Host-vb_uid`: Der Browser nimmt es nur von
dieser Domain über HTTPS an. Ein `vb_uid`, das eine Nachbar-Subdomain oder ein Angreifer im
Party-WLAN über eine HTTP-Antwort setzt, wird dann nicht gelesen. Ein Gast mit dem
alten Namen bleibt derselbe Gast: Die Seite schickt die Kopie aus dem localStorage mit.

### CSRF und Header

- Jede Änderung (POST, PUT, PATCH, DELETE) braucht einen `Origin` (oder `Referer`),
  dessen Schema, Host und Port passen: `VB_PUBLIC_BASE_URL`, ein Eintrag aus
  `VB_ALLOWED_ORIGINS` oder die eigene Adresse. Auf HTTPS-Seiten werden `http://`-Origins
  abgelehnt. Sonst: 403.
- **Strenge CSP** auf jeder Antwort: nur eigene Skripte, Styles, Bilder und
  Verbindungen, keine fremden Hosts, keine Inline-Skripte oder -Styles, keine Frames.
- Dazu `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, COOP und CORP, eine
  Permissions-Policy, die nur die Kamera erlaubt, und HSTS über HTTPS.
- API-Antworten sind `no-store`, HTML ist `private, no-cache`.
- Keine Laufzeit-API-Doku (`/docs` und `/openapi.json` sind aus).

### Limits

Bei Überschreitung antwortet der Server 429 mit `Retry-After`. Grenzen pro IP fassen
IPv6-Adressen pro /64 zusammen.

| Was | Grenze | Einstellung |
|---|---|---|
| Uploads pro Gast | 10 pro Minute, jeder Versuch zählt | `VB_UPLOADS_PER_USER_PER_MIN` |
| Uploads pro IP | 180 pro Minute, nur gültige Fotos | `VB_UPLOADS_PER_IP_PER_MIN` |
| Uploads der ganzen Party | 300 pro Minute, nur gültige Fotos | `VB_UPLOADS_GLOBAL_PER_MIN` |
| Neue Gäste pro IP | 120 pro 10 Minuten | `VB_NEW_USERS_PER_IP_PER_10MIN` |
| Gezählte QR-Scans ohne Besucher-ID pro IP | 120 pro 10 Minuten; darüber kommt der Browser trotzdem rein, nur ohne neue Besucher-Zeile (gezählt erst beim Beitritt), kein 429 | `VB_SCANS_PER_IP_PER_10MIN` |
| Fotos pro Gast | 300, nicht gelöschte über alle Aktivitäten; darüber 403 `photo_limit` („Du hast schon sehr viele Fotos gemacht …“), das Foto wartet auf dem Handy; 0 = keine Grenze | `VB_MAX_PHOTOS_PER_GUEST` |
| Freier Speicher | Uploads nur bei mindestens 2048 MB frei unter `VB_DATA_DIR`; sonst 503 `storage_full` mit `Retry-After: 300` und eine Warnung im Log (höchstens einmal pro Minute); 0 = aus | `VB_MIN_FREE_MB` |
| API-Anfragen pro beigetretenem Gerät | 300 pro Minute | `VB_API_REQUESTS_PER_GUEST_PER_MIN` |
| API-Anfragen pro IP, nicht beigetreten | 1200 pro Minute | `VB_API_REQUESTS_PER_IP_PER_MIN` |
| Admin-API mit Sitzung | keine Grenze | fest |
| Admin-Login pro IP | 5 pro Minute, 20 pro Stunde | fest |
| Login-Sperre für alle | nach 20 Fehlversuchen in 15 Minuten 5 Minuten | fest |
| Größe eines Uploads | 8.000.000 Bytes | `VB_MAX_UPLOAD_BYTES` |
| Foto | nur JPEG, genau 1080 × 1440 px | pro Aktivität |
| Progressives JPEG | höchstens 100 Scans | fest |
| Pixel | höchstens 25 Mio. pro Bild | fest |
| Upload-Metadaten (`X-VB-Meta`) | höchstens 2048 Zeichen, nur erlaubte Schlüssel, Werte bis 100 Zeichen | pro Aktivität |
| JSON-Anfrage | höchstens 64 KiB, `Content-Length` Pflicht | fest |
| Gerätemerkmale | höchstens 20 pro Gast, je bis 32 Felder | fest |
| Instagram-Name | höchstens 30 Zeichen aus a–z, 0–9, Punkt, Unterstrich | fest |
| Sammelaktion im Kontaktbogen | höchstens 200 Fotos | fest |
| Live-Verbindungen pro Login | 4 | fest |
| Falsche QR-Tokens pro IP | 60 pro Minute, danach antwortet jede Adresse mit dem Gate | fest |

### Uploads und Metadaten

- Jedes Foto wird geprüft (JPEG, Größe, Scans) und neu kodiert, das Vorschaubild auch.
  Dabei fallen alle Metadaten weg: EXIF mit GPS, XMP, ICC-Profile, Kommentare und
  angehängte Daten. Nichts davon erreicht die Platte.
- Die Prüfreihenfolge: Aktivität, Pause, Stopp, Format, Limits, Größe, Metadaten,
  Bild.
- Pausierte, gestoppte und gesperrte Gäste werden vor jeder Prüfung abgewiesen.

### Content-Blocker

uBlock, AdGuard, Brave und iOS-Blocker verstecken alles, was nach Werbung, Tracking oder
Cookie-Hinweis aussieht. virtubooth vermeidet das:

- Neutrale Namen in Dateien, URLs, CSS-Klassen, IDs, Test-IDs und Speicherschlüsseln:
  kein `ad`, `banner`, `track`, `pixel`, `consent`, `cookie`, `popup`, `modal`,
  `fingerprint` und Ähnliches.
- Der Build bricht bei verdächtigen Namen ab. Ein Test prüft alle URLs gegen echte
  Filterlisten, die Browser-Tests prüfen die fertigen Seiten.
- Der Sammler für Gerätemerkmale liegt in einem eigenen Teil. Blockiert ein Blocker
  ihn, läuft die Seite mit einer groben Ersatz-Kennung weiter.
- Startet die Seite trotzdem nicht, erscheint nach 6 s „Die Seite startet nicht“ mit dem
  Rat, den Blocker auszuschalten.

### Was über Gäste gespeichert wird

| Daten | Wozu |
|---|---|
| Gast-Nr. und Pseudonym, optional ein selbst gewählter Anzeigename | Anzeige |
| Instagram-Name, nur wenn angegeben | Markieren beim Posten |
| Zeit und Textversion des Beitritts | Nachweis, was der Gast gesehen hat |
| Erstes und letztes Mal gesehen | Gästeliste, „Aktiv“ |
| Online-Zeit und Zahl der Besuche (die Seite meldet sich jede Minute, solange sie sichtbar ist) | Statistik pro Gast |
| Erste und letzte IP-Adresse, User-Agent (bis 300 Zeichen) | Moderation, „Technische Details“ |
| Gerätemerkmal: Hash und Bestandteile (Bildschirm, Grafikkarte, Sprachen, Zeitzone, Kerne, Speicher, Touch, Canvas-Hash u. a.) | nur ein Hinweis für Sperren, keine Identität |
| Sperre mit Grund, Pause mit Quelle | Moderation |
| Fotos mit Vorschaubild, Aktivität, Nummer, Zeit, Gefäß bzw. Filter und Kamera | die Party |
| Anonyme Besucher-ID mit erstem und letztem Mal gesehen und dem Gast, zu dem sie wurde. Keine IP, kein User-Agent | „Gescannt“ in der Übersicht |
| QR-Code des Beitritts; welche Besucher-ID welchen Code wie oft geöffnet hat (erstes und letztes Mal). Keine IP | Zahlen pro QR-Code |
| Mit der Live-Wall: pro Foto Zahlen der [Fotoanalyse](#fotoanalyse) (Gesichter, Lächeln, Hände, geschätzter Ausdruck und Altersspanne u. a.), die Objektliste und Rahmen. Keine Gesichtsmerkmale, nichts, was eine Person wiedererkennt; beim Löschen des Fotos entfernt. Ob der Gast die Auswertung abgeschaltet hat | Kategorien der Live-Wall |
| Mit externer KI: die Werte der Eigenschaften pro Objekt, das letzte Urteil pro Kategorie, die Verbrauchszahlen (ohne Inhalte). Ob der Gast „Keine Weitergabe an externe KI“ gewählt hat. Was beim KI-Dienst landet: das verkleinerte Foto (Erkennung), Objektnamen und angezeigte Namen (Abfragen) | Kategorien der Live-Wall |

- Admin-Aktionen und Login-Versuche (mit IP) stehen im Protokoll. Admin-Sitzungen
  speichern Token-Hash, IP und User-Agent.
- Auf dem Gerät des Gasts: die Cookies oben, in localStorage eine Kopie der Gast-ID
  und die Wahl von Gefäß und Countdown, in IndexedDB die Outbox, in sessionStorage
  kleine Anzeige-Schalter.
- Löschen: Nur Löschen in der Verwaltung oder das Löschen des Volumes entfernt Dateien.
  Siehe [DEPLOY.md → Teardown](DEPLOY.md#teardown).

## 6. Erweiterbarkeit

Jede Aktivität ist eine Erweiterung aus zwei Hälften mit derselben ID:

- **Backend:** ein Paket `backend/src/virtubooth/extensions/<id>/` mit
  `extension = Extension(...)`. Es nennt Titel, Untertitel und Reihenfolge, optional
  Upload-Regeln (genaue Größe, erlaubte Metadaten, Prüffunktion), eine eigene API unter
  `/api/x/<id>/`, Admin-Routen unter `/api/admin/x/<id>/` (z. B. die Fotobox-Filter)
  und einen `on_upload`-Hook für Zusatzfelder in der Upload-Antwort.
- **Frontend:** ein Ordner `frontend/src/extensions/<id>/` mit einer `index.ts`, die
  die Seite unter `/x/<id>/` lazy registriert, optional mit einer Live-Zeile für Start.
  Die Seite nutzt das Gast-SDK: Sitzung, Kamera (Vorschau = Foto), Outbox und Upload,
  den Seitenrahmen `ActivityShell` mit Gästepass, Filmrand und Auslöser.
- Den Rest macht der Kern: Finden und Ordnen über `VB_EXTENSIONS`, Gate, Beitritt,
  Upload-Prüfung und Speicherung, Limits, Moderation, Karte auf Start, Umschalter,
  Admin-Filter, QR-Code, Archiv, Instagram-ZIP und Zeitraffer.
- Ein Unit-Test schlägt fehl, wenn eine Hälfte fehlt.
- Ein vollständiges, getestetes Beispiel („Schnappschuss“):
  [ARCHITECTURE.md → Adding an activity](ARCHITECTURE.md#adding-an-activity).

## 7. Bewusst nicht enthalten

- **Keine Live Wall** für Fernseher oder Beamer. Sie stand in der ursprünglichen
  Anforderung, ist aber verschoben. Die Erweiterungsschnittstelle lässt sie zu.
- **Keine Konten:** Gäste haben nur ein Pseudonym, Admins teilen ein Passwort.
- **Kein Service Worker,** keine Offline-App. Die Outbox hält Fotos trotzdem fest.
- **Nicht mehrere Worker oder Container:** Limits und Live-Ereignisse liegen im
  Speicher eines Prozesses.
- **Kein Raspberry Pi und kein systemd:** virtubooth läuft als Docker-Container hinter
  einem eigenen Reverse Proxy, statt wie ursprünglich geplant auf einem Pi mit Caddy.
- **Kein „Nein“ im Beitritt:** Wer nicht fotografiert werden will, nutzt die Seite
  nicht.
- **Kein Löschen auf Live:** Live kann Fotos nur aus- und einblenden. Löschen und
  Sperren gibt es nur in der Verwaltung und auf der Gästeseite.
- **Keine Laufzeit-API-Doku:** Das Schema entsteht mit `virtubooth export-openapi`.
