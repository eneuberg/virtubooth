/**
 * Test data for the ML-Pipeline admin (Vitest only), shaped like PLAN-NIGHT §4.4.
 */
import type { LlmProperty, LlmStatus, TestImageResult } from './types';

export function llmStatus(over: Partial<LlmStatus> = {}): LlmStatus {
  return {
    config: {
      enabled: true,
      provider: 'anthropic',
      model: 'claude-haiku-5-5',
      poll_interval_s: 180,
      detect: { local: true, external: false },
      image_max_px: 1024,
      budget: { party_usd: 5, party_calls: null, daily_usd: 2, daily_calls: null },
      rev: 1,
      updated_at: null,
      by: null,
    },
    key: { set: false, set_at: null, provider: null, valid: false },
    providers: [{ id: 'anthropic', title: 'Anthropic (Claude)', eu: false, available: true, reason: null }],
    models: [
      {
        id: 'claude-haiku-5-5',
        provider: 'anthropic',
        title: 'Claude Haiku 5.5',
        usd_in_mtok: 1,
        usd_out_mtok: 5,
      },
      {
        id: 'claude-sonnet-5-5',
        provider: 'anthropic',
        title: 'Claude Sonnet 5.5',
        usd_in_mtok: 3,
        usd_out_mtok: 15,
      },
      {
        id: 'claude-opus-5-5',
        provider: 'anthropic',
        title: 'Claude Opus 5.5',
        usd_in_mtok: 5,
        usd_out_mtok: 25,
      },
    ],
    poller: { state: 'idle', last_poll_at: null, next_poll_at: null, last_error: null },
    detection: { pending: 0, done: 4, failed: 0 },
    usage: {
      party: { calls: 12, input_tokens: 30_000, output_tokens: 4000, cost_usd: 1.25 },
      today: { calls: 5, input_tokens: 9000, output_tokens: 1000, cost_usd: 0.5 },
      by_kind: [
        { kind: 'detect', ref: null, calls: 4, tokens: 12_000, cost_usd: 0.4 },
        { kind: 'property', ref: 'coolness', calls: 6, tokens: 18_000, cost_usd: 0.7 },
        { kind: 'verdict', ref: 'coolstes_objekt', calls: 2, tokens: 4000, cost_usd: 0.15 },
      ],
      budget: { party_usd: 5, party_calls: null, daily_usd: 2, daily_calls: null },
      blocked: false,
      reason: null,
    },
    ...over,
  };
}

export function properties(): LlmProperty[] {
  return [
    {
      id: 1,
      name: 'coolness',
      prompt: 'Bewerte, wie cool jedes Objekt ist.',
      created_at: '2026-10-15T19:00:00Z',
      archived_at: null,
      scored_photos: 42,
      last_scored_at: '2026-10-15T20:00:00Z',
    },
    {
      id: 2,
      name: 'most_giraffe',
      prompt: 'Wie sehr erinnert das Objekt an eine Giraffe?',
      created_at: '2026-10-15T19:10:00Z',
      archived_at: '2026-10-15T19:30:00Z',
      scored_photos: 10,
      last_scored_at: '2026-10-15T19:25:00Z',
    },
  ];
}

export const testResult: TestImageResult = {
  width: 800,
  height: 600,
  local: {
    width: 800,
    height: 600,
    facts: { faces: 2, brightness: 0.41 },
    boxes: [{ kind: 'face', x: 0.1, y: 0.1, w: 0.2, h: 0.2, label: 'Gesicht', score: 0.9 }],
    details: [{ label: 'Gesichter', value: '2' }],
    objects: [
      { label: 'wine glass', label_de: 'Weinglas', score: 0.87, box: { x: 0.5, y: 0.5, w: 0.1, h: 0.2 } },
    ],
    durations_ms: { basic: 11, faces: 150 },
    error: null,
    skipped: {},
  },
  external: {
    objects: [{ label: 'hat', label_de: 'Hut', score: 0.7, box: { x: 0.2, y: 0, w: 0.2, h: 0.15 } }],
    usage: { calls: 1, input_tokens: 1200, output_tokens: 200, cost_usd: 0.0022 },
    error: null,
  },
};
