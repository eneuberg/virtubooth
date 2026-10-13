/**
 * Photo upload over XHR (for progress). OWNER: wave 2 "AC".
 * Port of vb.js uploadJpeg(): POST /api/x/<ext>/upload, Content-Type image/jpeg,
 * X-VB-Meta = encodeURIComponent(JSON.stringify(meta)) only when meta is non-empty,
 * 60 s timeout, errors through errorFromResponse()/unreachable() (src/api/errors.ts);
 * every answer refreshes the session's paused/stopped state.
 */
import type { UploadResponse } from '@/api/types';

export type UploadMeta = Record<string, string | number | boolean | null>;

export interface UploadOptions {
  meta?: UploadMeta;
  /** 0…1 */
  onProgress?: (fraction: number) => void;
  signal?: AbortSignal;
}

export type UploadResult = UploadResponse;

export function uploadPhoto(ext: string, blob: Blob, options: UploadOptions = {}): Promise<UploadResult> {
  void ext;
  void blob;
  void options;
  return Promise.reject(new Error('TODO(wave 2, AC): sdk/upload uploadPhoto'));
}
