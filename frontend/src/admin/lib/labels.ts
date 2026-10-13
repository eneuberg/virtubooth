/**
 * Admin copy built from data: frame labels, readable meta, devices, audit entries,
 * counts. German typography (lib/format): NBSP between number and unit, „…“.
 */
import type { AdminExtension, AdminPhoto, AdminUser, AuditEntry, ExportJob } from '@/api/types';
import { formatDateTime, formatTime, frameLabel, NBSP, pluralize } from '@/lib/format';
import { quoted } from '@/lib/messages.de';

export function photoLabel(photo: Pick<AdminPhoto, 'extension' | 'seq'>): string {
  return frameLabel(photo.extension, photo.seq);
}

export const photoCount = (n: number) => pluralize(n, 'Foto', 'Fotos');
export const guestCount = (n: number) => pluralize(n, 'Gast', 'Gäste');
export const deviceCount = (n: number) => pluralize(n, 'Gerät', 'Geräte');
export const handleCount = (n: number) => pluralize(n, 'Name', 'Namen');

/** "22:41" today, "Di., 22:41" on another day. */
export function clock(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return '–';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '–';
  const sameDay = date.toDateString() === now.toDateString();
  if (sameDay) return formatTime(date);
  const weekday = new Intl.DateTimeFormat('de-DE', { weekday: 'short' }).format(date);
  return `${weekday}, ${formatTime(date)}`;
}

/** Retry-After in words: "in 45 Sekunden", "in 1 Minute", "in 12 Minuten", "in 2 Stunden". */
export function waitInWords(seconds: number): string {
  const s = Math.max(1, Math.round(seconds));
  if (s < 60) return `in ${s}${NBSP}${s === 1 ? 'Sekunde' : 'Sekunden'}`;
  const min = Math.ceil(s / 60);
  if (min < 90) return `in ${min}${NBSP}${min === 1 ? 'Minute' : 'Minuten'}`;
  const h = Math.round(min / 60);
  return `in ${h}${NBSP}${h === 1 ? 'Stunde' : 'Stunden'}`;
}

// ------------------------------------------------------------------- devices

/** "iPhone, iOS 18.5, Safari 18.5" from a user agent (the pre-overhaul describeUA, with commas). */
export function describeUA(ua: string | null | undefined): string {
  if (!ua) return 'unbekannt';
  const parts: string[] = [];
  let m: RegExpMatchArray | null;
  if ((m = ua.match(/iPhone OS (\d+)[_.](\d+)/))) parts.push('iPhone', `iOS ${m[1]}.${m[2]}`);
  else if ((m = ua.match(/iPad.*OS (\d+)[_.](\d+)/))) parts.push('iPad', `iPadOS ${m[1]}.${m[2]}`);
  else if ((m = ua.match(/Android (\d+(?:\.\d+)?)(?:;\s*([^;)]+))?/))) {
    parts.push(`Android ${m[1]}`);
    const model = m[2]?.trim();
    if (model && !/^(K|wv|Linux|U)$/.test(model)) parts.push(model);
  } else if (/Macintosh/.test(ua)) parts.push('Mac');
  else if (/Windows/.test(ua)) parts.push('Windows');
  else if (/Linux/.test(ua)) parts.push('Linux');
  if (/Instagram/.test(ua)) parts.push('Instagram-App');
  else if (/FBAN|FBAV/.test(ua)) parts.push('Facebook-App');
  else if ((m = ua.match(/SamsungBrowser\/(\d+)/))) parts.push(`Samsung Internet ${m[1]}`);
  else if ((m = ua.match(/(?:CriOS|Chrome)\/(\d+)/)) && !/Edg/.test(ua)) parts.push(`Chrome ${m[1]}`);
  else if ((m = ua.match(/Edg(?:A|iOS)?\/(\d+)/))) parts.push(`Edge ${m[1]}`);
  else if ((m = ua.match(/(?:FxiOS|Firefox)\/(\d+)/))) parts.push(`Firefox ${m[1]}`);
  else if ((m = ua.match(/Version\/(\d+(?:\.\d+)?).*Safari/))) parts.push(`Safari ${m[1]}`);
  return parts.length ? parts.join(', ') : ua.slice(0, 60);
}

/** ", 2 weitere Geräte entsperrt" after lifting a device ban that auto-banned others. */
export function releasedText(n: number): string {
  if (n === 0) return '';
  return `, ${n === 1 ? '1 weiteres Gerät' : `${n} weitere Geräte`} entsperrt`;
}

