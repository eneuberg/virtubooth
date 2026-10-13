/**
 * QR codes: `/api/admin/codes` (list, create, edit, change the token, revoke). Every
 * change answers with the code; it goes straight into the cached list, the
 * `code.changed` event does the same for every other open admin screen.
 */
import { useQuery, type QueryClient } from '@tanstack/react-query';
import { useMemo } from 'react';
import { api, isApiError } from '@/api/client';
import type { SelectOption } from '@/ui/Select';
import { call } from '../store/api';
import { useExtensions } from '../store/hooks';
import { codesKey, withCode, type AdminCode, type CodesList } from './keys';

export type { AdminCode, CodesList };

/** The table refreshes its numbers this often while the page is in front. */
export const CODES_POLL_MS = 15_000;

export function fetchCodes(): Promise<CodesList> {
  return call(api.GET('/api/admin/codes'));
}

export function useCodes() {
  return useQuery({ queryKey: codesKey, queryFn: fetchCodes, refetchInterval: CODES_POLL_MS });
}

export interface Activities {
  /** loaded activities by id: what a code can point to */
  byId: ReadonlyMap<string, { title: string }>;
  /** „Start“ first, then the activities (ids: see `targetOption`) */
  options: ReadonlyArray<SelectOption<string>>;
}

/** The Select's id for „Start“ (target ''): never an activity id (those have no "_"). */
const START_OPTION = '_start';

export function targetOption(target: string): string {
  return target || START_OPTION;
}

export function optionTarget(option: string): string {
  return option === START_OPTION ? '' : option;
}

/** The targets a code can have: Start and every loaded activity that takes photos
 * (not the Live-Wall: it is a TV page, no guest activity). */
export function useActivities(): Activities {
  const { data } = useExtensions();
  return useMemo(() => {
    const loaded = (data ?? []).filter((e) => e.loaded && e.uploads);
    return {
      byId: new Map(loaded.map((e) => [e.id, { title: e.title }])),
      options: [{ id: START_OPTION, label: 'Start' }, ...loaded.map((e) => ({ id: e.id, label: e.title }))],
    };
  }, [data]);
}

/** Where the party runs: VB_PUBLIC_BASE_URL, else this admin page's origin. */
export function partyOrigin(baseUrl: string | null | undefined): string {
  return (baseUrl || window.location.origin).replace(/\/+$/, '');
}

export type FieldErrors = { token?: string | undefined; note?: string | undefined };

/** A server error that belongs to a field of the form (token, note), or null: a toast. */
export function fieldErrors(err: unknown): FieldErrors | null {
  if (!isApiError(err)) return null;
  if (err.code === 'invalid_token' || err.code === 'token_taken') return { token: err.message };
  if (err.code === 'invalid_note') return { note: err.message };
  return null;
}

function remember(qc: QueryClient, code: AdminCode): AdminCode {
  const list = qc.getQueryData<CodesList>(codesKey);
  if (list) qc.setQueryData(codesKey, withCode(list, code));
  return code;
}

export async function createCode(
  qc: QueryClient,
  body: { token: string | null; target: string; note: string },
): Promise<AdminCode> {
  const res = await call(api.POST('/api/admin/codes', { body }));
  return remember(qc, res.code);
}

export async function editCode(
  qc: QueryClient,
  id: number,
  body: { target?: string | null; note?: string | null },
): Promise<AdminCode> {
  const res = await call(
    api.PATCH('/api/admin/codes/{code_id}', { params: { path: { code_id: id } }, body }),
  );
  return remember(qc, res.code);
}

/** `token` null: the server generates one. */
export async function setCodeToken(qc: QueryClient, id: number, token: string | null): Promise<AdminCode> {
  const res = await call(
    api.POST('/api/admin/codes/{code_id}/token', { params: { path: { code_id: id } }, body: { token } }),
  );
  return remember(qc, res.code);
}

export async function revokeCode(qc: QueryClient, id: number): Promise<AdminCode> {
  const res = await call(api.DELETE('/api/admin/codes/{code_id}', { params: { path: { code_id: id } } }));
  return remember(qc, res.code);
}
