import { afterEach, describe, expect, it } from 'vitest';
import {
  createFilterPreference,
  downloadHref,
  hasOriginal,
  noOriginalHint,
  photoSrc,
  type PhotoVariants,
} from './photoFilter';

const WITH: PhotoVariants = {
  url: '/media/p1',
  thumb_url: '/media/p1?thumb=1',
  raw_url: '/media/p1?variant=raw',
  raw_thumb_url: '/media/p1?variant=raw&thumb=1',
  meta: { filter: 'thermal' },
};
const OLD: PhotoVariants = { ...WITH, raw_url: null, raw_thumb_url: null };
const BEER: PhotoVariants = { ...OLD, meta: { vessel: 'cup' } };
const NORMAL: PhotoVariants = { ...OLD, meta: { filter: 'normal' } };

afterEach(() => localStorage.clear());

describe('„Filter zeigen“', () => {
  it('shows the photo with its filter, or the original when switched off', () => {
    expect(photoSrc(WITH, true)).toBe('/media/p1');
    expect(photoSrc(WITH, true, true)).toBe('/media/p1?thumb=1');
    expect(photoSrc(WITH, false)).toBe('/media/p1?variant=raw');
    expect(photoSrc(WITH, false, true)).toBe('/media/p1?variant=raw&thumb=1');
  });

  it('keeps photos without an original as they are', () => {
    expect(photoSrc(OLD, false)).toBe('/media/p1');
    expect(photoSrc(BEER, false, true)).toBe('/media/p1?thumb=1');
    expect([hasOriginal(WITH), hasOriginal(OLD)]).toEqual([true, false]);
  });

  it('says why a photo cannot switch', () => {
    expect(noOriginalHint(WITH)).toBe('');
    expect(noOriginalHint(NORMAL)).toBe('Ohne Filter aufgenommen.');
    expect(noOriginalHint(BEER)).toBe('Ohne Filter aufgenommen.');
    expect(noOriginalHint(OLD)).toMatch(/Kein Original/);
  });

  it('downloads either version', () => {
    expect(downloadHref(WITH)).toBe('/media/p1?download=1');
    expect(downloadHref(WITH, true)).toBe('/media/p1?variant=raw&download=1');
    expect(downloadHref(OLD, true)).toBe('/media/p1?download=1');
  });

  it('is on by default and remembered in this browser', () => {
    const first = createFilterPreference('vb.test.filter');
    expect(first.getState().show).toBe(true);
    first.getState().setShow(false);
    expect(localStorage.getItem('vb.test.filter')).toBe('off');
    expect(createFilterPreference('vb.test.filter').getState().show).toBe(false);
    expect(createFilterPreference('vb.test.other').getState().show).toBe(true);
  });
});