/** First characters of a device-trait hash, grouped for reading: "e6c3 3669". */
export function shortHash(hash: string): string {
  return `${hash.slice(0, 4)} ${hash.slice(4, 8)}`;
}

// ---------------------------------------------------------------------- meta

const VALUE_LABELS: Record<string, Record<string, string>> = {
  vessel: { bottle: 'Flasche', cup: 'Becher' },
  facing: { user: 'Selfie', environment: 'Rückkamera' },
  filter: {
    normal: 'Normal',
    bw: 'Schwarz-Weiß',
    sepia: 'Sepia',
    colorpop: 'Color Pop',
    party: 'Party-Rahmen',
    emoji: 'Emoji-Props',
    neon: 'Neon',
    vhs: 'Vintage/VHS',
    retro: 'Retro-Pixel',
    comic: 'Comic',
  },
};

/** Readable meta rows: "Gefäß: Flasche", "Kamera: Selfie" (labels from the extension). */
export function metaRows(
  photo: Pick<AdminPhoto, 'meta'>,
  ext: AdminExtension | undefined,
): Array<[string, string]> {
  const rows: Array<[string, string]> = [];
  for (const [key, value] of Object.entries(photo.meta)) {
    if (value === null || value === '') continue;
    const label = ext?.meta_labels[key] ?? key;
    const raw = String(value);
    const text = typeof value === 'boolean' ? (value ? 'ja' : 'nein') : (VALUE_LABELS[key]?.[raw] ?? raw);
    rows.push([label, text]);
  }
  return rows;
}

// --------------------------------------------------------------------- status

export type GuestState = 'ok' | 'paused' | 'banned' | 'auto-banned';

export function guestState(user: Pick<AdminUser, 'banned' | 'auto_banned' | 'uploads_paused'>): GuestState {
  if (user.banned) return user.auto_banned ? 'auto-banned' : 'banned';
  return user.uploads_paused ? 'paused' : 'ok';
}

export function autoBanSource(user: AdminUser): string {
  if (!user.auto_ban) return 'einem gesperrten Gerätemerkmal (die Sperre gibt es nicht mehr)';
  const source = user.auto_ban.source_user_name
    ? ` (gesperrt über ${quoted(user.auto_ban.source_user_name)})`
    : user.auto_ban.source_user_id
      ? ` (gesperrt über Gast #${user.auto_ban.source_user_id})`
      : '';
  return `einem gesperrten Gerätemerkmal${source}`;
}

// ---------------------------------------------------------------------- audit

export const AUDIT_LABELS: Record<string, string> = {
  'photo.hide': 'Foto ausgeblendet',
  'photo.unhide': 'Foto eingeblendet',
  'photo.delete': 'Foto gelöscht',
  'user.ban': 'Gast gesperrt',
  'user.unban': 'Gast entsperrt',
  'fingerprint.ban': 'Gerätemerkmal gesperrt',
  'fingerprint.unban': 'Gerätemerkmal entsperrt',
  'admin.login': 'Admin angemeldet',
  'admin.logout': 'Admin abgemeldet',
  'admin.login_failed': 'Falsches Admin-Passwort',
  'admin.password_change': 'Admin-Passwort geändert',
  'admin.password_change_failed': 'Passwort ändern: falsches Passwort',
  'admin.password_reset': 'Admin-Passwort zurückgesetzt (Server)',
  'settings.event': 'Eventname geändert',
  'extension.settings': 'Aktivität eingestellt',
  'user.uploads_pause': 'Hochladen für Gast pausiert',
  'user.uploads_unpause': 'Hochladen für Gast erlaubt',
  'uploads.lock_on': 'Neue Gäste pausiert',
  'uploads.lock_off': 'Pause für neue Gäste beendet',
  'uploads.stop': 'Hochladen für alle gestoppt',
  'uploads.resume': 'Hochladen läuft wieder',
  'join.stop': 'Anmeldung gestoppt',
  'join.resume': 'Anmeldung wieder offen',
  'code.create': 'QR-Code angelegt',
  'code.edit': 'QR-Code bearbeitet',
  'code.token': 'QR-Token geändert',
  'code.revoke': 'QR-Code gelöscht',
  'instagram.done': 'Instagram-Name erledigt',
  'instagram.undone': 'Instagram-Name wieder offen',
  'export.create': 'Export gestartet',
  'export.delete': 'Export gelöscht',
  'poster.template': 'Plakat-Vorlage hochgeladen',
  'poster.layout': 'QR-Feld auf dem Plakat gesetzt',
  'poster.template_delete': 'Plakat-Vorlage entfernt',
};

