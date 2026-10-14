/**
 * Live Wall admin requests (PLAN-WALL §4.3 config/password/categories, §4.4 analysis).
 * Plain JSON through apiFetch (the hand-written types in types.ts are stricter than the
 * generated ones); a 401 `admin_required` leaves for the login page like store/api.ts call().
 */
import { apiFetch, isApiError, type ApiFetchInit } from '@/api/client';
import { authGate } from '../store/api';
import { editable } from './draft';
import type {
  AnalysisStatus,
  CategoryOverview,
  PasswordState,
  PhotoAnalysis,
  WallAdminOut,
  WallConfig,
} from './types';

const BASE = '/api/x/wall/admin';

async function wallFetch<T>(path: string, init: ApiFetchInit = {}): Promise<T> {
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

export async function fetchWallCategories(): Promise<CategoryOverview[]> {
  return (await wallFetch<{ categories: CategoryOverview[] }>('/categories')).categories;
}

// ------------------------------------------------------------------ analysis

export function fetchAnalysisStatus(): Promise<AnalysisStatus> {
  return wallFetch('/analysis');
}

export function setDisabledAnalyzers(disabled: string[]): Promise<AnalysisStatus> {
  return wallFetch('/analysis/analyzers', { method: 'PUT', json: { disabled } });
}

export function rerunAnalysis(scope: 'failed' | 'all'): Promise<{ queued: number }> {
  return wallFetch('/analysis/rerun', { method: 'POST', json: { scope } });
}

export function fetchPhotoAnalysis(publicId: string): Promise<PhotoAnalysis> {
  return wallFetch(`/photos/${encodeURIComponent(publicId)}/analysis`);
}

export function reanalyzePhoto(publicId: string): Promise<PhotoAnalysis> {
  return wallFetch(`/photos/${encodeURIComponent(publicId)}/analysis`, { method: 'POST' });
}
