import { describe, expect, it } from 'vitest';
import {
  NBSP,
  formatBytes,
  formatCount,
  formatDate,
  formatDateTime,
  formatFrame,
  formatNumber,
  formatPercent,
  formatRelative,
  formatSeconds,
  formatTime,
  formatWeekdayTime,
  frameLabel,
  pluralize,
} from './format';

const TZ = 'Europe/Berlin';
// 2026-10-13 22:41:00 in Berlin (CEST, UTC+2)
const AT = '2026-10-13T20:41:00.000+00:00';
const NOW = Date.parse(AT);
const ago = (seconds: number) => new Date(NOW - seconds * 1000).toISOString();

describe('numbers', () => {
  it('groups with dots', () => {
    expect(formatNumber(1_000_000)).toBe('1.000.000');
    expect(formatNumber(30)).toBe('30');
    expect(formatNumber(1234.5)).toBe('1.234,5');
  });

  it('shortens millions with a non-breaking space', () => {
    expect(formatCount(1_000_000)).toBe(`1${NBSP}Mio.`);
    expect(formatCount(2_500_000)).toBe(`2,5${NBSP}Mio.`);
    expect(formatCount(12_340_000)).toBe(`12,3${NBSP}Mio.`);
    expect(formatCount(999_999)).toBe('999.999');
    expect(formatCount(25_000)).toBe('25.000');
  });

  it('pads frame numbers like film edge print', () => {
    expect(formatFrame(31)).toBe('0031');
    expect(formatFrame(0)).toBe('0000');
    expect(formatFrame(12_345)).toBe('12345');
    expect(formatFrame(7, 2)).toBe('07');
    expect(formatFrame(-3)).toBe('0000');
  });

  it('labels frames per activity', () => {
    expect(frameLabel('beer', 32)).toBe(`Bier${NBSP}0032`);
    expect(frameLabel('booth', 18)).toBe(`Foto${NBSP}0018`);
    expect(frameLabel('wall', 3)).toBe(`Wall${NBSP}0003`);
  });

  it('keeps units attached', () => {
    expect(formatPercent(0.4)).toBe(`40${NBSP}%`);
    expect(formatPercent(1)).toBe(`100${NBSP}%`);
    expect(formatPercent(0.4)).not.toContain('\u202f');
    expect(formatSeconds(3)).toBe(`3${NBSP}s`);
  });

  it('pluralizes counts', () => {
    expect(pluralize(1, 'Foto', 'Fotos')).toBe(`1${NBSP}Foto`);
    expect(pluralize(0, 'Foto', 'Fotos')).toBe(`0${NBSP}Fotos`);
    expect(pluralize(1200, 'Gast', 'Gäste')).toBe(`1.200${NBSP}Gäste`);
  });

  it('formats bytes in decimal units', () => {
    expect(formatBytes(512)).toBe(`512${NBSP}Byte`);
    expect(formatBytes(1_234_567)).toBe(`1,2${NBSP}MB`);
    expect(formatBytes(2_000)).toBe(`2${NBSP}kB`);
    expect(formatBytes(3_500_000_000)).toBe(`3,5${NBSP}GB`);
    expect(formatBytes(-5)).toBe(`0${NBSP}Byte`);
  });
});

describe('dates', () => {
  it('formats in the given time zone', () => {
    expect(formatTime(AT, TZ)).toBe('22:41');
    expect(formatDate(AT, TZ)).toBe('13.10.2026');
    expect(formatDateTime(AT, TZ)).toBe('13.10.2026, 22:41');
    expect(formatWeekdayTime(AT, TZ)).toBe('Di., 22:41');
  });

  it('accepts timestamps and dates', () => {
    expect(formatTime(NOW, TZ)).toBe('22:41');
    expect(formatTime(new Date(NOW), TZ)).toBe('22:41');
  });

  it('shows a dash for invalid input', () => {
    expect(formatTime('nope', TZ)).toBe('–');
    expect(formatDate('', TZ)).toBe('–');
    expect(formatRelative('nope', NOW)).toBe('–');
  });
});

describe('formatRelative', () => {
  it('matches the pre-overhaul admin wording', () => {
    expect(formatRelative(ago(0), NOW)).toBe('gerade eben');
    expect(formatRelative(ago(44), NOW)).toBe('gerade eben');
    expect(formatRelative(ago(60), NOW)).toBe(`vor 1${NBSP}Min.`);
    expect(formatRelative(ago(3 * 60), NOW)).toBe(`vor 3${NBSP}Min.`);
    expect(formatRelative(ago(59 * 60), NOW)).toBe(`vor 59${NBSP}Min.`);
    expect(formatRelative(ago(2 * 3600), NOW)).toBe(`vor 2${NBSP}Std.`);
    expect(formatRelative(ago(2 * 3600 + 5 * 60), NOW)).toBe(`vor 2${NBSP}Std. 5${NBSP}Min.`);
  });

  it('never says 60 minutes', () => {
    expect(formatRelative(ago(2 * 3600 + 59 * 60 + 50), NOW)).toBe(`vor 3${NBSP}Std.`);
  });

  it('treats future times as now (clock skew)', () => {
    expect(formatRelative(ago(-30), NOW)).toBe('gerade eben');
  });

  it('switches to weekday and time, then to the date', () => {
    expect(formatRelative(ago(7 * 3600), NOW, TZ)).toBe('Di., 15:41');
    expect(formatRelative(ago(2 * 24 * 3600), NOW, TZ)).toBe('So., 22:41');
    expect(formatRelative(ago(10 * 24 * 3600), NOW, TZ)).toBe('03.10.2026');
  });
});