export function auditAction(action: string): string {
  return AUDIT_LABELS[action] ?? action;
}

/** "Admin-Sitzung edb5", "Unbekannt". */
export function auditActor(actor: string): string {
  if (actor === 'anonymous' || !actor) return 'Unbekannt';
  const m = /^admin:([0-9a-f]+)$/.exec(actor);
  return m?.[1] ? `Admin-Sitzung ${m[1].slice(0, 4)}` : actor;
}

export type AuditTarget =
  | { kind: 'user'; id: number }
  | { kind: 'instagram'; handle: string }
  | { kind: 'export'; id: string }
  | { kind: 'code'; id: number }
  | { kind: 'photo'; id: string }
  | { kind: 'device'; hash: string }
  | { kind: 'ip'; ip: string }
  | { kind: 'text'; text: string };

export function auditTarget(target: string): AuditTarget {
  const [kind, ...rest] = target.split(':');
  const value = rest.join(':');
  if (kind === 'user' && /^\d+$/.test(value)) return { kind: 'user', id: Number(value) };
  if (kind === 'photo' && value) return { kind: 'photo', id: value };
  if (kind === 'fp' && value) return { kind: 'device', hash: value };
  if (kind === 'ip' && value) return { kind: 'ip', ip: value };
  if (kind === 'instagram' && value) return { kind: 'instagram', handle: value };
  if (kind === 'export' && value) return { kind: 'export', id: value };
  if (kind === 'code' && /^\d+$/.test(value)) return { kind: 'code', id: Number(value) };
  return { kind: 'text', text: target || '–' };
}

const KIND_WORDS: Record<string, string> = { archive: 'Archiv', timelapse: 'Zeitraffer', qr: 'QR-Bogen' };

/** "Zeitraffer (Beer Cam) vom 13.10.2026, 22:41": a timelapse names its activity by title. */
export function exportJobTitle(
  job: Pick<ExportJob, 'kind' | 'options' | 'created_at'>,
  extensions?: ReadonlyMap<string, Pick<AdminExtension, 'title'>>,
): string {
  const options: Record<string, unknown> = { ...job.options };
  const id = options['extension'];
  const activity =
    job.kind === 'timelapse' && typeof id === 'string' ? ` (${extensions?.get(id)?.title ?? id})` : '';
  return `${KIND_WORDS[job.kind] ?? job.kind}${activity} vom ${formatDateTime(job.created_at)}`;
}

function detailValue(key: string, v: unknown): string {
  if (typeof v === 'boolean') return v ? 'ja' : 'nein';
  if (typeof v === 'string') return (key === 'kind' ? KIND_WORDS[v] : undefined) ?? (v || '–');
  if (typeof v === 'number') return String(v);
  if (v === null || v === undefined) return '–';
  if (Array.isArray(v)) return v.map((x) => detailValue(key, x)).join(', ') || '–';
  if (typeof v === 'object') {
    return Object.entries(v)
      .map(([k, x]) => `${DETAIL_LABELS[k] ?? k} ${detailValue(k, x)}`)
      .join(', ');
  }
  return '–';
}

const DETAIL_LABELS: Record<string, string> = {
  reason: 'Grund',
  event_name: 'Name',
  previous: 'vorher',
  sessions_ended: 'abgemeldete Geräte',
  disabled: 'aus',
  mode: 'Art',
  options: 'Optionen:',
  include_hidden: 'Ausgeblendete',
  include_db: 'Datenbank',
  base_url: 'Adresse',
  fps: 'Bilder/s',
  crossfade: 'Überblenden',
  extension: 'Aktivität',
  status: 'Status',
  bytes: 'Größe',
  page: 'Seite',
  pages: 'Seiten',
  file_name: 'Datei',
  period: 'Pause Nr.',
  restore: 'freigeschaltet',
  restored: 'freigeschaltet',
  kept: 'pausiert gelassen',
  source: 'Quelle',
  handle: 'Instagram',
  kind: 'Art',
  name: 'Name',
  target: 'Ziel',
  note: 'Notiz',
  token: 'Token',
  token_end: 'Token endet auf',
};

export function auditDetails(entry: Pick<AuditEntry, 'details'>): string {
  return Object.entries(entry.details)
    .map(([k, v]) => {
      const label = DETAIL_LABELS[k] ?? k;
      return label.endsWith(':') ? `${label} ${detailValue(k, v)}` : `${label}: ${detailValue(k, v)}`;
    })
    .join(', ');
}

/** "13.10.2026, 22:41" */
export const absTime = formatDateTime;
