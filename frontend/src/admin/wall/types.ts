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
    /** null: wie Theme (Erscheinungsbild: primary / accent / background) */
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

/** The focus object of a winner (categories v2): what the wall frames. */
export interface WinnerObject {
  idx: number;
  label: string;
  label_de: string;
  /** the measure's value for it (a property's score, else its confidence) */
  value: number | null;
  /** 0..1 on the analysed (= shown) photo; null: no frame */
  box: { x: number; y: number; w: number; h: number } | null;
}

export interface CategoryWinner {
  photo_id: string;
  thumb_url: string;
  value: number | null;
  /** headline and detail together („Sonnenbrille · 0,93 Coolness“) */
  label: string;
  /** the object's name (show_object) or the value text */
  headline: string;
  /** the value text when the headline is an object */
  detail: string | null;
  /** the focus object's idx in the photo's object list */
  object_idx: number | null;
  object: WinnerObject | null;
  /** the AI's cached comment on this winner (the best `verdict.count` only) */
  comment: { text: string; emoji: string | null } | null;
}

// ------------------------------------------------- category specs (categories v2)

export interface MeasureValue {
  kind: 'value';
  /** an analyzer's fact, `photo.created_at` or `photo.guest_photos` */
  key: string;
}

export interface ObjectFilter {
  /** only these labels (any of them); empty = all */
  labels: string[];
  exclude: string[];
  /** 0–1 */
  min_confidence: number | null;
}

export const AGGREGATES = ['count', 'max', 'min', 'mean', 'sum', 'top_k_mean', 'count_ge'] as const;
export type Aggregate = (typeof AGGREGATES)[number];

export interface MeasureObjects {
  kind: 'objects';
  where: ObjectFilter;
  /** `confidence` or `prop:<name>`; null for a plain count */
  field: string | null;
  agg: Aggregate;
  /** top_k_mean: 2–5 */
  k: number | null;
  /** count_ge: 0–1 */
  t: number | null;
}

export type Measure = MeasureValue | MeasureObjects;

export const POOL_OPS = ['gt', 'lt', 'gte', 'lte', 'eq', 'ne', 'between', 'exists', 'not_exists'] as const;
export type PoolOp = (typeof POOL_OPS)[number];

export interface PoolCondition {
  measure: Measure;
  op: PoolOp;
  operand: number | [number, number] | null;
}

export type RankOrder = 'desc' | 'asc';

export interface Rank {
  by: Measure;
  order: RankOrder;
  /** desc: only ≥ threshold, asc: only ≤ threshold */
  threshold: number | null;
  then_by: { by: Measure; order: RankOrder }[];
}

export const CAPTION_FORMATS = ['count', 'percent', 'decimal', 'number', 'time', 'text', 'none'] as const;
export type CaptionFormat = (typeof CAPTION_FORMATS)[number];

export interface Caption {
  /** null = rank.by */
  value: Measure | null;
  format: CaptionFormat;
  one: string;
  many: string;
  show_object: boolean;
}

export interface VerdictSpec {
  /** null = the default prompt */
  prompt: string | null;
  /** 1–5 comments, one per best winner */
  count: number;
  /** a Haiku/Sonnet-class model (LlmStatus.verdict.models); null = the provider's cheapest */
  model: string | null;
  effort: 'low' | 'medium' | 'high';
}

export interface CategorySpec {
  version: 2;
  emoji: string;
  title: string;
  /** empty = the generated explanation */
  line: string;
  pool: PoolCondition[];
  rank: Rank;
  select: { count: number; one_per_guest: boolean };
  caption: Caption;
  verdict: VerdictSpec | null;
}

export type OffReason = 'ai_off' | 'property_trashed' | 'property_missing' | 'migrated_inactive';

export interface CategoryLock {
  reason: 'ai_off' | 'property_trashed' | 'property_missing';
  property: string | null;
  /** German */
  message: string;
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
  /** the ranking in plain German (the wall's subtitle when `line` is empty) */
  explanation: string;
  /** it reads an LLM property */
  needs_ai: boolean;
  properties: string[];
  /** why it cannot be switched on right now, or null */
  locked: CategoryLock | null;
  /** switched off by the app, why (until the host switches it) */
  off_reason: OffReason | null;
  off_detail: string | null;
  off_at: string | null;
  available: boolean;
  reason: string | null;
  /** an AI verdict while the AI is not ready: no comments meanwhile */
  verdict_paused: boolean;
  /** deprecated: the best-ranked winner's comment */
  verdict: CategoryVerdict | null;
  winners: CategoryWinner[];
}

export interface CategoryPreview {
  winners: CategoryWinner[];
  /** photos in the pool that pass the threshold */
  matched: number;
  /** German, why nothing can win (an analyzer off, no property yet), else null */
  reason: string | null;
  explanation: string;
  /** the spec as validated (v2) */
  spec: CategorySpec;
  locked: CategoryLock | null;
}

/** A photo value for `{kind: value, key}` (categories v2). */
export interface PhotoValueInfo {
  key: string;
  title: string;
  group: string;
  kind: 'number' | 'count' | 'time';
  unit: string;
  needs: string[];
  available: boolean;
  reason: string | null;
}

export interface ObjectFieldInfo {
  /** `confidence` or `prop:<name>` */
  field: string;
  title: string;
  property: string | null;
  unit: string;
}

export interface AggregateInfo {
  agg: Aggregate;
  title: string;
  needs_field: boolean;
  param: 'k' | 't' | null;
  focus: 'max' | 'min' | 'surest' | null;
}

export interface LabelInfo {
  label: string;
  label_de: string;
  /** photos with that label */
  count: number;
}

