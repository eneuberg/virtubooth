/**
 * Einstellungen: reads and writes. Every request goes through `call()` (event cursor,
 * 401 → login); each write puts the server's answer into the cache at once, the event
 * stream's copy (`settings.event`, `extension.settings`) arrives later and changes
 * nothing.
 */
import { useQuery, type QueryClient } from '@tanstack/react-query';
import { api } from '@/api/client';
import type { components } from '@/api/schema.gen';
import { call } from '../store/api';
import { extensionSettingsKey, settingsKey } from './keys';

type S = components['schemas'];

/** GET /api/admin/settings */
export type AdminSettings = S['AdminSettingsOut'];
export type EventSettings = S['EventSettings'];
export type PasswordState = S['PasswordState'];
/** GET/PUT /api/admin/x/booth/filters */
export type BoothFilterSettings = S['BoothFilterSettingsOut'];
export type BoothFilterSetting = S['BoothFilterSetting'];

export const BOOTH_ID = 'booth';
export const boothFiltersKey = extensionSettingsKey(BOOTH_ID);

// ------------------------------------------------------------- settings

export function fetchSettings(): Promise<AdminSettings> {
  return call(api.GET('/api/admin/settings'));
}

export function useSettings() {
  return useQuery({ queryKey: settingsKey, queryFn: fetchSettings });
}

/** The event name in the cached settings (from an answer or a `settings.event`). */
export function patchEvent(qc: QueryClient, event: EventSettings): void {
  qc.setQueryData<AdminSettings>(settingsKey, (old) => (old ? { ...old, event } : old));
}

/** Set the event name; null = back to VB_PARTY_NAME. */
export async function saveEventName(qc: QueryClient, name: string | null): Promise<EventSettings> {
  const res = await call(api.PUT('/api/admin/settings/event', { body: { name } }));
  const event: EventSettings = {
    name: res.name,
    default_name: res.default_name,
    custom: res.custom,
    updated_at: res.updated_at,
    by: res.by,
  };
  patchEvent(qc, event);
  return event;
}

/** Change the admin password; returns how many other devices were logged out. */
export async function changePassword(qc: QueryClient, current: string, next: string): Promise<number> {
  const res = await call(api.POST('/api/admin/settings/password', { body: { current, new: next } }));
  void qc.invalidateQueries({ queryKey: settingsKey });
  return res.sessions_ended;
}

// ---------------------------------------------------------- booth filters

export function fetchBoothFilters(): Promise<BoothFilterSettings> {
  return call(api.GET('/api/admin/x/booth/filters'));
}

export function useBoothFilters(enabled = true) {
  return useQuery({ queryKey: boothFiltersKey, queryFn: fetchBoothFilters, enabled });
}

/** Which filters guests get (the full list of the enabled ids, at least one). */
export async function saveBoothFilters(qc: QueryClient, enabled: string[]): Promise<BoothFilterSettings> {
  const res = await call(api.PUT('/api/admin/x/booth/filters', { body: { enabled } }));
  qc.setQueryData(boothFiltersKey, res);
  return res;
}
