import { afterEach, describe, expect, it, vi } from 'vitest';
import { fnvHex, sha256Hex } from './hash';

afterEach(() => {
  vi.doUnmock('./traits');
  vi.resetModules();
});

describe('device traits', () => {
  it('uses the collector chunk when it loads', async () => {
    vi.doMock('./traits', () => ({
      collectTraits: () => Promise.resolve({ hash: 'cd'.repeat(32), components: { ua: 'x', cores: 8 } }),
    }));
    const { getDeviceTraits } = await import('./device');
    await expect(getDeviceTraits()).resolves.toEqual({
      hash: 'cd'.repeat(32),
      components: { ua: 'x', cores: 8 },
    });
  });

  it('falls back to a coarse hash when a blocker kills the chunk, and never rejects', async () => {
    vi.doMock('./traits', () => {
      throw new TypeError('Failed to fetch dynamically imported module');
    });
    const { getDeviceTraits } = await import('./device');
    const traits = await getDeviceTraits();
    expect(traits.components).toEqual({ ua: navigator.userAgent, fallback: true });
    expect(traits.hash).toMatch(/^[0-9a-f]{64}$/);
    // cached: one try per page
    expect(await getDeviceTraits()).toBe(traits);
  });

  it('does not let the preload recovery reload the page for this chunk', async () => {
    vi.doMock('./traits', () => {
      // what Vite's preload helper does before it rethrows
      const event = new Event('vite:preloadError', { cancelable: true });
      window.dispatchEvent(event);
      throw new TypeError('blocked');
    });
    const reloads = vi.fn<(event: Event) => void>();
    const { getDeviceTraits } = await import('./device');
    window.addEventListener('vite:preloadError', reloads); // registered later, like installPreloadRecovery
    await getDeviceTraits();
    window.removeEventListener('vite:preloadError', reloads);
    expect(reloads).not.toHaveBeenCalled();
  });
});

describe('hashes', () => {
  it('sha256 as hex', async () => {
    await expect(sha256Hex('abc')).resolves.toBe(
      'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
    );
  });

  it('the insecure-context fallback has the shape the server accepts', () => {
    expect(fnvHex('virtubooth')).toMatch(/^[0-9a-f]{64}$/);
    expect(fnvHex('a')).not.toBe(fnvHex('b'));
  });
});
