/**
 * Live-Wall screen API types, written by hand from the wall contract (PLAN-WALL §4.1–4.2).
 * JSON is snake_case like the rest of the API. WINT may replace these with generated types.
 */

export const MODES = ['spotlight', 'gallery', 'categories'] as const;
export type WallMode = (typeof MODES)[number];

export const ALGORITHMS = [
  'newest',
  'random',
  'shuffle',
  'fair',
  'least_shown',
  'fresh_first',
  'highlights',
] as const;
export type WallAlgorithm = (typeof ALGORITHMS)[number];

/** Every transition id of the contract; `random` („Zufall“) picks one of the others. */
export const TRANSITION_IDS = [
  'crossfade',
  'kenburns',
  'spring',
  'dither',
  'pixelate',
  'glitch',
  'polaroid',
  'slot',
  'jelly',
  'stamp',
  'confetti',
  'random',
] as const;
export type WallTransition = (typeof TRANSITION_IDS)[number];
/** The transitions that actually run (everything but `random`). */
export type ConcreteTransition = Exclude<WallTransition, 'random'>;

export type GallerySpeed = 'slow' | 'medium' | 'fast';
export const PRESETS = ['blobs', 'aurora', 'disco', 'confetti', 'plain'] as const;
export type BackgroundPreset = (typeof PRESETS)[number];
export type OverlayCorner = 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left';

export interface PlaylistEntry {
  mode: WallMode;
  enabled: boolean;
  duration_s: number;
}

export interface WallLook {
  preset: BackgroundPreset;
  primary: string;
  secondary: string;
  background: string;
  fps: 30 | 60;
  calm: boolean;
}

export interface WallConfig {
  rev: number;
  updated_at: string | null;
  by: string | null;
  playlist: PlaylistEntry[];
  spotlight: {
    algorithm: WallAlgorithm;
    n: number;
    interval_s: number;
    transition: WallTransition;
    transition_ms: number;
  };
  gallery: { speed: GallerySpeed; rows: number };
  categories: { per_category_s: number; disabled: string[] };
  sources: string[];
  delay_s: number;
  show_instagram: boolean;
  look: WallLook;
  overlay: {
    event_name: boolean;
    counter: boolean;
    qr: boolean;
    /** the chosen QR code (null = the lowest active one); the server resolves it to `qr` */
    qr_code_id?: number | null;
    corner: OverlayCorner;
  };
}

/** The corner's QR code: what it opens (a path: resolve against this page) and its name. */
export interface WallQr {
  url: string;
  name: string;
}

export type AnalysisState = 'pending' | 'running' | 'done' | 'failed' | 'skipped' | 'off';

export interface WallPhoto {
  /** the photo's public id */
  id: string;
  source: string;
  seq: number;
  taken_at: string;
  width: number;
  height: number;
  /** pseudonym */
  author: string;
  instagram: string | null;
  author_key: string;
  urls: { s: string; m: string; l: string };
  facts: { people?: number; faces?: number; hands?: number; smiles?: number };
  analysis: AnalysisState;
}

export type WallCursor = string | number | null;

export interface WallFeed {
  config: WallConfig;
  event_name: string;
  /** `overlay.qr` on and the code active, else null */
  qr: WallQr | null;
  total: number;
  /** newest first */
  photos: WallPhoto[];
  cursor: WallCursor;
  server_time: string;
}

export interface CategoryWinner {
  photo: WallPhoto;
  value: number;
  label: string;
}

export interface WallCategory {
  id: string;
  emoji: string;
  title: string;
  line: string;
  winners: CategoryWinner[];
}

export interface WallSession {
  ok: true;
  via: 'password' | 'admin';
}

/** The stream's events (SSE `event:` name → `data` JSON). */
export type WallEvent =
  | { type: 'hello'; data: { config_rev: number; server_time: string } }
  | { type: 'photo.add'; data: { photo: WallPhoto } }
  | { type: 'photo.update'; data: { photo: WallPhoto } }
  | { type: 'photo.remove'; data: { ids: string[] } }
  | { type: 'config'; data: { config: WallConfig; event_name: string; qr: WallQr | null } }
  | { type: 'categories.changed'; data: Record<string, never> }
  | { type: 'bye'; data: { reason: 'password' | 'logout' } }
  | { type: 'stream.resync'; data: Record<string, never> };

export type WallEventType = WallEvent['type'];

export const EVENT_TYPES: readonly WallEventType[] = [
  'hello',
  'photo.add',
  'photo.update',
  'photo.remove',
  'config',
  'categories.changed',
  'bye',
  'stream.resync',
];

/** The contract's defaults (absent `x.wall.config`); used until the first feed arrives. */
export const DEFAULT_CONFIG: WallConfig = {
  rev: 0,
  updated_at: null,
  by: null,
  playlist: [
    { mode: 'spotlight', enabled: true, duration_s: 120 },
    { mode: 'gallery', enabled: true, duration_s: 45 },
    { mode: 'categories', enabled: true, duration_s: 60 },
  ],
  spotlight: { algorithm: 'fresh_first', n: 12, interval_s: 8, transition: 'random', transition_ms: 1200 },
  gallery: { speed: 'medium', rows: 3 },
  categories: { per_category_s: 10, disabled: [] },
  sources: [],
  delay_s: 20,
  show_instagram: false,
  look: {
    preset: 'blobs',
    primary: '#a855f7',
    secondary: '#ff4fa3',
    background: '#2b2b31',
    fps: 30,
    calm: false,
  },
  overlay: { event_name: true, counter: true, qr: false, qr_code_id: null, corner: 'bottom-right' },
};
