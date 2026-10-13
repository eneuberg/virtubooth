/**
 * Friendly names for the API's shapes. Import types from here, never from the
 * generated schema directly, so a schema rename touches one file.
 *
 * Source: `schema.gen.ts`, generated from the backend's OpenAPI export
 * (`cd backend && uv run virtubooth export-openapi -o ../frontend/openapi.json`,
 * then `pnpm gen:api`).
 */
import type { components } from './schema.gen';

type S = components['schemas'];

/** UTC ISO-8601 with milliseconds, e.g. "2026-10-13T01:39:22.113+00:00" (compares as string). */
export type ISO = string;
/** ^[A-Za-z0-9_-]{8,32}$ */
export type PublicPhotoId = string;
/** ^[0-9a-f]{16,64}$ */
export type FpHash = string;
export type Meta = Record<string, string | number | boolean | null>;

export type ApiErrorBody = S['ErrorBody'];
export type ErrorCode = S['ErrorBody']['error'];

// ----------------------------------------------------------------- guest side

export type GuestUser = S['GuestUser'];
export type ConsentInfo = S['ConsentInfo'];
export type GuestPhoto = S['GuestPhoto'];
export type PublicExtension = S['PublicExtension'];
/** GET /api/extensions */
export type ExtensionsResponse = S['ExtensionsOut'];
/** a known device: identify answer `ok` / `banned` (with `join_text`), also the base of JoinOut */
export type KnownGuest = S['IdentifiedOut'];
/** POST /api/identify */
export type IdentifyResponse = S['IdentifiedOut'] | S['NeedsConsentOut'];
/** POST /api/join (201 new, 200 when the cookie user already exists) */
export type JoinResponse = S['JoinOut'];
/** PATCH /api/me */
export type MeResponse = S['MeOut'];
/** GET /api/me/photos: own non-deleted, non-hidden photos, newest first, ≤ 60 */
export type MyPhotosResponse = S['MyPhotosOut'];
export type BeerStats = S['BeerStats'];
/** POST /api/x/{ext}/upload */
export type UploadResponse = S['UploadOut'];
export type BoothFilter = S['BoothFilter'];
/** GET /api/x/booth/filters */
export type BoothFilters = S['BoothFilters'];
/** GET /api/x/booth/stats */
export type BoothStats = S['BoothStats'];

// ----------------------------------------------------------------- admin side

export type PhotoUser = S['PhotoUser'];
export type AdminPhoto = S['AdminPhoto'];
/** Every admin user object has this one shape (incl. auto_banned / auto_ban). */
export type AdminUser = S['AdminUser'];
/** @deprecated same as AdminUser since the restructure */
export type AdminUserView = AdminUser;
export type AutoBan = S['AutoBan'];
export type UserRef = S['UserRef'];
export type StopState = S['StopState'];
export type PauseState = S['PauseState'];
export type StopResponse = S['StopOut'];
export type PauseResponse = S['PauseOut'];
export type AdminExtension = S['AdminExtension'];
export type AdminExtensionsResponse = S['AdminExtensionsOut'];
/** GET /api/admin/photos */
export type AdminPhotosResponse = S['PhotoListOut'];
/** GET /api/admin/photos/{id} */
export type AdminPhotoResponse = S['PhotoOut'];
/** POST /api/admin/photos/{id}/hide | unhide */
export type HideResponse = S['PhotoChangeOut'];
export type DeletePhotoResponse = S['DeletePhotoOut'];
export type BulkResponse = S['BulkOut'];
/** GET /api/admin/users */
export type AdminUsersResponse = S['UserListOut'];
export type UserFingerprint = S['FingerprintOut'];
/** GET /api/admin/users/{id} */
export type UserDetail = S['UserDetailOut'];
export type BanResponse = S['BanOut'];
export type UnbanResponse = S['UnbanOut'];
export type UserUploadsResponse = S['UserUploadsOut'];
export type DeviceBan = S['DeviceBanOut'];
export type DeviceBansResponse = S['DeviceBansOut'];
export type DeviceUnbanResponse = S['DeviceUnbanOut'];
/** GET /api/admin/stats */
export type AdminStats = S['StatsOut'];
export type InstagramHandle = S['InstagramHandleOut'];
export type InstagramUser = S['InstagramUserOut'];
/** GET /api/admin/instagram */
export type InstagramResponse = S['InstagramOut'];
export type AuditEntry = S['AuditEntryOut'];
export type AuditResponse = S['AuditOut'];
export type SessionResponse = S['SessionOut'];
export type OkResponse = S['OkOut'];

// --------------------------------------------------- exports (PLAN §3.2)

export type ExportJob = S['ExportJob'];
export type ExportKind = S['ExportJob']['kind'];
export type ExportStatus = S['ExportJob']['status'];
export type ArchiveOptions = S['ArchiveOptions'];
export type TimelapseOptions = S['TimelapseOptions'];
export type QrOptions = S['QrOptions'];
/** POST /api/admin/exports body (one variant per kind) */
export type ExportRequest = S['ExportIn'];
/** POST /api/admin/exports: 202 + created:true, or 200 + created:false (already queued/running) */
export type ExportCreateResponse = S['ExportCreatedOut'];
/** GET /api/admin/exports */
export type ExportsResponse = S['ExportJobsOut'];
export type ExportDeletedResponse = S['ExportDeletedOut'];
/** POST /api/admin/instagram/{handle}/done */
export type InstagramDoneResponse = S['InstagramDoneOut'];

// ---------------------------------------------- dashboard (live overview)

/** GET /api/admin/overview: live counters (definitions in contracts/api.md §7) */
export type Overview = S['OverviewOut'];
export type OverviewActivity = S['OverviewActivity'];
/** one QR code's numbers in the overview (active codes plus deleted ones with scans) */
export type OverviewCode = S['OverviewCode'];

// ------------------------------------- QR codes, Einstellungen, Plakat (batch QR)

/** one QR code (revoked ones too: `active` false) */
export type AdminCode = S['AdminCode'];
/** GET /api/admin/codes */
export type CodesList = S['CodesOut'];
/** GET /api/admin/settings */
export type AdminSettings = S['AdminSettingsOut'];
export type EventSettings = S['EventSettings'];
export type PasswordState = S['PasswordState'];
/** GET/PUT /api/admin/x/booth/filters */
export type BoothFilterSettings = S['BoothFilterSettingsOut'];
export type BoothFilterSetting = S['BoothFilterSetting'];
/** GET /api/admin/poster */
export type PosterOut = S['PosterOut'];
export type PosterTemplate = S['PosterTemplate'];
/** PUT /api/admin/poster/layout */
export type PosterLayoutIn = S['PosterLayoutIn'];
