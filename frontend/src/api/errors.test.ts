import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { msg } from '@/lib/messages.de';
import {
  ApiError,
  errorFromResponse,
  fatalCopy,
  isApiError,
  setNoAccessHandler,
  unreachable,
} from './errors';

const RATE = { error: 'rate_limited', message: 'Langsam! Zu viele Anfragen. Warte kurz.' };

describe('errorFromResponse', () => {
  let restore: () => void;
  const onNoAccess = vi.fn<() => void>();
  beforeEach(() => {
    onNoAccess.mockReset();
    restore = setNoAccessHandler(onNoAccess);
  });
  afterEach(() => restore());

  it('keeps code, message and body', () => {
    const err = errorFromResponse(403, { error: 'banned', message: 'Dieses Gerät ist gesperrt.' }, null, 'x');
    expect(err).toBeInstanceOf(ApiError);
    expect(err.name).toBe('ApiError');
    expect(err.status).toBe(403);
    expect(err.code).toBe('banned');
    expect(err.message).toBe('Dieses Gerät ist gesperrt.');
    expect(err.retryAfter).toBeNull();
    expect(err.offline).toBe(false);
    expect(err.data).toEqual({ error: 'banned', message: 'Dieses Gerät ist gesperrt.' });
  });

  it('falls back to http_<status> and the fallback text', () => {
    const err = errorFromResponse(502, null, null, 'Da ist etwas schiefgelaufen.');
    expect(err.code).toBe('http_502');
    expect(err.message).toBe('Da ist etwas schiefgelaufen.');
    expect(errorFromResponse(500, 'Internal Server Error', null, 'F').message).toBe('F');
  });

  it('appends the wait in seconds and strips the trailing period', () => {
    const err = errorFromResponse(429, RATE, '12', 'x');
    expect(err.retryAfter).toBe(12);
    expect(err.message).toBe('Langsam! Zu viele Anfragen. Warte kurz (in 12\u00a0s nochmal).');
  });

  it('switches to minutes from 90 seconds on', () => {
    expect(errorFromResponse(429, RATE, '89', 'x').message).toBe(
      'Langsam! Zu viele Anfragen. Warte kurz (in 89\u00a0s nochmal).',
    );
    expect(errorFromResponse(429, RATE, '95', 'x').message).toBe(
      'Langsam! Zu viele Anfragen. Warte kurz (in 2\u00a0min nochmal).',
    );
    expect(errorFromResponse(503, { error: 'x', message: 'Gleich wieder da' }, '600', 'x').message).toBe(
      'Gleich wieder da (in 10\u00a0min nochmal).',
    );
  });

  it('ignores Retry-After on other statuses or when invalid', () => {
    expect(errorFromResponse(400, RATE, '12', 'x').retryAfter).toBeNull();
    expect(errorFromResponse(429, RATE, 'soon', 'x').retryAfter).toBeNull();
    expect(errorFromResponse(429, RATE, '0', 'x').message).toBe(RATE.message);
  });

  it('calls the no-access handler for scan_qr only', () => {
    errorFromResponse(404, { error: 'scan_qr', message: 'Bitte scanne den QR-Code.' }, null, 'x');
    expect(onNoAccess).toHaveBeenCalledTimes(1);
    errorFromResponse(404, { error: 'not_found', message: 'Nicht gefunden.' }, null, 'x');
    expect(onNoAccess).toHaveBeenCalledTimes(1);
  });
});

describe('unreachable', () => {
  it('says offline when the device knows it', () => {
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);
    const err = unreachable(msg.offline, msg.noAnswer);
    expect(err.code).toBe('network');
    expect(err.status).toBe(0);
    expect(err.offline).toBe(true);
    expect(err.message).toBe(msg.offline);
  });

  it('names both causes when the device seems online', () => {
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
    const err = unreachable(msg.offline, msg.noAnswer);
    expect(err.offline).toBe(false);
    expect(err.message).toBe(msg.noAnswer);
  });

  it('uses one text for both when only one is given', () => {
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
    expect(unreachable(msg.uploadOffline).message).toBe(msg.uploadOffline);
  });
});

describe('fatalCopy', () => {
  it('distinguishes offline from no answer', () => {
    const offline = new ApiError(0, 'network', 'x');
    offline.offline = true;
    expect(fatalCopy(offline)).toEqual({ title: msg.offlineTitle, text: msg.offlineText });
    expect(fatalCopy(new ApiError(0, 'network', 'x'))).toEqual({
      title: msg.noAnswerTitle,
      text: msg.noAnswerText,
    });
    expect(msg.noAnswerText).toContain('Blocker');
  });

  it('shows API and camera messages', () => {
    expect(fatalCopy(new ApiError(403, 'banned', 'Dieses Gerät ist gesperrt.')).text).toBe(
      'Dieses Gerät ist gesperrt.',
    );
    class CameraError extends Error {
      override name = 'CameraError';
    }
    expect(fatalCopy(new CameraError('Die Kamera ist blockiert.'))).toEqual({
      title: msg.failedTitle,
      text: 'Die Kamera ist blockiert.',
    });
  });

  it('never shows raw errors', () => {
    expect(fatalCopy(new TypeError('undefined is not a function'))).toEqual({
      title: msg.unknownTitle,
      text: msg.unknownText,
    });
    expect(fatalCopy('boom')).toEqual({ title: msg.unknownTitle, text: msg.unknownText });
  });

  it('recognises ApiError instances', () => {
    expect(isApiError(new ApiError(400, 'x', 'y'))).toBe(true);
    expect(isApiError(new Error('y'))).toBe(false);
  });
});