export interface ValuesOut {
  photo_values: PhotoValueInfo[];
  object_fields: ObjectFieldInfo[];
  aggregates: AggregateInfo[];
  objects_available: boolean;
  objects_reason: string | null;
  labels: LabelInfo[];
}

// ------------------------------------------------------- export / import (§2)

export interface CategoriesFile {
  format: 'virtubooth-categories';
  version: 2;
  exported_at: string;
  /** each property a category reads (by name), with its prompt */
  properties: Array<{ name: string; prompt: string }>;
  categories: Array<{ id: string; enabled: boolean; preset: string | null; spec: CategorySpec }>;
}

export type OnConflict = 'copy' | 'replace';

export interface CategoryImportResult {
  imported: Array<{ id: string; title: string; enabled: boolean; from_id: string | null; replaced: boolean }>;
  skipped: Array<{ id: string; reason: string }>;
  properties_created: string[];
  /** exist here with another prompt: theirs stays */
  prompt_conflicts: string[];
  switched_off: Array<{ id: string; reason: CategoryLock['reason']; detail: string | null; message: string }>;
  notes: string[];
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
  models: ModelsStatus;
  /** „Erkennung auf“: the image every analyzer and the AI detection read for new photos */
  image: AnalysisImage;
}

export const MODEL_DOWNLOAD_STATES = ['idle', 'running', 'done', 'failed'] as const;
export type ModelDownloadState = (typeof MODEL_DOWNLOAD_STATES)[number];

/** „Modelle herunterladen“: the model files the analyzers need, as the app sees them. */
export interface ModelsStatus {
  /** the ML packages are installed (image built with VB_ML=1) */
  ml: boolean;
  /** needed models that are not on the server */
  missing: string[];
  missing_mb: number;
  /** where downloads go (the data volume) */
  dest: string;
  /** POST /analysis/models/download would fetch something now */
  can_download: boolean;
  download: {
    state: ModelDownloadState;
    current: string | null;
    models: string[];
    done_bytes: number;
    total_bytes: number;
    /** German */
    error: string | null;
    finished_at: string | null;
  };
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
  /** the MERGED object list (local and AI, deduplicated), in idx order: what the poll rates */
  objects: PhotoObject[];
  /** the local model's own list */
  objects_local: SourceObject[];
  /** the external AI's own list (Claude, Mistral) */
  objects_ai: SourceObject[];
  runs: DetectionRun[];
  /** the local detector stood in for the external AI on this photo: why (German); null otherwise */
  objects_fallback: string | null;
  /** the guest's LIVE opt-out flags */
  opt_out: { analysis: boolean; external_ai: boolean };
  /** the latest property scores, one per object (index = idx) */
  properties: Array<{ name: string; inactive: boolean; scores: Array<number | null> }>;
  durations_ms: Record<string, number>;
}

/** GET /admin/photos/analysis?ids=…: what the Live screen shows under a tile. */
export interface PhotoAnalysisSummary {
  photo_id: string;
  state: AnalysisState;
  /** only the key values: people, faces, smiles, happy_max, hands, thumbs_up, peace, rock, glasses, hats, age_groups */
  facts: Record<string, number>;
  /** score to 2 places; box on the full photo (0..1, 3 places), null when the source gave none */
  objects: Array<{
    /** the English key (the COCO class when it is one): the frame's colour */
    label: string;
    label_de: string;
    /** the source that added the entry */
    source: ObjectSource;
    /** every source that found it */
    sources: ObjectSource[];
    score: number;
    box: { x: number; y: number; w: number; h: number } | null;
  }>;
  /** face and hand frames on the full photo (objects carry their own) */
  boxes: Array<{ kind: 'face' | 'hand'; x: number; y: number; w: number; h: number }>;
  opt_out: { analysis: boolean; external_ai: boolean };
  /** analysed while object detection was „Aus“: „Objekterkennung aus“, not „Nichts erkannt“ */
  objects_off: boolean;
  /** the categories this photo currently wins */
  wins: CategoryWin[];
}

/** A category the photo wins right now (the Live chip, which expands). */
export interface CategoryWin {
  id: string;
  emoji: string;
  title: string;
  /** the AI commented on it */
  verdict: boolean;
  /** its place among the winners, 1 = best */
  rank: number;
  headline: string;
  detail: string | null;
  /** the focus object's German name */
  object_label: string | null;
  comment: { text: string; emoji: string | null } | null;
}

export type ObjectSource = 'local' | 'claude' | 'mistral' | (string & {});

export interface PhotoObject {
  idx: number;
  label: string;
  label_de: string;
  score: number;
  box: { x: number; y: number; w: number; h: number } | null;
  /** the source that added the entry */
  source: ObjectSource;
  model: string;
  /** every source whose object is this entry (local and an AI: both found it) */
  sources: ObjectSource[];
}

/** An object as one source found it (its own frozen list). */
export interface SourceObject {
  /** position in the source's own list */
  pos: number;
  label: string;
  label_de: string;
  score: number;
  box: { x: number; y: number; w: number; h: number } | null;
  source: ObjectSource;
  model: string;
  /** the merged entry (`objects[].idx`) it became or is */
  merged_idx: number;
}

export interface DetectionRun {
  source: ObjectSource;
  state: 'done' | 'failed' | 'skipped';
  model: string | null;
  error: string | null;
  /** the image it looked at; null: before the choice existed */
  image?: 'original' | 'filtered' | 'photo' | null;
}

export const ANALYSIS_IMAGES = ['original', 'filtered'] as const;
export type AnalysisImage = (typeof ANALYSIS_IMAGES)[number];
