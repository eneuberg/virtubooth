import { describe, expect, it } from 'vitest';
import type { PauseState, StopState } from '@/api/types';
import {
  endPausePlan,
  endPauseResult,
  partyControlsCopy,
  partySummary,
  pauseDescription,
  pauseSource,
  pauseSourceShort,
} from './uploadState';

const NOW = new Date('2026-10-13T22:50:00');
const AT = new Date('2026-10-13T22:41:00').toISOString();
const off: StopState = { enabled: false, since: null, by: null };
const on: StopState = { enabled: true, since: AT, by: 'admin:1' };
const noPause: PauseState = {
  enabled: false,
  since: null,
  period: null,
  by: null,
  affected: 0,
  paused_total: 0,
};
const pause = (affected: number): PauseState => ({
  enabled: true,
  since: AT,
  period: 3,
  by: 'admin:1',
  affected,
  paused_total: affected + 1,
});

describe('upload state', () => {
  it('says each switch state in one line, "Lädt…" while unknown', () => {
    expect(partyControlsCopy(undefined, undefined, undefined, NOW)).toEqual({
      uploads: 'Lädt…',
      join: 'Lädt…',
      pause: 'Lädt…',
    });
    expect(partyControlsCopy(off, off, noPause, NOW)).toEqual({
      uploads: 'Alle können hochladen.',
      join: 'Neue Gäste können beitreten.',
      pause: 'Neue Gäste laden sofort hoch.',
    });
    expect(partyControlsCopy(on, on, pause(3), NOW)).toEqual({
      uploads: 'Gestoppt seit 22:41.',
      join: 'Gestoppt seit 22:41.',
      pause: 'Seit 22:41, 3\u00a0Gäste betroffen.',
    });
    expect(pauseDescription(pause(0), NOW)).toBe('Seit 22:41, noch niemand betroffen.');
  });

  it('sums the three switches up for screen readers', () => {
    expect(partySummary(undefined, off, noPause, NOW)).toBe('');
    expect(partySummary(off, off, noPause, NOW)).toBe('Hochladen läuft. Anmeldung offen.');
    expect(partySummary(on, on, pause(1), NOW)).toBe(
      'Hochladen für alle gestoppt seit 22:41. Anmeldung gestoppt seit 22:41. Neue Gäste pausiert seit 22:41.',
    );
  });

  it('switching the new-guest pause off asks only when someone joined meanwhile', () => {
    expect(endPausePlan(pause(0)).ask).toBe(false);
    const one = endPausePlan(pause(1));
    expect(one.ask).toBe(true);
    expect(one.text).toContain('1 Gast ist während der Pause beigetreten');
    expect([one.restoreLabel, one.keepLabel]).toEqual(['Freischalten', 'Pausiert lassen']);
    const many = endPausePlan(pause(4));
    expect([many.restoreLabel, many.keepLabel]).toEqual(['Alle 4 freischalten', 'Alle 4 pausiert lassen']);
  });

  it('reports what ending the pause did', () => {
    expect(endPauseResult({ restored: 2, kept: 0 })).toBe('2 Gäste wieder freigeschaltet.');
    expect(endPauseResult({ restored: 0, kept: 1 })).toBe(
      'Neue Gäste können wieder hochladen. 1 Gast bleibt pausiert.',
    );
    expect(endPauseResult({ restored: 0, kept: 0 })).toBe('Neue Gäste können wieder hochladen.');
  });

  it('explains why a guest is paused', () => {
    const base = { uploads_paused: true, uploads_paused_at: AT, uploads_lock_period: 3 };
    expect(pauseSource({ ...base, uploads_paused_source: 'admin' }, noPause, NOW)).toBe(
      'von Hand pausiert seit 22:41',
    );
    expect(pauseSource({ ...base, uploads_paused_source: 'new_guest_lock' }, pause(1), NOW)).toBe(
      'automatisch: neue Gäste pausiert seit 22:41',
    );
    expect(pauseSource({ ...base, uploads_paused_source: 'new_guest_lock' }, noPause, NOW)).toContain(
      'während der Pause für neue Gäste beigetreten',
    );
    expect(pauseSource({ ...base, uploads_paused: false, uploads_paused_source: null }, noPause)).toBeNull();
    expect(pauseSourceShort({ ...base, uploads_paused_source: 'new_guest_lock' }, NOW)).toBe(
      'automatisch, seit 22:41',
    );
  });
});
