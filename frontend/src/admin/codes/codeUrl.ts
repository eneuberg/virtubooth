/**
 * QR codes, pure helpers (codeUrl.test.ts): the URL a code opens, reading a pasted
 * link or token, the client mirror of the server's token rules, and short texts.
 */
import { formatDateTime, formatNumber, NBSP } from '@/lib/format';
import { quoted } from '@/lib/messages.de';

/** The server's rule (domain/codes.py), checked here to answer while typing. */
export const TOKEN_RE = /^[A-Za-z0-9_-]{16,128}$/;
export const TOKEN_MIN_DISTINCT = 6;
export const NOTE_MAX = 60;

export const TOKEN_INVALID =
  'Das Token braucht 16 bis 128 Zeichen aus A–Z, a–z, 0–9, _ und - (ohne Leerzeichen).';
export const TOKEN_TOO_SIMPLE =
  'Das Token ist zu einfach. Nimm mehr verschiedene Zeichen oder lass eins erzeugen.';
export const NO_TOKEN_IN_LINK = 'In diesem Link steckt kein Token (…?t=…).';

/** The full URL a code opens: the public base URL (or this page's origin) + entry path. */
export function codeUrl(baseUrl: string | null | undefined, entryPath: string, origin: string): string {
  const base = (baseUrl || origin).replace(/\/+$/, '');
  return `${base}${entryPath}`;
}

/** Why `token` can't be a custom token (the server says the same), or null. */
export function tokenProblem(token: string): string | null {
  if (!TOKEN_RE.test(token)) return TOKEN_INVALID;
  if (new Set(token).size < TOKEN_MIN_DISTINCT) return TOKEN_TOO_SIMPLE;
  return null;
}

export interface PastedToken {
  /** the token to send; null when there is none (see `error`) */
  token: string | null;
  /** blocking: no token in the link, or one the server would refuse */
  error: string | null;
  /** not blocking: the link points at another host */
  warning: string | null;
  /** the link opens this activity ('' = Start); null: the link says nothing usable */
  target: string | null;
}

export interface PasteContext {
  /** where the party runs: VB_PUBLIC_BASE_URL, else this page's origin */
  partyOrigin: string;
  /** loaded activities by id */
  activities: ReadonlyMap<string, { title: string }>;
}

const LINKISH = /[/?:#=]/;

/** A pasted link: absolute, without scheme ("party.example/?t=…") or a path ("/?t=…"). */
function parseLink(raw: string, partyOrigin: string): URL | null {
  try {
    let url: URL;
    if (raw.startsWith('/') || raw.startsWith('?')) url = new URL(raw, partyOrigin);
    else if (/^[a-z][a-z0-9+.-]*:\/\//i.test(raw)) url = new URL(raw);
    else url = new URL(`https://${raw}`);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url : null;
  } catch {
    return null;
  }
}

function hostOf(origin: string): string {
  try {
    return new URL(origin).host;
  } catch {
    return origin;
  }
}

/**
 * What the admin pasted into „Token oder Link“: a bare token, or a whole link as a
 * phone's camera app shows it (`https://party.example/x/booth/?t=…`). Takes `t` from
 * the link, warns about another host, and reads the activity from `/x/<id>/`.
 */
export function readTokenInput(raw: string, ctx: PasteContext): PastedToken {
  const text = raw.trim();
  if (!text) return { token: null, error: TOKEN_INVALID, warning: null, target: null };
  if (!LINKISH.test(text)) {
    return { token: text, error: tokenProblem(text), warning: null, target: null };
  }
  const url = parseLink(text, ctx.partyOrigin);
  const token = url?.searchParams.get('t')?.trim() ?? '';
  if (!url || !token) return { token: null, error: NO_TOKEN_IN_LINK, warning: null, target: null };
  const party = hostOf(ctx.partyOrigin);
  const warning =
    url.host.toLowerCase() === party.toLowerCase()
      ? null
      : `Achtung: Der Link zeigt auf ${url.host}, die Party läuft auf ${party}. Der Code funktioniert nur, wenn er auf diese Adresse zeigt.`;
  return { token, error: tokenProblem(token), warning, target: targetOfPath(url.pathname, ctx.activities) };
}

/** '' for Start, an activity id for `/x/<id>/…` of a loaded activity, else null. */
export function targetOfPath(path: string, activities: ReadonlyMap<string, unknown>): string | null {
  if (path === '/' || path === '') return '';
  const m = /^\/x\/([a-z][a-z0-9-]{1,30})(?:\/.*)?$/.exec(path);
  return m?.[1] && activities.has(m[1]) ? m[1] : null;
}

/** „Ziel auf „Fotobox“ gesetzt, wie im Link.“ */
export function targetFromLinkNote(target: string, activities: ReadonlyMap<string, { title: string }>) {
  return `Ziel auf ${quoted(targetLabel(target, activities))} gesetzt, wie im Link.`;
}

/** „Start“, the activity's title, or „Ziel nicht verfügbar“ when it is no longer loaded. */
export function targetLabel(target: string, activities: ReadonlyMap<string, { title: string }>): string {
  if (!target) return 'Start';
  return activities.get(target)?.title ?? 'Ziel nicht verfügbar';
}

/** „3 aktiv · 1 gelöscht“, „3 aktiv“ when none is revoked. */
export function countText(active: number, revoked: number): string {
  const head = `${formatNumber(active)} aktiv`;
  return revoked > 0 ? `${head} · ${formatNumber(revoked)} gelöscht` : head;
}

/** „gelöscht am 13.10., 22:41“ */
export function revokedTitle(iso: string): string {
  const full = formatDateTime(iso); // "13.10.2026, 22:41"
  return `gelöscht am ${full.replace(/(\d{2}\.\d{2}\.)\d{4}/, '$1')}`;
}

/** „12-mal von 9 Personen“, „1-mal von 1 Person“, „Noch nie“. */
export function scansText(scans: number, people: number): string {
  if (scans === 0) return 'Noch nie';
  const who = people === 1 ? `1${NBSP}Person` : `${formatNumber(people)}${NBSP}Personen`;
  return `${formatNumber(scans)}-mal von ${who}`;
}

/** „#2“ */
export function codeNumber(id: number): string {
  return `#${id}`;
}
