import { describe, expect, it, vi } from 'vitest';
import { fullscreenAvailable, isFullscreen, toggleFullscreen, type PrefixedDocument } from './screen';

/** A document of an old TV browser: only the `webkit` fullscreen API. */
function webkitDoc(capitalS = false) {
  const doc: PrefixedDocument = { documentElement: {}, webkitFullscreenElement: null };
  const root = document.createElement('div');
  const request = vi.fn<() => void>(() => {
    doc.webkitFullscreenElement = root;
  });
  const exit = vi.fn<() => void>(() => {
    doc.webkitFullscreenElement = null;
  });
  if (capitalS) {
    doc.documentElement.webkitRequestFullScreen = request;
    doc.webkitCancelFullScreen = exit;
  } else {
    doc.webkitFullscreenEnabled = true;
    doc.documentElement.webkitRequestFullscreen = request;
    doc.webkitExitFullscreen = exit;
  }
  return { doc, request, exit };
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
    const request = vi.fn<(options?: FullscreenOptions) => Promise<void>>(() => Promise.resolve());
    const webkit = vi.fn<() => void>();
    const doc: PrefixedDocument = {
      fullscreenEnabled: false,
      fullscreenElement: null,
      webkitFullscreenEnabled: true,
      documentElement: { requestFullscreen: request, webkitRequestFullscreen: webkit },
    };
    expect(fullscreenAvailable(doc)).toBe(false);
    await toggleFullscreen(doc);
    expect(request).toHaveBeenCalledWith({ navigationUI: 'hide' });
    expect(webkit).not.toHaveBeenCalled();
  });

  it('no API at all: not available, toggling does nothing', async () => {
    const doc: PrefixedDocument = { documentElement: {} };
    expect(fullscreenAvailable(doc)).toBe(false);
    await expect(toggleFullscreen(doc)).resolves.toBeUndefined();
  });
});
