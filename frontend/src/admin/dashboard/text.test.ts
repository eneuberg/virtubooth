import { describe, expect, it } from 'vitest';
import type { Overview } from '@/api/types';
import { freshness, liveStats, minutes, scansSince, switchCopy } from './text';

const NOW = new Date('2026-10-13T22:50:00.000+02:00');
const SINCE = '2026-10-13T20:41:00.000+00:00'; // 22:41 in Berlin

const overview: Overview = {
  at: '2026-10-13T20:50:00.000+00:00',
  active_minutes: 5,
  guests: { total: 36, active_now: 12, uploading_now: 4, instagram: 20, banned: 1, paused: 2 },
  scans: { scanned: 48, joined: 36, not_joined: 12, waiting_now: 3, since: SINCE },
  photos: {
    total: 120,
    visible: 110,
    hidden: 10,
    last_15_min: 23,
    last_60_min: 70,
    last_upload_at: SINCE,
  },
  activities: [],
};

describe('dashboard text', () => {
  it('names the switches with the glossary words and says since when they are on', () => {
    const off = switchCopy('uploads', { enabled: false, since: null, by: null }, NOW);
    expect(off.toggle).toBe('Hochladen stoppen');
    expect(off.detail).toBe('Niemand kann hochladen.');
    const on = switchCopy('uploads', { enabled: true, since: SINCE, by: 'admin:1' }, NOW);
    expect(on.title).toBe('Hochladen gestoppt – für alle');
    expect(on.detail).toMatch(/^Seit \d\d:\d\d\. Niemand kann hochladen\.$/);
    expect(on.resumeLabel).toBe('Hochladen fortsetzen');
    const join = switchCopy('join', { enabled: true, since: SINCE, by: 'admin:1' }, NOW);
    expect(join.toggle).toBe('Anmeldung stoppen');
    expect(join.title).toBe('Anmeldung gestoppt');
    expect(join.detail).toMatch(/Niemand Neues kann beitreten\.$/);
    expect(join.resume).toBe('Wieder öffnen');
  });

  it('puts a no-break space before units', () => {
    expect(minutes(5)).toBe('5\u00a0min');
    expect(freshness(overview, NOW)).toMatch(
      /^„Jetzt“ heißt: in den letzten 5\u00a0min\. Stand \d\d:\d\d\.$/,
    );
  });

  it('picks the six live numbers in a fixed order', () => {
    expect(liveStats(overview).map((s) => [s.id, s.value])).toEqual([
      ['active', 12],
      ['uploading', 4],
      ['recent', 23],
      ['scanned', 48],
      ['not-joined', 12],
      ['guests', 36],
    ]);
    expect(liveStats(overview)[2]?.label).toBe('Fotos, letzte 15\u00a0min');
  });

  it('says since when scans are counted, or that nobody scanned yet', () => {
    expect(scansSince(overview, NOW)).toMatch(/^Gezählt seit \d\d:\d\d\.$/);
    expect(scansSince({ ...overview, scans: { ...overview.scans, since: null } })).toBe(
      'Noch niemand hat gescannt.',
    );
  });
});
