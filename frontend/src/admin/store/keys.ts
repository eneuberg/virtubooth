/**
 * Query keys of the admin app. Everything lives under ['admin', …] so a
 * `stream.resync` can invalidate it in one go.
 */
import type { GuestFilter, PhotoFilter } from './types';

export type PhotoScope = 'live' | 'manage';

export const qk = {
  all: ['admin'] as const,
  /** every photo list (live and manage, any filter) */
  photoLists: ['admin', 'photos'] as const,
  photos: (scope: PhotoScope, filter: PhotoFilter) => ['admin', 'photos', scope, filter] as const,
  photo: (id: string) => ['admin', 'photo', id] as const,
  stats: ['admin', 'stats'] as const,
  extensions: ['admin', 'extensions'] as const,
  /** the guests table (any filter) */
  userLists: ['admin', 'users'] as const,
  users: (filter: GuestFilter) => ['admin', 'users', filter] as const,
  /** every guest with photos, for the "Gast" filter */
  userOptions: ['admin', 'user-options'] as const,
  /** every user page */
  userDetails: ['admin', 'user'] as const,
  user: (id: number) => ['admin', 'user', id] as const,
  bannedUsers: ['admin', 'banned-users'] as const,
  deviceBans: ['admin', 'device-bans'] as const,
  instagram: ['admin', 'instagram'] as const,
  audit: ['admin', 'audit'] as const,
  uploadStop: ['admin', 'upload-stop'] as const,
  uploadPause: ['admin', 'upload-pause'] as const,
  pausedUsers: ['admin', 'paused-users'] as const,
  exports: ['admin', 'exports'] as const,
};
