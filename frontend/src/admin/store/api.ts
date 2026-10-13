/**
 * Every admin request goes through here:
 * - the `X-VB-Event-Id` of each answer feeds the stream cursor (cursor.ts);
 * - 401 `admin_required` sends the browser to the login page (with `next`) and the
 *   request never settles, so no error flashes while the page leaves.
 */
import { api, isApiError, unwrap } from '@/api/client';
import type {
  AdminExtension,
  AdminPhoto,
  AdminStats,
  AdminUsersResponse,
  AuditResponse,
  DeviceBan,
  ExportsResponse,
  InstagramHandle,
  PauseState,
  StopState,
  UserDetail,
} from '@/api/types';
import { goLogin, never } from '../lib/nav';
import { noteEventId } from './cursor';
import type { GuestFilter, PhotoFilter, PhotoPage } from './types';

type ClientResult = { data?: unknown; error?: unknown; response: Response };

/** 401 admin_required: leave for the login page; the request never settles. */
function authGate(err: unknown): Promise<never> {
  if (isApiError(err) && err.status === 401 && err.code === 'admin_required') {
    goLogin();
    return never();
  }
  throw err;
}

/** An openapi-fetch call: its data, or an ApiError. */
export async function call<R extends ClientResult>(
  request: Promise<R>,
): Promise<Exclude<R['data'], undefined>> {
  const result = await request;
  noteEventId(result.response.headers.get('X-VB-Event-Id'));
  try {
    return await unwrap(result);
  } catch (err) {
    return authGate(err);
  }
}

// ------------------------------------------------------------------- reads

export const PAGE_SIZE = { live: 30, manage: 48 } as const;

export function fetchPhotos(filter: PhotoFilter, before: string | null, limit: number): Promise<PhotoPage> {
  return call(
    api.GET('/api/admin/photos', {
      params: {
        query: {
          limit,
          ...(filter.ext ? { extension: filter.ext } : {}),
          ...(filter.status === 'all' ? {} : { hidden: filter.status }),
          ...(filter.user === null ? {} : { user_id: String(filter.user) }),
          ...(before ? { before } : {}),
        },
      },
    }),
  );
}

export async function fetchPhoto(id: string): Promise<AdminPhoto> {
  const res = await call(api.GET('/api/admin/photos/{photo_id}', { params: { path: { photo_id: id } } }));
  return res.photo;
}

export function fetchStats(): Promise<AdminStats> {
  return call(api.GET('/api/admin/stats'));
}

export async function fetchExtensions(): Promise<AdminExtension[]> {
  return (await call(api.GET('/api/admin/extensions'))).extensions;
}

export function fetchUsers(filter: GuestFilter, offset: number, limit = 100): Promise<AdminUsersResponse> {
  const { search, status } = filter;
  return call(
    api.GET('/api/admin/users', {
      params: {
        query: {
          limit,
          offset,
          ...(search.trim() ? { search: search.trim() } : {}),
          ...(status === 'banned' ? { banned: 'true' } : status === 'ok' ? { banned: 'false' } : {}),
          ...(status === 'paused' ? { paused: 'true' } : {}),
        },
      },
    }),
  );
}

export function fetchUser(id: number): Promise<UserDetail> {
  return call(api.GET('/api/admin/users/{user_id}', { params: { path: { user_id: id } } }));
}

export async function fetchDeviceBans(): Promise<DeviceBan[]> {
  return (await call(api.GET('/api/admin/device-bans'))).bans;
}

export async function fetchInstagram(): Promise<InstagramHandle[]> {
  return (await call(api.GET('/api/admin/instagram'))).handles;
}

export function fetchAudit(before: number | null): Promise<AuditResponse> {
  return call(
    api.GET('/api/admin/audit', { params: { query: { limit: 100, ...(before ? { before } : {}) } } }),
  );
}

export function fetchStop(): Promise<StopState> {
  return call(api.GET('/api/admin/upload-stop'));
}

export function fetchPause(): Promise<PauseState> {
  return call(api.GET('/api/admin/upload-pause'));
}

export function fetchExports(): Promise<ExportsResponse> {
  return call(api.GET('/api/admin/exports'));
}

/** Plain session check (no redirect logic): for the login page and a closed stream. */
export async function fetchSession(): Promise<boolean> {
  const res = await api.GET('/api/admin/session');
  return Boolean(res.data?.authenticated);
}
