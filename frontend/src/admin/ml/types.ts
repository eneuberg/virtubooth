/**
 * ML-Pipeline admin types for the external AI (PLAN-NIGHT §3 `x.llm.config`, §4.4),
 * written by hand until INT2 switches to the generated schema. JSON is snake_case.
 * The analyzers themselves (GET /analysis) are typed in ../wall/types.ts.
 */
import type { AnalysisBox } from '../wall/types';

export interface LlmBudget {
  party_usd: number | null;
  party_calls: number | null;
  daily_usd: number | null;
  daily_calls: number | null;
}

export interface LlmConfig {
  enabled: boolean;
  provider: string;
  model: string;
  /** 60–3600 */
  poll_interval_s: number;
  /** „Erkennung beim Hochladen“: both may be on */
  detect: { local: boolean; external: boolean };
  image_max_px: number;
  budget: LlmBudget;
  /** server-set, ignored on input */
  rev: number;
  updated_at: string | null;
  by: string | null;
}

/** The key's state: never the key itself (N11). */
export interface LlmKeyState {
  set: boolean;
  set_at: string | null;
  provider: string | null;
  /** false: it no longer decrypts (VB_SECRET_KEY changed); null = not checked / not set */
  valid: boolean | null;
}

export interface LlmProvider {
  id: string;
  title: string;
  /** hosted in the EU */
  eu: boolean;
  available: boolean;
  reason: string | null;
}

export interface LlmModel {
  id: string;
  title: string;
  /** USD per million input / output tokens */
  usd_in_mtok: number;
  usd_out_mtok: number;
}

export const POLLER_STATES = ['off', 'idle', 'running', 'blocked'] as const;
export type PollerState = (typeof POLLER_STATES)[number];

export interface UsageTotals {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export const USAGE_KINDS = ['detect', 'property', 'verdict', 'test'] as const;
export type UsageKind = (typeof USAGE_KINDS)[number];

export interface UsageRow {
  kind: UsageKind | (string & {});
  /** property name, category id or photo id; null = all of that kind */
  ref: string | null;
  calls: number;
  tokens: number;
  cost_usd: number;
}

export interface Usage {
  party: UsageTotals;
  today: UsageTotals;
  by_kind: UsageRow[];
  budget: LlmBudget;
  /** a limit is reached: every external call stops */
  blocked: boolean;
  reason: string | null;
}

export interface LlmStatus {
  config: LlmConfig;
  key: LlmKeyState;
  providers: LlmProvider[];
  models: LlmModel[];
  poller: {
    state: PollerState;
    last_poll_at: string | null;
    next_poll_at: string | null;
    last_error: string | null;
  };
  detection: { pending: number; done: number; failed: number };
  usage: Usage;
}

export interface LlmProperty {
  id: number;
  name: string;
  prompt: string;
  created_at: string;
  archived_at: string | null;
  scored_photos: number;
  last_scored_at: string | null;
}

/**
 * One object of a test run. D1's `DetectedObject` (label, label_de, score, box); the
 * box may come as [x, y, w, h] (a Python tuple) or {x, y, w, h}: {@link boxOf}.
 */
export interface TestObject {
  label: string;
  label_de: string;
  score: number;
  box: [number, number, number, number] | { x: number; y: number; w: number; h: number } | null;
}

export interface TestRun {
  width: number;
  height: number;
  facts: Record<string, number>;
  boxes: AnalysisBox[];
  details: Array<{ label: string; value: string }>;
  objects: TestObject[];
  durations_ms: Record<string, number>;
  error: string | null;
}

export interface TestImageResult {
  width: number;
  height: number;
  local: TestRun | null;
  external: {
    objects: TestObject[];
    usage: { input_tokens: number; output_tokens: number; cost_usd: number } | null;
    error: string | null;
  } | null;
}
