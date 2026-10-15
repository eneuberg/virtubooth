/**
 * Live Wall admin requests (PLAN-WALL §4.3 config/password, §4.4 analysis; PLAN-NIGHT
 * §4.3 analyzers, categories and values).
 * Plain JSON through apiFetch (the hand-written types in types.ts are stricter than the
 * generated ones); a 401 `admin_required` leaves for the login page like store/api.ts call().
 */
import { apiFetch, isApiError, type ApiFetchInit } from '@/api/client';
import { authGate } from '../store/api';
import { editable } from './draft';
import type {
  AnalysisStatus,
  CategoryItem,
  CategoryPreview,
  CategorySpec,
  PasswordState,
  PhotoAnalysis,
  ValuesOut,
  WallAdminOut,
  WallConfig,
} from './types';

const BASE = '/api/x/wall/admin';

export async function wallFetch<T>(path: string, init: ApiFetchInit = {}): Promise<T> {
  try {
    return await apiFetch<T>(`${BASE}${path}`, init);
  } catch (err) {
    return authGate(err);
  }
}

/** The route is not there at all: the wall extension is off on this server. */
export function isRouteMissing(err: unknown): boolean {
  return isApiError(err) && err.status === 404 && err.code === 'http_404';
}

/** No analysis row for this photo (yet). */
export function isNoAnalysis(err: unknown): boolean {
  return isApiError(err) && err.status === 404 && err.code === 'not_found';
}

// ------------------------------------------------------------------- config

export function fetchWallAdmin(): Promise<WallAdminOut> {
  return wallFetch('/config');
}

/** The editable part only; rev, updated_at and by are server-set. */
export function saveWallConfig(config: WallConfig): Promise<WallAdminOut> {
  return wallFetch('/config', { method: 'PUT', json: editable(config) });
}

export function setWallPassword(password: string): Promise<PasswordState> {
  return wallFetch('/password', { method: 'PUT', json: { password } });
}

export function clearWallPassword(): Promise<PasswordState> {
  return wallFetch('/password', { method: 'DELETE' });
}

export function logoutWalls(): Promise<{ ok: boolean }> {
  return wallFetch('/logout', { method: 'POST' });
}

// ---------------------------------------------------------------- categories

export async function fetchWallCategories(): Promise<CategoryItem[]> {
  return (await wallFetch<{ categories: CategoryItem[] }>('/categories')).categories;
}

export function createCategory(id: string, spec: CategorySpec, enabled = true): Promise<CategoryItem> {
  return wallFetch('/categories', { method: 'POST', json: { id, spec, enabled } });
}

export function saveCategory(id: string, spec: CategorySpec, enabled: boolean): Promise<CategoryItem> {
  return wallFetch(`/categories/${encodeURIComponent(id)}`, { method: 'PUT', json: { spec, enabled } });
}

export function deleteCategory(id: string): Promise<{ ok: boolean }> {
  return wallFetch(`/categories/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export async function orderCategories(ids: string[]): Promise<CategoryItem[]> {
  const out = await wallFetch<{ categories: CategoryItem[] }>('/categories/order', {
    method: 'PUT',
    json: { ids },
  });
  return out.categories;
}

export function restorePresets(): Promise<{ added: string[] }> {
  return wallFetch('/categories/restore-presets', { method: 'POST' });
}

/** `specJson`: the spec as JSON text (the editor debounces on it). */
export function previewCategory(specJson: string, signal?: AbortSignal): Promise<CategoryPreview> {
  return wallFetch('/categories/preview', {
    method: 'POST',
    body: `{"spec":${specJson}}`,
    headers: { 'Content-Type': 'application/json' },
    ...(signal ? { signal } : {}),
  });
}

export function fetchValues(): Promise<ValuesOut> {
  return wallFetch('/values');
}

// ------------------------------------------------------------------ analysis

export function fetchAnalysisStatus(): Promise<AnalysisStatus> {
  return wallFetch('/analysis');
}

/** One analyzer on/off, and its settings (they apply to photos analysed from now on). */
export function setAnalyzer(
  name: string,
  change: { enabled: boolean; settings?: Record<string, number> },
): Promise<AnalysisStatus> {
  return wallFetch(`/analysis/analyzers/${encodeURIComponent(name)}`, { method: 'PUT', json: change });
}

/** „Modelle herunterladen“: the missing models, in the background (idempotent). */
export function downloadModels(): Promise<AnalysisStatus> {
  return wallFetch('/analysis/models/download', { method: 'POST' });
}

export function fetchPhotoAnalysis(publicId: string): Promise<PhotoAnalysis> {
  return wallFetch(`/photos/${encodeURIComponent(publicId)}/analysis`);
}
