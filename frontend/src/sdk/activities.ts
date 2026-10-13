/**
 * The enabled activities: what the server lists on the start screen
 * (GET /api/extensions, in its order) AND what this build has a page for
 * (src/extensions/registry.ts). Used by Start and the activity switcher.
 */
import { useQuery } from '@tanstack/react-query';
import { api, unwrap } from '@/api/client';
import type { ExtensionsResponse, PublicExtension } from '@/api/types';
import { getExtension } from '@/extensions/registry';

export interface Activity {
  id: string;
  /** "Beer Cam" */
  title: string;
  /** the server's tagline (Start may use its own copy) */
  tagline: string;
  /** "/x/beer/" */
  href: string;
  /** takes photos */
  uploads: boolean;
}

export const ACTIVITIES_KEY = ['extensions'] as const;

/**
 * How often the list is fetched again while the page is visible (React Query pauses it
 * in the background): the host may rename the event in the admin, and guests have no
 * event stream.
 */
export const ACTIVITIES_REFRESH_MS = 60_000;

export function fetchActivities(): Promise<ExtensionsResponse> {
  return unwrap(api.GET('/api/extensions'));
}

export function toActivities(extensions: ReadonlyArray<PublicExtension>): Activity[] {
  return extensions
    .filter((ext) => getExtension(ext.id) !== undefined)
    .map((ext) => ({
      id: ext.id,
      title: ext.title,
      tagline: ext.tagline,
      href: `/x/${ext.id}/`,
      uploads: ext.uploads,
    }));
}

/** The party's name, its Instagram account and the activities (refetched every minute). */
export function useActivities() {
  return useQuery({
    queryKey: ACTIVITIES_KEY,
    queryFn: fetchActivities,
    staleTime: 5 * 60_000,
    refetchInterval: ACTIVITIES_REFRESH_MS,
    select: (data) => ({
      partyName: data.party_name,
      instagramAccount: data.instagram_account,
      activities: toActivities(data.extensions),
    }),
  });
}
