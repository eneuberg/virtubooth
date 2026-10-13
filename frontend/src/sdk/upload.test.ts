import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/errors';
import { FakeXhr, PHOTO } from './fakeXhr.test-util';
import {
  decodeMeta,
  encodeMeta,
  isPermanentUploadError,
  retryAfterSeconds,
  subscribeUploadAnswers,
  uploadPhoto,
  UPLOAD_TIMEOUT_MS,
} from './upload';

const note = vi.hoisted(() => vi.fn<(code: string) => void>());
vi.mock('./session', () => ({ noteUploadAnswer: note }));

const blob = new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xe0])], { type: 'image/jpeg' });

beforeEach(() => {
  FakeXhr.reset();
  vi.stubGlobal('XMLHttpRequest', FakeXhr);
  note.mockClear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function xhr(): FakeXhr {
  if (!FakeXhr.last) throw new Error('no request');
  return FakeXhr.last;
}

describe('meta encoding (X-VB-Meta)', () => {
  it('is encodeURIComponent(JSON) and only sent when there is meta', () => {
    expect(encodeMeta({ vessel: 'bottle', facing: 'environment' })).toBe(
      '%7B%22vessel%22%3A%22bottle%22%2C%22facing%22%3A%22environment%22%7D',
    );
    expect(encodeMeta({})).toBeNull();
    expect(encodeMeta(null)).toBeNull();
    expect(encodeMeta(undefined)).toBeNull();
  });

  it('round-trips umlauts, numbers, booleans and null', () => {
    const meta = { filter: 'bw', note: 'Größe „ok“', n: 3, ok: true, none: null };
    expect(decodeMeta(encodeMeta(meta) ?? '')).toEqual(meta);
  });

  it('stays far below the server limit for real meta', () => {
    expect((encodeMeta({ filter: 'colorpop', facing: 'environment' }) ?? '').length).toBeLessThan(2048);
  });
});

describe('uploadPhoto', () => {
  it('posts the JPEG with type, meta and timeout, reports progress, resolves the answer', async () => {
    const progress: number[] = [];
    const done = uploadPhoto('beer', blob, { meta: { vessel: 'cup' }, onProgress: (p) => progress.push(p) });
    const req = xhr();
    expect(req.method).toBe('POST');
    expect(req.url).toBe('/api/x/beer/upload');
    expect(req.headers['Content-Type']).toBe('image/jpeg');
    expect(req.headers['X-VB-Meta']).toBe(encodeMeta({ vessel: 'cup' }));
    expect(req.timeout).toBe(UPLOAD_TIMEOUT_MS);
    expect(req.body).toBe(blob);
    req.progress(50, 100);
    req.respond(201, { photo: PHOTO, beer_number: 4, total: 3 });
    await expect(done).resolves.toEqual({ photo: PHOTO, beer_number: 4, total: 3 });
    expect(progress).toEqual([0.5, 1]);
  });

  it('sends no meta header without meta', async () => {
    const done = uploadPhoto('booth', blob);
    expect(xhr().headers['X-VB-Meta']).toBeUndefined();
    xhr().respond(201, { photo: PHOTO, booth_number: 1 });
    await done;
  });

  it('maps a 429 with Retry-After', async () => {
    const done = uploadPhoto('beer', blob);
    xhr().respond(
      429,
      { error: 'rate_limited', message: 'Langsam! Zu viele Anfragen. Warte kurz.' },
      { 'Retry-After': '2' },
    );
    const err = await done.catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 429, code: 'rate_limited', retryAfter: 2 });
    expect(err instanceof ApiError && err.message).toBe(
      'Langsam! Zu viele Anfragen. Warte kurz (in 2 s nochmal).',
    );
    expect(retryAfterSeconds(err)).toBe(2);
    expect(note).toHaveBeenCalledWith('rate_limited');
  });

  it.each(['uploads_paused', 'uploads_stopped', 'banned'])('tells the session about 403 %s', async (code) => {
    const answers: string[] = [];
    const off = subscribeUploadAnswers((a) => answers.push(a));
    const done = uploadPhoto('beer', blob);
    xhr().respond(403, { error: code, message: 'Nein.' });
    await expect(done).rejects.toMatchObject({ status: 403, code, message: 'Nein.' });
    expect(note).toHaveBeenCalledWith(code);
    expect(answers).toEqual([code]);
    off();
  });

  it('tells listeners about a success too', async () => {
    const answers: string[] = [];
    const off = subscribeUploadAnswers((a) => answers.push(a));
    const done = uploadPhoto('beer', blob);
    xhr().respond(201, { photo: PHOTO });
    await done;
    expect(answers).toEqual(['ok']);
    off();
  });

  it('falls back to a German message for a body without one', async () => {
    const done = uploadPhoto('beer', blob);
    xhr().respond(502, null);
    await expect(done).rejects.toMatchObject({
      status: 502,
      code: 'http_502',
      message: 'Upload fehlgeschlagen.',
    });
  });

  it('turns a dead network into code network', async () => {
    const done = uploadPhoto('beer', blob);
    xhr().fail();
    await expect(done).rejects.toMatchObject({ status: 0, code: 'network' });
  });

  it('times out after 60 s', async () => {
    const done = uploadPhoto('beer', blob);
    xhr().expire();
    await expect(done).rejects.toMatchObject({
      code: 'timeout',
      message: 'Der Upload hat zu lange gedauert. Nochmal versuchen?',
    });
  });

  it('aborts with the signal', async () => {
    const controller = new AbortController();
    const done = uploadPhoto('beer', blob, { signal: controller.signal });
    controller.abort();
    await expect(done).rejects.toMatchObject({ name: 'AbortError' });
    expect(xhr().aborted).toBe(true);
  });
});

describe('which failures are for good', () => {
  it.each([
    [400, 'invalid_image', true],
    [413, 'too_large', true],
    [415, 'unsupported_type', true],
    [404, 'not_found', true],
    [422, 'invalid_request', true],
    [404, 'scan_qr', false], // the page reloads into the gate; the photo stays
    [401, 'needs_consent', false],
    [403, 'uploads_paused', false],
    [403, 'banned', false],
    [429, 'rate_limited', false],
    [500, 'http_500', false],
    [0, 'network', false],
    [0, 'timeout', false],
  ])('%s %s → permanent: %s', (status, code, permanent) => {
    expect(isPermanentUploadError(new ApiError(status, code, 'x'))).toBe(permanent);
  });

  it('only ApiErrors count', () => {
    expect(isPermanentUploadError(new Error('x'))).toBe(false);
    expect(retryAfterSeconds(new Error('x'))).toBe(0);
  });
});
