import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installPreloadRecovery } from './boot';

const html = (entry: string) =>
  `<!doctype html><script type="module" crossorigin src="/assets/${entry}.js"></script><div id="app"></div>`;

/** What Vite's preload helper does when a lazy chunk fails; then let the check finish. */
async function chunkFails(times = 1): Promise<Event[]> {
  const events = Array.from({ length: times }, () => new Event('vite:preloadError', { cancelable: true }));
  for (const event of events) window.dispatchEvent(event);
  await new Promise((resolve) => setTimeout(resolve, 0));
  return events;
}

describe('preload recovery', () => {
  const fetchMock = vi.fn<(input: string, init?: RequestInit) => Promise<Response>>();
  const reload = vi.fn<() => void>();
  let listener: EventListenerOrEventListenerObject | undefined;

  beforeEach(() => {
    // this page runs the build with the entry e-old (parsed while detached: happy-dom
    // then never tries to load it, like a browser with a script from innerHTML)
    const parsed = document.createElement('div');
    parsed.innerHTML = '<script type="module" crossorigin src="/assets/e-old.js"></script>';
    document.head.replaceChildren(...parsed.childNodes);
    sessionStorage.clear();
    fetchMock.mockReset();
    reload.mockReset();
    vi.stubGlobal('fetch', fetchMock);
    vi.spyOn(location, 'reload').mockImplementation(reload);
  });
  afterEach(() => {
    if (listener) window.removeEventListener('vite:preloadError', listener);
    document.head.replaceChildren();
    vi.useRealTimers();
  });

  function install(): void {
    const add = vi.spyOn(window, 'addEventListener');
    installPreloadRecovery();
    listener = add.mock.calls.find(([type]) => type === 'vite:preloadError')?.[1];
    add.mockRestore();
  }

  it('reloads once when a new deploy serves another entry script', async () => {
    install();
    fetchMock.mockImplementation(() => Promise.resolve(new Response(html('e-new'))));
    await chunkFails(2); // both cards on Start at once
    expect(fetchMock).toHaveBeenCalledWith(location.pathname, { cache: 'no-store', keepalive: true });
    expect(reload).toHaveBeenCalledOnce();
    expect(sessionStorage.getItem('vb_chunk_reload')).toBe('1');
  });

  it('does not reload for the same build: the page is leaving, or the network hiccuped', async () => {
    install();
    fetchMock.mockImplementation(() => Promise.resolve(new Response(html('e-old'))));
    const [event] = await chunkFails();
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(reload).not.toHaveBeenCalled();
    expect(event?.defaultPrevented).toBe(false); // Vite rethrows: the error boundary shows it
  });

  it('does not reload when the check fails (offline)', async () => {
    install();
    fetchMock.mockRejectedValue(new TypeError('NetworkError when attempting to fetch resource.'));
    await chunkFails();
    expect(reload).not.toHaveBeenCalled();
  });

  it('does not reload into an error page (no access any more, a proxy mid-deploy)', async () => {
    install();
    fetchMock.mockImplementation(() => Promise.resolve(new Response('Bad Gateway', { status: 502 })));
    await chunkFails();
    expect(reload).not.toHaveBeenCalled();
  });

  it('does not reload again right after its reload: no loop', async () => {
    sessionStorage.setItem('vb_chunk_reload', '1'); // this page is the reload
    install();
    fetchMock.mockImplementation(() => Promise.resolve(new Response(html('e-new'))));
    await chunkFails();
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(reload).not.toHaveBeenCalled();
  });

  it('may reload again once the page stayed up 30 s (the next deploy)', () => {
    vi.useFakeTimers({ toFake: ['setTimeout'] });
    sessionStorage.setItem('vb_chunk_reload', '1');
    install();
    vi.advanceTimersByTime(29_999);
    expect(sessionStorage.getItem('vb_chunk_reload')).toBe('1');
    vi.advanceTimersByTime(1);
    expect(sessionStorage.getItem('vb_chunk_reload')).toBeNull();
  });
});
