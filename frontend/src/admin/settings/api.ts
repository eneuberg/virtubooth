/**
 * Allgemeines (and the Fotobox section's filters): reads and writes. Every request goes through `call()` (event cursor,
 * 401 → login); each write puts the server's answer into the cache at once, the event
 * stream's copy (`settings.event`, `extension.settings`) arrives later and changes
 * nothing.
 */
import { useQuery, type QueryClient } from '@tanstack/react-query';
import { api } from '@/api/client';
import type {
  AddressCheck,
  AdminSettings,
  BoothFilterSetting,
  BoothFilterSettings,
  EventSettings,
  PasswordState,
  PublicAddress,
} from '@/api/types';
import { codesKey } from '../codes/keys';
import { call } from '../store/api';
import { extensionSettingsKey, settingsKey } from './keys';

export type {
  AddressCheck,
  AdminSettings,
  BoothFilterSetting,
  BoothFilterSettings,
  EventSettings,
  PasswordState,
  PublicAddress,
};

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

// ------------------------------------------------------- public address

function patchAddress(qc: QueryClient, update: (old: PublicAddress) => PublicAddress): void {
  qc.setQueryData<AdminSettings>(settingsKey, (old) =>
    old ? { ...old, public_address: update(old.public_address) } : old,
  );
}

/** Set the public address (null = VB_PUBLIC_BASE_URL or automatic); the server checks it at once. */
export async function savePublicAddress(qc: QueryClient, address: string | null): Promise<PublicAddress> {
  const res = await call(api.PUT('/api/admin/settings/public-address', { body: { address } }));
  patchAddress(qc, () => res);
  // the codes' links (and the posters') follow the address
  void qc.invalidateQueries({ queryKey: codesKey });
  return res;
}

/** Check the public address now: does it reach this server? */
export async function checkPublicAddress(qc: QueryClient): Promise<AddressCheck> {
  const check = await call(api.POST('/api/admin/settings/public-address/check'));
  patchAddress(qc, (old) => ({ ...old, check }));
  return check;
}

/** A check older than this is repeated when the QR-Codes tab opens. */
export const CHECK_MAX_AGE_MS = 10 * 60_000;

/** The address is fine for printing: checked OK, or automatic (nothing to check). */
export function addressIsFine(check: AddressCheck): boolean {
  return check.status === 'ok' || check.status === 'auto';
}

/** Whether a stored check is missing or older than CHECK_MAX_AGE_MS (auto: never). */
export function checkIsStale(check: AddressCheck, now: number = Date.now()): boolean {
  if (check.status === 'auto') return false;
  if (!check.at) return true;
  const at = new Date(check.at).getTime();
  return Number.isNaN(at) || now - at > CHECK_MAX_AGE_MS;
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
