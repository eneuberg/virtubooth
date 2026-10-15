import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { msg } from '@/lib/messages.de';
import { ApiError, api, apiFetch, unwrap } from './client';
import { setNoAccessHandler } from './errors';

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

describe('api client', () => {
  const fetchMock = vi.fn<(input: Request) => Promise<Response>>();
  let restore: () => void;
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
    restore = setNoAccessHandler(() => {});
  });
  afterEach(() => restore());

  it('returns the data of a successful call', async () => {
    fetchMock.mockResolvedValue(json(200, { authenticated: true }));
    await expect(unwrap(api.GET('/api/admin/session'))).resolves.toEqual({ authenticated: true });
    const request = fetchMock.mock.calls[0]![0];
    expect(new URL(request.url).pathname).toBe('/api/admin/session');
    expect(request.headers.get('Accept')).toBe('application/json');
    expect(request.credentials).toBe('same-origin');
  });

  it('maps a 429 with Retry-After', async () => {
    fetchMock.mockResolvedValue(
      json(
        429,
        { error: 'rate_limited', message: 'Langsam! Zu viele Anfragen. Warte kurz.' },
        { 'Retry-After': '12' },
      ),
    );
    const err = await unwrap(api.GET('/api/extensions')).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({
      status: 429,
      code: 'rate_limited',
      retryAfter: 12,
      message: 'Langsam! Zu viele Anfragen. Warte kurz (in 12\u00a0s nochmal).',
    });
  });

  it('sends JSON bodies', async () => {
    fetchMock.mockResolvedValue(
      json(200, { user: { name: 'x', instagram: null, banned: false, uploads_paused: false } }),
    );
    await unwrap(api.PATCH('/api/me', { body: { instagram: 'lena.k' } }));
    const request = fetchMock.mock.calls[0]![0];
    expect(request.method).toBe('PATCH');
    expect(await request.json()).toEqual({ instagram: 'lena.k' });
  });

  it('turns a network failure into code network', async () => {
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    const err = await unwrap(api.GET('/api/extensions')).catch((e: unknown) => e);
    expect(err).toMatchObject({ name: 'ApiError', code: 'network', status: 0, message: msg.noAnswer });
  });

  it('lets aborts through unchanged', async () => {
    fetchMock.mockRejectedValue(new DOMException('aborted', 'AbortError'));
    const err = await unwrap(api.GET('/api/extensions')).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(DOMException);
  });
});

describe('apiFetch', () => {
  const fetchMock = vi.fn<(input: Request) => Promise<Response>>();
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });

  it('posts JSON and parses the answer', async () => {
    fetchMock.mockResolvedValue(json(202, { job: { id: 'a' } }));
    const data = await apiFetch<{ job: { id: string } }>('/api/admin/exports', {
      method: 'POST',
      json: { kind: 'archive' },
    });
    expect(data.job.id).toBe('a');
    const request = fetchMock.mock.calls[0]![0];
    expect(request.headers.get('Content-Type')).toBe('application/json');
    expect(await request.json()).toEqual({ kind: 'archive' });
  });

  it('maps errors and empty bodies', async () => {
    fetchMock.mockResolvedValue(new Response('', { status: 500 }));
    await expect(apiFetch('/api/x')).rejects.toMatchObject({ code: 'http_500', message: msg.generic });
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(apiFetch('/api/x')).resolves.toBeNull();
  });
});
