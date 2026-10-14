import { describe, expect, it, vi } from 'vitest';
import { fullscreenAvailable, isFullscreen, toggleFullscreen } from './screen';

/** A document of an old TV browser: only the `webkit` fullscreen API. */
function webkitDoc(capitalS = false) {
  const root: Record<string, unknown> = {};
  const doc: Record<string, unknown> = { documentElement: root, webkitFullscreenElement: null };
  const request = vi.fn(() => {
    doc['webkitFullscreenElement'] = root;
  });
  const exit = vi.fn(() => {
    doc['webkitFullscreenElement'] = null;
  });
  if (capitalS) {
    root['webkitRequestFullScreen'] = request;
    doc['webkitCancelFullScreen'] = exit;
  } else {
    doc['webkitFullscreenEnabled'] = true;
    root['webkitRequestFullscreen'] = request;
    doc['webkitExitFullscreen'] = exit;
  }
  return { doc: doc as unknown as Document, request, exit };
}

describe('fullscreen with the webkit prefix', () => {
  it.each([false, true])('enters and leaves (capital S: %s)', async (capitalS) => {
    const { doc, request, exit } = webkitDoc(capitalS);
    expect(fullscreenAvailable(doc)).toBe(true);
    expect(isFullscreen(doc)).toBe(false);
    await toggleFullscreen(doc);
    expect(request).toHaveBeenCalledOnce();
    expect(isFullscreen(doc)).toBe(true);
    await toggleFullscreen(doc);
    expect(exit).toHaveBeenCalledOnce();
    expect(isFullscreen(doc)).toBe(false);
  });

  it('the standard API wins where it exists, also when it says no', async () => {
    const request = vi.fn(() => Promise.resolve());
    const webkit = vi.fn();
    const doc = {
      fullscreenEnabled: false,
      fullscreenElement: null,
      webkitFullscreenEnabled: true,
      documentElement: { requestFullscreen: request, webkitRequestFullscreen: webkit },
    } as unknown as Document;
    expect(fullscreenAvailable(doc)).toBe(false);
    await toggleFullscreen(doc);
    expect(request).toHaveBeenCalledWith({ navigationUI: 'hide' });
    expect(webkit).not.toHaveBeenCalled();
  });

  it('no API at all: not available, toggling does nothing', async () => {
    const doc = { documentElement: {} } as unknown as Document;
    expect(fullscreenAvailable(doc)).toBe(false);
    await expect(toggleFullscreen(doc)).resolves.toBeUndefined();
  });
});
