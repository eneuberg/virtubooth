import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BEAT_MS, MIN_GAP_MS, startPresence, stopPresence } from './presence';

interface Beat {
  visible: boolean;
  keepalive: boolean;
  at: number;
}

type Reply = { status: number; body: unknown };

/** A fake server for POST /api/here: records the beats, answers `reply`. */
function serve(reply: Reply = { status: 200, body: { ok: true } }) {
  const beats: Beat[] = [];
  const state = { reply };
  const fetchMock = vi.fn<(input: Request | string, init?: RequestInit) => Promise<Response>>(
    async (input, init) => {
      const request = typeof input === 'string' ? new Request(new URL(input, location.href), init) : input;
      expect(new URL(request.url).pathname).toBe('/api/here');
      expect(request.method).toBe('POST');
      const body: unknown = JSON.parse(await request.text());
      const visible = typeof body === 'object' && body !== null && Reflect.get(body, 'visible') === true;
      beats.push({ visible, keepalive: init?.keepalive === true, at: Date.now() });
      return new Response(JSON.stringify(state.reply.body), {
        status: state.reply.status,
        headers: { 'Content-Type': 'application/json' },
      });
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  return { beats, state, fetchMock };
}

function setVisibility(value: 'visible' | 'hidden'): void {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => value });
  document.dispatchEvent(new Event('visibilitychange'));
}

const tick = (ms: number) => vi.advanceTimersByTimeAsync(ms);

describe('presence heartbeat', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });
  });

  afterEach(() => {
    stopPresence();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    Reflect.deleteProperty(document, 'visibilityState');
  });

  it('beats at start and every minute while visible', async () => {
    const { beats } = serve();
    startPresence();
    await tick(0);
    expect(beats).toHaveLength(1);
    expect(beats[0]).toMatchObject({ visible: true, keepalive: false });
    await tick(BEAT_MS - 1);
    expect(beats).toHaveLength(1);
    await tick(1);
    expect(beats).toHaveLength(2);
    await tick(BEAT_MS * 3);
    expect(beats).toHaveLength(5);
    expect(beats.every((b) => b.visible)).toBe(true);
  });

  it('starts only once', async () => {
    const { beats } = serve();
    startPresence();
    startPresence();
    await tick(0);
    expect(beats).toHaveLength(1);
  });

  it('does not beat while hidden, and tells the server once with keepalive', async () => {
    const { beats, fetchMock } = serve();
    startPresence();
    await tick(0);
    setVisibility('hidden');
    await tick(0);
    expect(beats.at(-1)).toMatchObject({ visible: false, keepalive: true });
    expect(fetchMock).toHaveBeenLastCalledWith('/api/here', {
      method: 'POST',
      keepalive: true,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: '{"visible":false}',
    });
    window.dispatchEvent(new Event('pagehide'));
    await tick(BEAT_MS * 5);
    expect(beats.map((b) => b.visible)).toEqual([true, false]);
  });

  it('beats at once when visible again, but not within 15 s of the last beat', async () => {
    const { beats } = serve();
    startPresence();
    await tick(0);
    const start = beats[0]?.at ?? 0;

    setVisibility('hidden');
    await tick(5_000);
    setVisibility('visible');
    await tick(0);
    expect(beats.map((b) => b.visible)).toEqual([true, false]); // 5 s: too soon
    await tick(MIN_GAP_MS - 5_000);
    expect(beats.map((b) => b.visible)).toEqual([true, false, true]);
    expect(beats[2]?.at).toBe(start + MIN_GAP_MS);

    // hidden for longer: at once
    setVisibility('hidden');
    await tick(30_000);
    setVisibility('visible');
    await tick(0);
    expect(beats.map((b) => b.visible)).toEqual([true, false, true, false, true]);
    // and the next one a minute after that
    const last = beats.at(-1)?.at ?? 0;
    await tick(BEAT_MS);
    expect(beats.at(-1)?.at).toBe(last + BEAT_MS);
  });

  it('flapping visibility sends no more than one visible beat per 15 s', async () => {
    const { beats } = serve();
    startPresence();
    await tick(0);
    for (let i = 0; i < 20; i += 1) {
      setVisibility('hidden');
      // oxlint-disable-next-line no-await-in-loop -- one step of fake time after the other
      await tick(500);
      setVisibility('visible');
      // oxlint-disable-next-line no-await-in-loop -- one step of fake time after the other
      await tick(500);
    }
    // 20 s of flapping: the start and one more 15.5 s later
    const visibleBeats = beats.filter((b) => b.visible).map((b) => b.at);
    expect(visibleBeats).toHaveLength(2);
    expect((visibleBeats[1] ?? 0) - (visibleBeats[0] ?? 0)).toBeGreaterThanOrEqual(MIN_GAP_MS);
  });

  it('a page that starts hidden waits until it is shown', async () => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
    const { beats } = serve();
    startPresence();
    await tick(BEAT_MS * 2);
    window.dispatchEvent(new Event('pagehide'));
    expect(beats).toEqual([]);
    setVisibility('visible');
    await tick(0);
    expect(beats.map((b) => b.visible)).toEqual([true]);
  });

  it('stops for good without party access', async () => {
    const { beats } = serve({ status: 404, body: { error: 'scan_qr', message: 'Scanne den QR-Code.' } });
    startPresence();
    await tick(0);
    expect(beats).toHaveLength(1);
    setVisibility('hidden');
    setVisibility('visible');
    window.dispatchEvent(new Event('pagehide'));
    await tick(BEAT_MS * 3);
    expect(beats).toHaveLength(1);
  });

  it('keeps beating after other errors, silently', async () => {
    const { beats, state, fetchMock } = serve({ status: 503, body: { error: 'http_503', message: 'Weg.' } });
    startPresence();
    await tick(0);
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    await tick(BEAT_MS);
    state.reply = { status: 200, body: { ok: true } };
    await tick(BEAT_MS);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(beats).toHaveLength(2); // the rejected call recorded nothing
  });
});
