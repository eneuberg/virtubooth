import { describe, expect, it } from 'vitest';
import type { Overview } from '@/api/types';
import { freshness, liveStats, minutes, scansSince } from './text';

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
  codes: [],
};

describe('dashboard text', () => {
  it('puts a no-break space before units', () => {
    expect(minutes(5)).toBe('5\u00a0min');
    expect(freshness(overview, NOW)).toMatch(/^„Jetzt“: letzte 5\u00a0min, Stand \d\d:\d\d\.$/);
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
    expect(liveStats(overview)[2]?.label).toBe('Fotos in 15\u00a0min');
  });

  it('says since when scans are counted, or that nobody scanned yet', () => {
    expect(scansSince(overview, NOW)).toMatch(/^Gezählt seit \d\d:\d\d\.$/);
    expect(scansSince({ ...overview, scans: { ...overview.scans, since: null } })).toBe(
      'Noch niemand hat gescannt.',
    );
  });
});
