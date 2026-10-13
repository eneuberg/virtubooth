import { describe, expect, it } from 'vitest';
import { loginUrl, safeNext } from '../lib/nav';
import { parseGuestFilter, parsePhotoFilter, parseSection, sectionHref, withParams } from './manageUrl';

const q = (s: string) => new URLSearchParams(s);

describe('manage URL state', () => {
  it('keeps the pre-overhaul tab names, unknown ones open Fotos', () => {
    expect(parseSection('gaeste')).toBe('gaeste');
    expect(parseSection('export')).toBe('export');
    expect(parseSection('nope')).toBe('fotos');
    expect(parseSection(null)).toBe('fotos');
    expect(sectionHref('fotos')).toBe('/manage');
    expect(sectionHref('sperren')).toBe('/manage?tab=sperren');
  });

  it('reads the photo filters and drops invalid values', () => {
    expect(parsePhotoFilter(q('ext=beer&status=hidden&user=12'))).toEqual({
      ext: 'beer',
      status: 'hidden',
      user: 12,
    });
    expect(parsePhotoFilter(q('ext=Beer!&status=weird&user=0'))).toEqual({
      ext: null,
      status: 'all',
      user: null,
    });
  });

  it('reads the guest filters (show=paused as in the upload sheet link)', () => {
    expect(parseGuestFilter(q('tab=gaeste&show=paused'))).toEqual({ search: '', status: 'paused' });
    expect(parseGuestFilter(q(`q=${'x'.repeat(150)}&show=x`))).toEqual({
      search: 'x'.repeat(100),
      status: 'all',
    });
  });

  it('writes changes and leaves defaults out', () => {
    const next = withParams(q('tab=fotos&ext=beer&photo=abcdefgh'), {
      status: 'hidden',
      ext: null,
      photo: null,
    });
    expect(next.toString()).toBe('tab=fotos&status=hidden');
    expect(withParams(q('tab=gaeste&show=banned'), { show: 'all', tab: 'fotos' }).toString()).toBe('');
  });
});

describe('login redirect', () => {
  it('accepts admin pages with a query, nothing else', () => {
    expect(safeNext('/admin/manage?tab=gaeste&show=paused')).toBe('/admin/manage?tab=gaeste&show=paused');
    expect(safeNext('/admin/user?id=5')).toBe('/admin/user?id=5');
    for (const evil of [
      'https://evil.example/',
      '//evil.example/admin/live',
      '/admin/../x',
      '/admin/Live',
      // oxlint-disable-next-line no-script-url -- the redirect must refuse it
      'javascript:alert(1)',
      '/admin/login',
      '/admin/login?next=/admin/live',
      '/admin/',
      '/admin/user?id=<script>',
      null,
    ]) {
      expect(safeNext(evil)).toBe('/admin/live');
    }
  });

  it('sends the whole page, query included, as next', () => {
    expect(loginUrl({ pathname: '/admin/user', search: '?id=5' })).toBe(
      '/admin/login?next=%2Fadmin%2Fuser%3Fid%3D5',
    );
    expect(loginUrl({ pathname: '/admin/login', search: '' })).toBe('/admin/login');
  });
});
