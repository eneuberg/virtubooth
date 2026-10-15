/**
 * ML-Pipeline admin types for the external AI (PLAN-NIGHT §3 `x.llm.config`, §4.4).
 * The generated schema's types where they are exact (api/types.ts); by hand where the
 * generated ones mark server-defaulted fields optional (config, budget) or are loose
 * (the test run's boxes), checked against the schema in ./contract.ts.
 * The analyzers themselves (GET /analysis) are typed in ../wall/types.ts.
 */
import type {
  LlmDetection,
  MergedTestObject,
  LlmKeyState,
  LlmModel,
  LlmPoller,
  LlmProvider,
  LlmUsageRow,
  LlmUsageTotals,
  TestObject,
} from '@/api/types';
import type { AnalysisBox } from '../wall/types';

export type {
  LlmKeyState,
  MergedTestObject,
  LlmModel,
  LlmPollResponse,
  LlmProperty,
  LlmProvider,
  TestObject,
  LlmUsageRow as UsageRow,
  LlmUsageTotals as UsageTotals,
} from '@/api/types';

export interface LlmBudget {
  party_usd: number | null;
  party_calls: number | null;
  daily_usd: number | null;
  daily_calls: number | null;
}

/** „Denkaufwand“ (Anthropic, DeutschlandGPT): adaptive thinking with this effort */
export const EFFORTS = ['low', 'medium', 'high'] as const;
export type Effort = (typeof EFFORTS)[number];

/** Object detection, either/or: the local detector, the external AI, or none */
export const DETECTION_MODES = ['local', 'ai', 'off'] as const;
export type DetectionMode = (typeof DETECTION_MODES)[number];

export interface LlmConfig {
  /** master switch „Externe KI verwenden“: nothing leaves the server while off */
  enabled: boolean;
  provider: string;
  model: string;
  /** „Eigenschaften abfragen“: the poll (properties, verdicts) runs every poll_interval_s */
  poll: boolean;
  /** 60–3600 */
  poll_interval_s: number;
  /** external: „Objekte mit KI“ is the active detector (the local one is off then) */
  detect: { external: boolean };
  effort: Effort;
  image_max_px: number;
  budget: LlmBudget;
  /** server-set, ignored on input */
  rev: number;
  updated_at: string | null;
  by: string | null;
}

export const POLLER_STATES = ['off', 'idle', 'running', 'blocked'] as const;
export type PollerState = (typeof POLLER_STATES)[number];

/** UsageRow.kind; its ref is the property name or category id, null = all of that kind */
export const USAGE_KINDS = ['detect', 'property', 'verdict', 'test'] as const;
export type UsageKind = (typeof USAGE_KINDS)[number];

export interface Usage {
  party: LlmUsageTotals;
  today: LlmUsageTotals;
  by_kind: LlmUsageRow[];
  budget: LlmBudget;
  /** a limit is reached: every external call stops */
  blocked: boolean;
  reason: string | null;
}

/** The fields PUT /llm/config takes (missing ones stay). */
export type LlmConfigChange = Partial<
  Pick<
    LlmConfig,
    | 'enabled'
    | 'provider'
    | 'model'
    | 'poll'
    | 'poll_interval_s'
    | 'detect'
    | 'effort'
    | 'image_max_px'
    | 'budget'
  >
>;

export interface LlmStatus {
  config: LlmConfig;
  key: LlmKeyState;
  providers: LlmProvider[];
  models: LlmModel[];
  poller: LlmPoller;
  detection: LlmDetection;
  usage: Usage;
}

/** The local pipeline's answer on a test image (D1's TestRun). */
export interface TestRun {
  width: number;
  height: number;
  facts: Record<string, number>;
  boxes: AnalysisBox[];
  details: Array<{ label: string; value: string }>;
  objects: TestObject[];
  durations_ms: Record<string, number>;
  error: string | null;
  /** analyzer → why it did not run (switched off, model missing) */
  skipped: Record<string, string>;
}

export interface TestImageResult {
  width: number;
  height: number;
  local: TestRun | null;
  external: {
    /** claude | mistral | deutschlandgpt */
    source: string;
    model: string;
    objects: TestObject[];
    usage: LlmUsageTotals | null;
    error: string | null;
  } | null;
  /** both lists merged as a photo's would be (what the poll would rate) */
  merged: MergedTestObject[];
}
