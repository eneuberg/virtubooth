/**
 * German number, date and time formatting (de-DE, Intl only, formatters cached).
 *
 * Typography rules (UX audit §3.4): a number and its unit never wrap apart (NBSP:
 * "1 Mio.", "3 s", "40 %"), counters use tabular figures (CSS `tabular`), frame
 * numbers are zero-padded like film edge print ("0031").
 */

export const NBSP = '\u00a0';
const LOCALE = 'de-DE';

/** Intl inserts U+202F (narrow NBSP) in some places; the UI uses U+00A0 everywhere. */
function nbsp(text: string): string {
  return text.replace(/[\u202f\u2009]/g, NBSP);
}

const numberFmt = new Intl.NumberFormat(LOCALE);
const decimalFmt = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 1 });
const percentFmt = new Intl.NumberFormat(LOCALE, { style: 'percent', maximumFractionDigits: 0 });

/** 1000000 → "1.000.000" */
export function formatNumber(n: number): string {
  return numberFmt.format(n);
}

/** Counters and goals: 1000000 → "1 Mio.", 2500000 → "2,5 Mio.", 25000 → "25.000". */
export function formatCount(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `${decimalFmt.format(n / 1_000_000)}${NBSP}Mio.`;
  return formatNumber(n);
}

/** Film edge frame number: 31 → "0031"; never cut: 123456 → "123456". */
export function formatFrame(n: number, digits = 4): string {
  return String(Math.max(0, Math.trunc(n))).padStart(digits, '0');
}

const FRAME_WORD: Record<string, string> = { beer: 'Bier', booth: 'Foto' };

/** "Bier 0032", "Foto 0018"; other extensions use their capitalised id. */
export function frameLabel(extension: string, seq: number): string {
  const word = FRAME_WORD[extension] ?? extension.charAt(0).toUpperCase() + extension.slice(1);
  return `${word}${NBSP}${formatFrame(seq)}`;
}

/** 0.4 → "40 %" */
export function formatPercent(fraction: number): string {
  return nbsp(percentFmt.format(fraction));
}

/** 3 → "3 s" */
export function formatSeconds(seconds: number): string {
  return `${formatNumber(seconds)}${NBSP}s`;
}

/** 1 → "1 Foto", 3 → "3 Fotos", 1200 → "1.200 Fotos" */
export function pluralize(n: number, one: string, many: string): string {
  return `${formatNumber(n)}${NBSP}${n === 1 ? one : many}`;
}

const BYTE_UNITS = ['Byte', 'kB', 'MB', 'GB', 'TB'] as const;

/** 1234567 → "1,2 MB" (decimal units, like file managers) */
export function formatBytes(bytes: number): string {
  let value = Math.max(0, bytes);
  let unit = 0;
  while (value >= 1000 && unit < BYTE_UNITS.length - 1) {
    value /= 1000;
    unit += 1;
  }
  const shown = unit === 0 ? formatNumber(value) : decimalFmt.format(value);
  return `${shown}${NBSP}${BYTE_UNITS[unit]}`;
}

// --------------------------------------------------------------------- dates

const dateFmts = new Map<string, Intl.DateTimeFormat>();

function dateFmt(key: string, options: Intl.DateTimeFormatOptions, timeZone?: string): Intl.DateTimeFormat {
  const id = `${key}|${timeZone ?? ''}`;
  let fmt = dateFmts.get(id);
  if (!fmt) {
    fmt = new Intl.DateTimeFormat(LOCALE, timeZone ? { ...options, timeZone } : options);
    dateFmts.set(id, fmt);
  }
  return fmt;
}

function toDate(value: string | number | Date): Date | null {
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** "22:41" (the browser's time zone unless one is given) */
export function formatTime(value: string | number | Date, timeZone?: string): string {
  const date = toDate(value);
  return date ? dateFmt('time', { hour: '2-digit', minute: '2-digit' }, timeZone).format(date) : '–';
}

/** "13.10.2026" */
export function formatDate(value: string | number | Date, timeZone?: string): string {
  const date = toDate(value);
  return date
    ? dateFmt('date', { day: '2-digit', month: '2-digit', year: 'numeric' }, timeZone).format(date)
    : '–';
}

/** "13.10.2026, 22:41" */
export function formatDateTime(value: string | number | Date, timeZone?: string): string {
  const date = toDate(value);
  return date
    ? dateFmt(
        'datetime',
        { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' },
        timeZone,
      ).format(date)
    : '–';
}

/** "Di., 22:41" (a moment within the last week) */
export function formatWeekdayTime(value: string | number | Date, timeZone?: string): string {
  const date = toDate(value);
  return date
    ? dateFmt('weekday', { weekday: 'short', hour: '2-digit', minute: '2-digit' }, timeZone).format(date)
    : '–';
}

/**
 * Relative time as the admin showed it before the overhaul: "gerade eben",
 * "vor 1 Min.", "vor 12 Min.", "vor 2 Std. 5 Min." (under 6 h), then "Di., 22:41"
 * within a week, then the date. Future times (clock skew) count as "gerade eben".
 */
export function formatRelative(
  value: string | number | Date,
  now: number = Date.now(),
  timeZone?: string,
): string {
  const date = toDate(value);
  if (!date) return '–';
  const s = Math.max(0, (now - date.getTime()) / 1000);
  if (s < 45) return 'gerade eben';
  if (s < 90) return `vor 1${NBSP}Min.`;
  if (s < 3600) return `vor ${Math.round(s / 60)}${NBSP}Min.`;
  if (s < 6 * 3600) {
    const total = Math.round(s / 60); // whole minutes first: never "60 Min."
    const hours = Math.floor(total / 60);
    const mins = total % 60;
    return `vor ${hours}${NBSP}Std.${mins ? ` ${mins}${NBSP}Min.` : ''}`;
  }
  if (s < 7 * 24 * 3600) return formatWeekdayTime(date, timeZone);
  return formatDate(date, timeZone);
}

/** Monogram of a pseudonym for the guest pass: "Verrückte Ente #2" → "VE". */
export function monogram(name: string): string {
  return name
    .replace(/\s*#\d+$/, '')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w.charAt(0).toLocaleUpperCase('de-DE'))
    .join('');
}
