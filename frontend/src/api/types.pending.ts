/**
 * Hand-written shapes for endpoints that are not in the OpenAPI export yet
 * (PLAN §3.2: export jobs, built by BE-features in wave 2). Delete this file once
 * they are, and alias the schema in types.ts instead.
 */
type ISO = string;

// --------------------------------------------------------- exports (PLAN §3, new)

export type ExportKind = 'archive' | 'timelapse' | 'qr';
export type ExportStatus = 'queued' | 'running' | 'done' | 'failed';

export interface ExportJob {
  id: string;
  kind: ExportKind;
  status: ExportStatus;
  /** 0..1, null when unknown */
  progress: number | null;
  created_at: ISO;
  started_at: ISO | null;
  finished_at: ISO | null;
  error: string | null;
  file_name: string | null;
  bytes: number | null;
}

export interface ArchiveOptions {
  include_hidden: boolean;
  include_db: boolean;
}
export interface TimelapseOptions {
  extension: string;
  fps: number;
  crossfade: boolean;
  include_hidden: boolean;
}
export interface QrOptions {
  base_url?: string;
}

/** POST /api/admin/exports (202) */
export interface ExportCreateResponse {
  job: ExportJob;
}

/** GET /api/admin/exports */
export interface ExportsResponse {
  jobs: ExportJob[];
}
