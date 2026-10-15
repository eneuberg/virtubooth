/**
 * Shared German UI copy: the glossary (UX audit §3.4) and texts more than one screen uses.
 *
 * One name per concept, the same word in button, toast and badge. Typography:
 * „…“ quotes, ’ apostrophe, … with no space before it, NBSP (\u00a0) between a
 * number and its unit. Screen-specific copy stays with its screen.
 */

const NBSP = '\u00a0';

/** Glossary: actions and states, exactly as buttons, toasts and badges show them. */
export const t = {
  // moderation (live and manage)
  hide: 'Ausblenden',
  hidden: 'Ausgeblendet',
  unhide: 'Einblenden',
  undo: 'Rückgängig',
  deleteEllipsis: 'Löschen…',
  deleteForever: 'Endgültig löschen',
  banned: 'Gesperrt',
  autoBanned: 'Automatisch gesperrt',
  banEllipsis: 'Sperren…',
  unbanEllipsis: 'Entsperren…',
  deviceMark: 'Gerätemerkmal',
  deviceMarks: 'Gerätemerkmale',
  banDeviceMarkToo: 'Gerätemerkmal auch sperren',

  // uploading
  upload: 'Hochladen',
  uploading: 'Wird hochgeladen…',
  uploaded: 'Hochgeladen',
  retrySend: 'Erneut senden',
  waiting: 'Wartet',
  uploadsPaused: 'Hochladen pausiert',
  stopAllUploads: 'Hochladen für alle stoppen',
  uploadsStoppedGuest: 'Hochladen ist kurz angehalten',
  pauseNewGuests: 'Neue Gäste pausieren',

  // taking photos
  anotherBeer: 'Noch ein Bier',
  newPhoto: 'Neues Foto',
  takePhoto: 'Foto aufnehmen',
  switchCamera: 'Kamera wechseln',
  countdownOff: 'aus',

  // identity
  instagramName: 'Instagram-Name',
  instagram: 'Instagram',
  instagramOptional: 'Instagram (freiwillig)',
  addInstagram: 'Instagram hinzufügen',

  // navigation and generic actions
  start: 'Start',
  toStart: 'Zum Start',
  backToStart: 'Zurück zum Start',
  reloadPage: 'Seite neu laden',
  /** forms (name, settings); never the guest's own photo: that is „Herunterladen“ */
  save: 'Speichern',
  /** a photo onto the phone (iOS: the share sheet's „Bild sichern“): optional, not a confirmation */
  download: 'Herunterladen',
  cancel: 'Abbrechen',
  close: 'Schließen',
  more: 'Mehr dazu',
  loading: 'Lädt…',
  sending: 'Sendet…',
  done: 'Erledigt',

  // admin realtime connection (dot + text)
  connLive: 'verbunden',
  connConnecting: 'verbindet…',
  connPolling: 'nur Abfrage',
  connClosed: 'getrennt',
} as const;

/** Errors and statuses shared by the API client, the SDK and full-screen notices. */
export const msg = {
  // api client (vb.js api()/uploadJpeg())
  offline: 'Keine Verbindung. Bist du noch im Netz?',
  noAnswer: 'Keine Antwort vom Server. Prüf dein Netz und versuch es nochmal.',
  uploadOffline: 'Keine Verbindung. Nochmal versuchen?',
  uploadTimeout: 'Der Upload hat zu lange gedauert. Nochmal versuchen?',
  uploadFailed: 'Upload fehlgeschlagen.',
  generic: 'Da ist etwas schiefgelaufen.',
  invalidRequest: 'Ungültige Anfrage.',

  // full-screen errors (vb.js fatal(), titles name the problem)
  offlineTitle: 'Keine Verbindung',
  offlineText: 'Dein Handy ist gerade offline. Sobald du wieder Netz hast, lade die Seite neu.',
  noAnswerTitle: 'Keine Antwort vom Server',
  noAnswerText:
    'Die Seite erreicht den Server gerade nicht. Prüf dein Netz, und falls du einen Werbe- oder ' +
    'Tracking-Blocker nutzt, schalte ihn für diese Seite aus. Dann lade sie neu.',
  failedTitle: 'Das hat nicht geklappt',
  unknownTitle: 'Etwas ist schiefgelaufen',
  unknownText: 'Lade die Seite neu.',

  // public/boot-check.js (kept in sync by hand: that file is a classic script)
  bootTitle: 'Die Seite startet nicht',
  bootText:
    'Wahrscheinlich blockiert ein Werbe- oder Tracking-Blocker einen Teil der Seite. ' +
    'Schalte ihn für diese Seite aus und lade sie neu.',

  // guest upload state (status slot / guest pass)
  pausedTitle: 'Hochladen pausiert',
  pausedText: 'Hochladen ist für dich gerade pausiert. Die Gastgeber geben es bald wieder frei.',
  stoppedTitle: 'Hochladen ist kurz angehalten',
  stoppedText: 'Hochladen ist kurz angehalten. Gleich geht’s weiter.',
  uploadsFreeAgain: 'Du kannst wieder hochladen.',
  bannedTitle: 'Gesperrt',
  bannedText: 'Dieses Gerät ist gesperrt. Sprich die Gastgeber an, wenn das ein Versehen ist.',
  bannedShort: 'Dieses Gerät ist gesperrt.',
  offlineShort: 'Offline',

  // gate / not found
  gateTitle: 'Scan den QR-Code',
  gateText: 'Diese Seite öffnet sich nur über einen der QR-Codes auf der Party.',
  gateHint: 'Halte die Kamera deines Handys auf den Code und tippe auf den Link.',
  notFoundTitle: 'Hier ist nichts.',
  notFoundText: 'Diese Seite gibt es nicht.',

  // misc
  /** the photo is on the phone („Herunterladen“ done) */
  downloaded: 'Heruntergeladen',
  goalShort: `1${NBSP}Mio.`,
} as const;

/** "1 Foto wartet" / "3 Fotos warten" (outbox in the status slot). */
export function waitingPhotos(n: number): string {
  return n === 1 ? `1${NBSP}Foto wartet` : `${n}${NBSP}Fotos warten`;
}

/** "Foto 0018 ausgeblendet" (toast after hiding, with the undo action). */
export function hiddenToast(frameLabel: string): string {
  return `${frameLabel} ausgeblendet`;
}

/** "„Hüpfendes Alpaka #2“ sperren?" (confirm title). */
export function quoted(text: string): string {
  return `„${text}“`;
}
