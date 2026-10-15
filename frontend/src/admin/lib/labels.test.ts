import { describe, expect, it } from 'vitest';
import { ApiError } from '@/api/errors';
import { lockoutText } from '../login/lockout';
import {
  auditAction,
  auditActor,
  auditDetails,
  auditTarget,
  describeUA,
  exportJobTitle,
  metaRows,
  releasedText,
  shortHash,
  waitInWords,
} from './labels';

describe('admin labels', () => {
  it('describes devices without middle dots', () => {
    expect(
      describeUA(
        'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1',
      ),
    ).toBe('iPhone, iOS 18.5, Safari 18.5');
    expect(
      describeUA(
        'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36',
      ),
    ).toBe('Android 14, Pixel 7, Chrome 140');
    expect(describeUA('')).toBe('unbekannt');
  });

  it('says waits in words', () => {
    expect(waitInWords(1)).toBe('in 1 Sekunde');
    expect(waitInWords(45)).toBe('in 45 Sekunden');
    expect(waitInWords(60)).toBe('in 1 Minute');
    expect(waitInWords(700)).toBe('in 12 Minuten');
    expect(waitInWords(3 * 3600)).toBe('in 3 Stunden');
  });

  it('shows the login lockout with the wait in words', () => {
    const err = new ApiError(
      429,
      'login_locked',
      'Zu viele Fehlversuche. Login ist kurz gesperrt. (in 12 min nochmal).',
      {
        error: 'login_locked',
        message: 'Zu viele Fehlversuche. Login ist kurz gesperrt.',
      },
    );
    err.retryAfter = 700;
    const text = lockoutText(err, new Date('2026-10-13T22:41:00').getTime());
    expect(text).toBe(
      'Zu viele Fehlversuche. Login ist kurz gesperrt. Versuch es in 12 Minuten nochmal (um 22:52).',
    );
    expect(lockoutText(new ApiError(401, 'wrong_password', 'Falsches Passwort.'))).toBeNull();
  });

  it('says the per-address rate limit once, not the general "Langsam! … Warte kurz" text', () => {
    const at = new Date('2026-10-13T22:41:00').getTime();
    const rate = (wait: number | null) => {
      const err = new ApiError(
        429,
        'rate_limited',
        'Langsam! Zu viele Anfragen. Warte kurz (in 3 s nochmal).',
        {
          error: 'rate_limited',
          message: 'Langsam! Zu viele Anfragen. Warte kurz.',
        },
      );
      err.retryAfter = wait;
      return lockoutText(err, at);
    };
    expect(rate(3)).toBe('Zu viele Versuche hintereinander. Versuch es in 3\u00a0Sekunden nochmal.');
    expect(rate(120)).toBe(
      'Zu viele Versuche hintereinander. Versuch es in 2\u00a0Minuten nochmal (um 22:43).',
    );
    expect(rate(null)).toBe('Zu viele Versuche hintereinander. Warte kurz und versuch es dann nochmal.');
  });

  it('turns meta ids into words', () => {
    const photo = { meta: { vessel: 'cup', facing: 'environment', filter: 'neon', empty: null } };
    const ext = {
      id: 'beer',
      title: 'Beer Cam',
      emoji: '',
      tagline: '',
      url: null,
      uploads: true,
      meta_labels: { vessel: 'Gefäß', facing: 'Kamera', filter: 'Filter' },
      loaded: true,
    };
    expect(metaRows(photo, ext)).toEqual([
      ['Gefäß', 'Becher'],
      ['Kamera', 'Rückkamera'],
      ['Filter', 'Neon'],
    ]);
  });

  it('makes audit entries readable', () => {
    expect(auditActor('anonymous')).toBe('Unbekannt');
    expect(auditActor('admin:edb5eaeb')).toBe('Admin-Sitzung edb5');
    expect(auditActor('guest:12')).toBe('Gast #12');
    expect(auditAction('user.display_name')).toBe('Anzeigename geändert');
    expect(auditTarget('user:12')).toEqual({ kind: 'user', id: 12 });
    expect(auditTarget('photo:abcdefgh')).toEqual({ kind: 'photo', id: 'abcdefgh' });
    expect(auditTarget('fp:0123456789abcdef')).toEqual({ kind: 'device', hash: '0123456789abcdef' });
    expect(auditTarget('instagram:anna.party')).toEqual({ kind: 'instagram', handle: 'anna.party' });
    expect(auditTarget('')).toEqual({ kind: 'text', text: '–' });
    expect(auditDetails({ details: { reason: 'Spam', restore: true } })).toBe(
      'Grund: Spam, freigeschaltet: ja',
    );
    expect(auditDetails({ details: { kind: 'archive', options: { include_hidden: false } } })).toBe(
      'Art: Archiv, Optionen: Ausgeblendete nein',
    );
  });

  it('names activities, booth filters, poster pages and the QR-Bogen code', () => {
    expect(auditTarget('x:booth')).toEqual({ kind: 'extension', id: 'booth' });
    const names = new Map([['sepia', 'Sepia']]);
    expect(auditDetails({ details: { disabled: ['sepia', 'gone'] } }, names)).toBe('aus: Sepia, gone');
    expect(auditDetails({ action: 'poster.layout', details: { page: 0, pages: 3 } })).toBe(
      'Seite: 1, Seiten: 3',
    );
    expect(auditDetails({ details: { kind: 'qr', options: { code_id: 2 } } })).toBe(
      'Art: QR-Bogen, Optionen: QR-Code 2',
    );
    // the QR-Bogen job kind is gone; old audit entries keep their words
  });

  it('counts released devices and shortens hashes', () => {
    expect(releasedText(0)).toBe('');
    expect(releasedText(1)).toBe(', 1 weiteres Gerät entsperrt');
    expect(releasedText(2)).toBe(', 2 weitere Geräte entsperrt');
    expect(shortHash('e6c336695afa0000')).toBe('e6c3 3669');
  });

  it('names export jobs by kind and activity title, not the id', () => {
    const at = '2026-10-13T20:41:00Z';
    const extensions = new Map([['beer', { title: 'Beer Cam' }]]);
    const timelapse = {
      kind: 'timelapse' as const,
      created_at: at,
      options: { extension: 'beer', fps: 12, crossfade: false, include_hidden: false },
    };
    expect(exportJobTitle(timelapse, extensions)).toMatch(/^Zeitraffer \(Beer Cam\) vom /);
    expect(exportJobTitle(timelapse)).toMatch(/^Zeitraffer \(beer\) vom /); // catalogue not loaded yet
    expect(
      exportJobTitle(
        {
          kind: 'archive',
          created_at: at,
          options: { include_db: false, include_hidden: false, filters: 'baked' },
        },
        extensions,
      ),
    ).toMatch(/^Archiv vom /);
    expect(
      exportJobTitle({
        kind: 'archive',
        created_at: at,
        options: { include_db: false, include_hidden: false, filters: 'raw' },
      }),
    ).toMatch(/^Archiv \(ohne Filter \(Originale\)\) vom /);
    expect(
      exportJobTitle({
        kind: 'archive',
        created_at: at,
        options: { include_db: false, include_hidden: false, filters: 'both' },
      }),
    ).toMatch(/^Archiv \(mit und ohne Filter\) vom /);
  });
});
