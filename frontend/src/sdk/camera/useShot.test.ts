import { describe, expect, it } from 'vitest';
import { ApiError } from '@/api/errors';
import { shotErrorText } from './useShot';

const err = (status: number, code: string, message = 'Vom Server.', offline = false) => {
  const e = new ApiError(status, code, message);
  e.offline = offline;
  return e;
};

describe('what the print says when a shot is not sent', () => {
  it.each([
    [err(429, 'rate_limited'), 3, 'Langsam! Zu viele Fotos auf einmal. In 3 s nochmal.'],
    [err(429, 'rate_limited'), 0, 'Langsam! Zu viele Fotos auf einmal. Versuch es gleich nochmal.'],
    [err(0, 'network', 'x', true), 0, 'Keine Verbindung.'],
    [err(0, 'network'), 0, 'Keine Verbindung zum Server.'],
    [err(0, 'timeout'), 0, 'Das Hochladen hat zu lange gedauert.'],
    [
      err(403, 'uploads_paused', 'Uploads sind für dich gerade pausiert.'),
      0,
      'Hochladen ist für dich gerade pausiert. Die Gastgeber geben es bald wieder frei.',
    ],
    [
      err(403, 'uploads_stopped', "Uploads sind gerade kurz gestoppt – gleich geht's weiter."),
      0,
      'Hochladen ist kurz angehalten. Gleich geht’s weiter.',
    ],
    [err(403, 'banned', 'Dieses Gerät wurde für Uploads gesperrt.'), 0, 'Dieses Gerät ist gesperrt.'],
    [
      err(400, 'invalid_image', 'Bild muss genau 1080×1440 px groß sein.'),
      0,
      'Bild muss genau 1080×1440 px groß sein.',
    ],
  ])('%s', (error, wait, text) => {
    expect(shotErrorText(error, wait)).toBe(text);
  });

  it('says nothing without an error', () => {
    expect(shotErrorText(null, 0)).toBe('');
  });
});
