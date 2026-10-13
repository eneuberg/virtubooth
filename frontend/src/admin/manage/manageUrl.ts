/**
 * The manage area's state in the URL (manageUrl.test.ts). Section names are the
 * pre-overhaul tab names, so old bookmarks keep working:
 *
 *   /admin/manage?tab=fotos|gaeste|instagram|sperren|protokoll|export|uebersicht
 *   Fotos: &ext=<activity>&status=visible|hidden&user=<id>&photo=<id>
 *   Gäste: &q=<search>&show=banned|ok|paused
 *
 * Defaults are left out, invalid values fall back to them.
 */
import type { GuestFilter, GuestStatus, PhotoFilter, PhotoStatus } from '../store/types';

export const SECTIONS = [
  'fotos',
  'gaeste',
  'instagram',
  'sperren',
  'protokoll',
  'qr',
  'export',
  'uebersicht',
] as const;
export type Section = (typeof SECTIONS)[number];

const EXT_RE = /^[a-z][a-z0-9-]{1,30}$/;
const ID_RE = /^[1-9]\d{0,15}$/;

export function parseSection(raw: string | null): Section {
  return SECTIONS.find((s) => s === raw) ?? 'fotos';
}

export function sectionHref(section: Section): string {
  return section === 'fotos' ? '/manage' : `/manage?tab=${section}`;
}

export function parsePhotoFilter(params: URLSearchParams): PhotoFilter {
  const ext = params.get('ext');
  const status = params.get('status');
  const user = params.get('user');
  return {
    ext: ext && EXT_RE.test(ext) ? ext : null,
    status: status === 'visible' || status === 'hidden' ? status : 'all',
    user: user && ID_RE.test(user) ? Number(user) : null,
  };
}

const GUEST_STATUSES: ReadonlyArray<GuestStatus> = ['all', 'banned', 'ok', 'paused'];

export function parseGuestFilter(params: URLSearchParams): GuestFilter {
  const show = params.get('show');
  return {
    search: (params.get('q') ?? '').slice(0, 100),
    status: GUEST_STATUSES.find((s) => s === show) ?? 'all',
  };
}

/**
 * A copy of `params` with `changes` applied: null, '' and default values remove the
 * key (`tab=fotos`, `status=all`, `show=all`).
 */
export function withParams(
  params: URLSearchParams,
  changes: Record<string, string | number | null | undefined>,
): URLSearchParams {
  const next = new URLSearchParams(params);
  for (const [key, value] of Object.entries(changes)) {
    const text = value === null || value === undefined ? '' : String(value);
    const isDefault =
      text === '' ||
      (key === 'tab' && text === 'fotos') ||
      (key === 'status' && text === 'all') ||
      (key === 'show' && text === 'all');
    if (isDefault) next.delete(key);
    else next.set(key, text);
  }
  return next;
}

export function photoStatusParam(status: PhotoStatus): string | null {
  return status === 'all' ? null : status;
}

/** `code=<id>`: the QR code whose sheet is open (`?tab=qr&code=2`), else null. */
export function parseCodeParam(params: URLSearchParams): number | null {
  const code = params.get('code');
  return code && ID_RE.test(code) ? Number(code) : null;
}
