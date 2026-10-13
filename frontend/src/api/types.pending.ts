/**
 * TODO(wave 2): regenerate — the provisional openapi.json was exported from the
 * pre-overhaul backend whose routes have no response models. Delete this file once
 * BE-core's `export-openapi` lands and `pnpm gen:api` produces typed responses; switch
 * src/api/types.ts to schema aliases.
 *
 * Provenance: frontend/openapi.json = create_app(settings).openapi() of the main
 * checkout at 1d6b5eb (29 paths; request bodies typed, responses untyped). The shapes
 * below are hand-written from docs/overhaul/analysis/architecture.md §2 and PLAN §3.
 */

/** UTC ISO-8601 with milliseconds, e.g. "2026-10-13T01:39:22.113+00:00" (compares as string). */
export type ISO = string;
/** ^[A-Za-z0-9_-]{8,32}$ */
export type PublicPhotoId = string;
/** ^[0-9a-f]{16,64}$ */
export type FpHash = string;
export type Meta = Record<string, string | number | boolean | null>;

export interface ApiErrorBody {
  error: string;
  message: string;
}

// ----------------------------------------------------------------- guest side

/** Exactly these keys (tested by the API suite). */
export interface GuestUser {
  name: string;
  instagram: string | null;
  banned: boolean;
  uploads_paused: boolean;
}

export interface ConsentInfo {
  version: string;
  title: string;
  paragraphs: string[];
  instagram_prompt: string;
  accept_label: string;
  party_name: string;
  instagram_account: string;
}

export interface GuestPhoto {
  id: PublicPhotoId;
  extension: string;
  seq: number;
  created_at: ISO;
  width: number;
  height: number;
  /** /media/{id} */
  url: string;
  /** /media/{id}?thumb=1 */
  thumb_url: string;
}

export interface PublicExtension {
  id: string;
  title: string;
  emoji: string;
  tagline: string;
  /** /x/{id}/ */
  url: string;
  uploads: boolean;
}

/** GET /api/extensions */
export interface ExtensionsResponse {
  party_name: string;
  instagram_account: string;
  extensions: PublicExtension[];
}

export interface KnownGuest {
  state: 'ok' | 'banned';
  user: GuestUser;
  uploads_stopped: boolean;
  uid_token: string;
}

/** POST /api/identify */
export type IdentifyResponse = { state: 'needs_consent'; consent: ConsentInfo } | KnownGuest;

/** POST /api/join (201 new, 200 when the cookie user already exists) */
export interface JoinResponse extends KnownGuest {
  already_joined: boolean;
  /** only with already_joined: a different handle was kept out */
  instagram_kept?: boolean;
}

/** PATCH /api/me */
export interface MeResponse {
  user: GuestUser;
}

/** GET /api/me/photos (new, PLAN §3): own non-deleted, non-hidden photos, newest first, ≤ 60 */
export interface MyPhotosResponse {
  photos: GuestPhoto[];
}

/** GET /api/x/beer/stats */
export interface BeerStats {
  total: number;
  goal: number;
}

/** POST /api/x/{ext}/upload (201): the photo plus the extension's extras */
export interface UploadResponse {
  photo: GuestPhoto;
  /** beer: the photo's seq */
  beer_number?: number;
  /** beer: visible beer photos, the number to show */
  total?: number;
  /** booth: the photo's seq */
  booth_number?: number;
}

// ----------------------------------------------------------------- admin side

/** The photo's owner; note: no auto_banned here. */
export interface PhotoUser {
  id: number;
  name: string;
  instagram: string | null;
  banned: boolean;
  uploads_paused: boolean;
}

export interface AdminPhoto {
  id: PublicPhotoId;
  extension: string;
  seq: number;
  created_at: ISO;
  width: number;
  height: number;
  bytes: number;
  meta: Meta;
  hidden: boolean;
  hidden_at: ISO | null;
  hidden_reason: 'admin' | 'ban' | null;
  deleted: boolean;
  url: string;
  thumb_url: string;
  user: PhotoUser;
}

export interface AdminUser {
  id: number;
  name: string;
  instagram: string | null;
  created_at: ISO;
  last_seen_at: ISO;
  consent_at: ISO;
  consent_version: string;
  fp_hash: FpHash | null;
  fp_components: Record<string, string | number | boolean | null>;
  first_ip: string;
  last_ip: string;
  user_agent: string;
  banned: boolean;
  banned_at: ISO | null;
  ban_reason: string | null;
  /** non-deleted photos */
  photo_count: number;
  uploads_paused: boolean;
  uploads_paused_at: ISO | null;
  uploads_paused_source: 'admin' | 'new_guest_lock' | null;
  uploads_lock_period: number | null;
}

export interface AutoBan {
  fp_hash: FpHash;
  source_user_id: number | null;
  source_user_name: string | null;
}

/** auto_banned: banned && ban_reason === "Gerät gesperrt (Fingerprint)" */
export interface AdminUserView extends AdminUser {
  auto_banned: boolean;
  auto_ban: AutoBan | null;
}

