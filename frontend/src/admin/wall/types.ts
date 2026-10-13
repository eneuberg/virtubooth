/**
 * Live Wall admin types, written by hand from the contract (PLAN-WALL §4.1, §4.3,
 * §4.4); checked against the generated schema (schema.gen.ts), which marks the
 * defaulted config fields optional, so these stay. JSON is snake_case.
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
export type SpotlightAlgorithm = (typeof ALGORITHMS)[number];

export const TRANSITIONS = [
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
export type WallTransition = (typeof TRANSITIONS)[number];

export const SPEEDS = ['slow', 'medium', 'fast'] as const;
export type GallerySpeed = (typeof SPEEDS)[number];

export const PRESETS = ['blobs', 'aurora', 'disco', 'confetti', 'plain'] as const;
export type LookPreset = (typeof PRESETS)[number];

export const CORNERS = ['bottom-right', 'bottom-left', 'top-right', 'top-left'] as const;
export type OverlayCorner = (typeof CORNERS)[number];

export const FPS = [30, 60] as const;
export type WallFps = (typeof FPS)[number];

export interface PlaylistEntry {
  mode: WallMode;
  enabled: boolean;
  duration_s: number;
}

export interface WallConfig {
  /** server-set, ignored on input */
  rev: number;
  updated_at: string | null;
  by: string | null;
  playlist: PlaylistEntry[];
  spotlight: {
    algorithm: SpotlightAlgorithm;
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
  look: {
    preset: LookPreset;
    primary: string;
    secondary: string;
    background: string;
    fps: WallFps;
    calm: boolean;
  };
  overlay: {
    event_name: boolean;
    counter: boolean;
    qr: boolean;
    /** the QR code in the corner (party_codes id); null = the lowest active one */
    qr_code_id: number | null;
    corner: OverlayCorner;
  };
}

export interface WallSource {
  id: string;
  title: string;
  emoji: string;
}

export interface CategoryInfo {
  id: string;
  emoji: string;
  title: string;
  line: string;
  enabled: boolean;
  available: boolean;
  /** German, why the category can't qualify (an analyzer is off or missing) */
  reason: string | null;
}

export interface CategoryWinner {
  photo_id: string;
  thumb_url: string;
  value: number;
  label: string;
}

export interface CategoryOverview extends CategoryInfo {
  winners: CategoryWinner[];
}

export interface WallAdminOut {
  config: WallConfig;
  defaults: WallConfig;
  password: { set: boolean; changed_at: string | null };
  wall_path: string;
  sources: WallSource[];
  categories: CategoryInfo[];
  open_walls: number;
  event_name: string;
}

export interface PasswordState {
  set: boolean;
  changed_at: string | null;
}

export const WORKER_STATES = ['running', 'starting', 'stopped', 'off', 'crashed'] as const;
export type WorkerState = (typeof WORKER_STATES)[number];

export const ANALYSIS_STATES = ['pending', 'running', 'done', 'failed', 'skipped'] as const;
export type AnalysisState = (typeof ANALYSIS_STATES)[number];

export type AnalyzerKind = 'basic' | 'ml';

export interface Analyzer {
  name: string;
  title: string;
  kind: AnalyzerKind;
  version: string;
  enabled: boolean;
  available: boolean;
  reason: string | null;
  facts: string[];
}

export interface AnalysisStatus {
  worker: {
    state: WorkerState;
    ml: boolean;
    message: string | null;
    last_beat_at: string | null;
  };
  counts: { pending: number; running: number; done: number; failed: number; skipped: number; total: number };
  analyzers: Analyzer[];
}

export const BOX_KINDS = ['face', 'hand', 'person', 'object'] as const;
export type BoxKind = (typeof BOX_KINDS)[number];

export interface AnalysisBox {
  kind: BoxKind;
  /** 0..1 of the photo, top-left corner */
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
  score: number;
}

export interface PhotoAnalysis {
  photo_id: string;
  state: AnalysisState;
  attempts: number;
  error: string | null;
  finished_at: string | null;
  versions: Record<string, string>;
  facts: Record<string, number>;
  boxes: AnalysisBox[];
  details: Array<{ label: string; value: string }>;
}
