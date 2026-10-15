/**
 * Live Wall admin types, written by hand from the contract (PLAN-WALL §4.1, §4.3,
 * §4.4, and PLAN-NIGHT §4.2/§4.3 for analyzers, objects and the category specs);
 * checked against the generated schema (schema.gen.ts), which marks the defaulted
 * config fields optional, so these stay. JSON is snake_case.
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
    /** null: wie Theme (Allgemeines → Erscheinungsbild: primary / accent / background) */
    primary: string | null;
    secondary: string | null;
    background: string | null;
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
  value: number | null;
  label: string;
  /** the object of the photo's object list the value came from (prop.*, objects.*) */
  object_idx: number | null;
}

// ----------------------------------------------------------- category specs (§4.2)

export const CONDITION_OPS = [
  'gt',
  'lt',
  'gte',
  'lte',
  'eq',
  'ne',
  'between',
  'exists',
  'not_exists',
  'contains',
  'not_contains',
  'contains_any',
] as const;
export type ConditionOp = (typeof CONDITION_OPS)[number];

/** number ops: a number; between: [a, b]; exists/not_exists: null; contains*: a label / labels */
export type Operand = number | [number, number] | string | string[] | null;

export interface Condition {
  value: string;
  op: ConditionOp;
  operand: Operand;
}

export const SELECT_ORDERS = ['top', 'bottom'] as const;
export type SelectOrder = (typeof SELECT_ORDERS)[number];

/** a tie-breaker after `by` (contract: `then_by` ≤ 2; shape decided here, see report) */
export interface ThenBy {
  by: string;
  order: SelectOrder;
}

export interface Selection {
  by: string;
  order: SelectOrder;
  count: number;
  then_by: ThenBy[];
  one_per_guest: boolean;
}

export const LABEL_STYLES = ['count', 'percent', 'number', 'time', 'fixed', 'object'] as const;
export type LabelStyle = (typeof LABEL_STYLES)[number];

export interface LabelSpec {
  /** the value the label shows; null = `select.by` */
  value: string | null;
  style: LabelStyle;
  one: string;
  many: string;
}

export interface CategorySpec {
  emoji: string;
  title: string;
  line: string;
  where: Condition[];
  select: Selection;
  label: LabelSpec;
  verdict: { prompt: string } | null;
}

/** The LLM's verdict on a category (the latest poll), as the admin and the wall get it. */
export interface CategoryVerdict {
  text: string;
  emoji: string | null;
  /** public id of the photo it is about, null = none in particular */
  photo_id: string | null;
}

export interface CategoryItem {
  id: string;
  enabled: boolean;
  /** the preset it came from („Vorlage“), null = made by the host */
  preset: string | null;
  position: number;
  spec: CategorySpec;
  available: boolean;
  reason: string | null;
  verdict: CategoryVerdict | null;
  winners: CategoryWinner[];
}

export interface CategoryPreview {
  winners: CategoryWinner[];
  /** photos that meet every condition */
  matched: number;
  /** German, why nothing can win (an analyzer off, no property yet), else null */
  reason: string | null;
}

export const VALUE_KINDS = ['number', 'count', 'labels', 'time'] as const;
export type ValueKind = (typeof VALUE_KINDS)[number];

export interface ValueInfo {
  key: string;
  title: string;
  group: string;
  kind: ValueKind;
  unit: string | null;
  /** the analyzer (or property) it needs; shape not pinned by the contract */
  needs: string | string[] | null;
  available: boolean;
  reason: string | null;
  archived: boolean;
}

export interface LabelInfo {
  label: string;
  label_de: string;
  /** photos with that label */
  count: number;
}

export interface ValuesOut {
  values: ValueInfo[];
  labels: LabelInfo[];
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

export interface AnalyzerStats {
  processed: number;
  errors: number;
  avg_ms: number | null;
  last_ms: number | null;
}

/** One number setting of an analyzer (e.g. objects.score_min). */
export interface AnalyzerSetting {
  key: string;
  title: string;
  min: number;
  max: number;
  step: number;
}

export interface Analyzer {
  name: string;
  title: string;
  kind: AnalyzerKind;
  version: string;
  enabled: boolean;
  available: boolean;
  reason: string | null;
  facts: string[];
  /** German: what it does */
  description: string;
  size_mb: number | null;
  stats: AnalyzerStats;
  /** current values; null = the analyzer has no settings */
  settings: Record<string, number> | null;
  settings_schema: AnalyzerSetting[];
}

export interface AnalysisStatus {
  worker: {
    state: WorkerState;
    ml: boolean;
    message: string | null;
    last_beat_at: string | null;
    /**
     * From a fresh heartbeat of the worker (null / empty without one): photos done
     * since the worker started, its memory in MB, and the analyzers that failed to
     * load (name: error).
     */
    processed: number | null;
    rss_mb: number | null;
    load_errors: Record<string, string>;
  };
  counts: { pending: number; running: number; done: number; failed: number; skipped: number; total: number };
  queue: { pending: number; running: number; oldest_pending_s: number | null };
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
  /** the frozen object list, in idx order */
  objects: PhotoObject[];
  runs: DetectionRun[];
  /** the guest's LIVE opt-out flags */
  opt_out: { analysis: boolean; external_ai: boolean };
  /** the latest property scores, one per object (index = idx) */
  properties: Array<{ name: string; archived: boolean; scores: Array<number | null> }>;
  durations_ms: Record<string, number>;
}

export type ObjectSource = 'local' | 'claude' | 'mistral' | (string & {});

export interface PhotoObject {
  idx: number;
  label: string;
  label_de: string;
  score: number;
  box: { x: number; y: number; w: number; h: number } | null;
  source: ObjectSource;
  model: string;
}

export interface DetectionRun {
  source: ObjectSource;
  state: 'done' | 'failed' | 'skipped';
  model: string | null;
  error: string | null;
}