export interface UserRef {
  id: number;
  name: string;
  instagram: string | null;
  banned: boolean;
  auto_banned: boolean;
}

export interface StopState {
  enabled: boolean;
  since: ISO | null;
  by: string | null;
}

export interface PauseState {
  enabled: boolean;
  since: ISO | null;
  /** null while disabled */
  period: number | null;
  by: string | null;
  /** still paused by this period; 0 when disabled */
  affected: number;
  paused_total: number;
}

/** POST /api/admin/upload-stop */
export interface StopResponse extends StopState {
  changed: boolean;
}

/** POST /api/admin/upload-pause */
export interface PauseResponse extends PauseState {
  changed: boolean;
  restored: number;
  kept: number;
}

export interface AdminExtension extends Omit<PublicExtension, 'url'> {
  url: string | null;
  meta_labels: Record<string, string>;
  loaded: boolean;
}

/** GET /api/admin/extensions */
export interface AdminExtensionsResponse {
  extensions: AdminExtension[];
}

/** GET /api/admin/photos */
export interface AdminPhotosResponse {
  photos: AdminPhoto[];
  next: PublicPhotoId | null;
  /** only without a cursor */
  total?: number;
}

/** GET /api/admin/photos/{id} */
export interface AdminPhotoResponse {
  photo: AdminPhoto;
}

/** POST /api/admin/photos/{id}/hide | unhide */
export interface HideResponse {
  photo: AdminPhoto;
  changed: boolean;
}

/** DELETE /api/admin/photos/{id} */
export interface DeletePhotoResponse {
  ok: true;
  id: PublicPhotoId;
}

/** POST /api/admin/photos/bulk */
export interface BulkResponse {
  action: 'hide' | 'unhide' | 'delete';
  changed: PublicPhotoId[];
  unchanged: PublicPhotoId[];
  missing: PublicPhotoId[];
}

/** GET /api/admin/users */
export interface AdminUsersResponse {
  users: AdminUserView[];
  next_offset: number | null;
}

export interface UserFingerprint {
  fp_hash: FpHash;
  first_seen: ISO;
  last_seen: ISO;
  shared_with: number;
  banned: boolean;
  current: boolean;
  users: UserRef[];
}

/** GET /api/admin/users/{id} */
export interface UserDetail {
  user: AdminUserView;
  fingerprints: UserFingerprint[];
  sharing: UserRef[];
  /** up to 1000, newest first */
  photos: AdminPhoto[];
}

/** POST /api/admin/users/{id}/ban */
export interface BanResponse {
  user: AdminUserView;
  changed: boolean;
  fingerprint_banned: boolean;
  photos: AdminPhoto[];
}

/** POST /api/admin/users/{id}/unban */
export interface UnbanResponse {
  user: AdminUserView;
  changed: boolean;
  fingerprints_unbanned: FpHash[];
  users_unbanned: UserRef[];
  photos: AdminPhoto[];
}

/** POST /api/admin/users/{id}/uploads */
export interface UserUploadsResponse {
  user: AdminUser;
  changed: boolean;
}

export interface DeviceBan {
  fp_hash: FpHash;
  created_at: ISO;
  reason: string;
  source_user_id: number | null;
  source_user_name: string | null;
  users: UserRef[];
}

/** GET /api/admin/device-bans */
export interface DeviceBansResponse {
  bans: DeviceBan[];
}

/** DELETE /api/admin/device-bans/{fp_hash} */
export interface DeviceUnbanResponse {
  ok: true;
  fp_hash: FpHash;
  users_unbanned: UserRef[];
}

/** GET /api/admin/stats */
export interface AdminStats {
  photos: number;
  visible: number;
  hidden: number;
  deleted: number;
  last_upload_at: ISO | null;
  guests: number;
  banned: number;
  /** guests with a handle */
  instagram: number;
  /** distinct handles */
  instagram_handles: number;
  uploaders: number;
  fingerprint_bans: number;
  extensions: Record<string, { photos: number; hidden: number }>;
}

export interface InstagramHandle {
  handle: string;
  users: { id: number; name: string; banned: boolean; photos: number }[];
  photos: number;
  visible: number;
  hidden: number;
  last_upload_at: ISO | null;
  /** ≤ 8, visible, newest first */
  recent: AdminPhoto[];
  /** new (PLAN §3): the host marked this handle as posted/tagged */
  done: boolean;
}

/** GET /api/admin/instagram */
export interface InstagramResponse {
  handles: InstagramHandle[];
}

export interface AuditEntry {
  id: number;
  at: ISO;
  /** "anonymous" | "admin:<8 hex>" */
  actor: string;
  action: string;
  /** "user:<id>" | "photo:<id>" | "fp:<16 hex>" | "ip:<ip>" | "" */
  target: string;
  details: Record<string, unknown>;
}

/** GET /api/admin/audit */
export interface AuditResponse {
  entries: AuditEntry[];
  next: number | null;
}

/** GET /api/admin/session */
export interface SessionResponse {
  authenticated: boolean;
}

/** POST /api/admin/login | logout */
export interface OkResponse {
  ok: true;
}

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
