import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { canShareFiles, saveImage, shareImage } from './share';

const blob = () => new Blob(['jpeg'], { type: 'image/jpeg' });

let clicks: string[];

beforeEach(() => {
  clicks = [];
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    clicks.push(this.download);
  });
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:x');
  vi.spyOn(URL, 'revokeObjectURL').mockReturnValue(undefined);
});

afterEach(() => {
  Reflect.deleteProperty(navigator, 'share');
  Reflect.deleteProperty(navigator, 'canShare');
});

function withShare(share: (data: ShareData) => Promise<void>, canShare = true) {
  Object.defineProperty(navigator, 'share', {
    configurable: true,
    value: vi.fn<(data: ShareData) => Promise<void>>(share),
  });
  Object.defineProperty(navigator, 'canShare', {
    configurable: true,
    value: vi.fn<() => boolean>(() => canShare),
  });
}

describe('saveImage', () => {
  it('downloads where the browser has no share sheet', async () => {
    await expect(saveImage(blob(), 'beer-00012.jpg', { preferShare: true })).resolves.toBe('downloaded');
    expect(clicks).toEqual(['beer-00012.jpg']);
    expect(canShareFiles()).toBe(false);
  });

  it('shares the file where supported and asked to', async () => {
    withShare(() => Promise.resolve());
    await expect(shareImage(blob(), 'booth-00003.jpg')).resolves.toBe('shared');
    expect(clicks).toEqual([]);
    expect(canShareFiles()).toBe(true);
  });

  it('a closed share sheet is "cancelled", not a download', async () => {
    withShare(() => Promise.reject(new DOMException('closed', 'AbortError')));
    await expect(shareImage(blob(), 'a.jpg')).resolves.toBe('cancelled');
    expect(clicks).toEqual([]);
  });

  it('falls back to a download when sharing fails otherwise', async () => {
    withShare(() => Promise.reject(new DOMException('no activation', 'NotAllowedError')));
    await expect(shareImage(blob(), 'a.jpg')).resolves.toBe('downloaded');
    expect(clicks).toEqual(['a.jpg']);
  });

  it('„Herunterladen“ downloads on Android even with a share sheet (it has no "save to gallery")', async () => {
    withShare(() => Promise.resolve());
    await expect(saveImage(blob(), 'a.jpg')).resolves.toBe('downloaded');
  });

  it('a browser that cannot share files downloads', async () => {
    withShare(() => Promise.resolve(), false);
    await expect(shareImage(blob(), 'a.jpg')).resolves.toBe('downloaded');
  });
});
