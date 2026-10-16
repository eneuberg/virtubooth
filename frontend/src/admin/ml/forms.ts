/**
 * Pure helpers of the ML-Pipeline cards (forms.test.ts): validation, limits, states.
 */
import { isApiError } from '@/api/client';
import { formatNumber } from '@/lib/format';
import { errorText } from '../common/usePhotoActions';
import { parseDecimal } from '../wall/categories/spec';
import type { Effort, LlmKeyState, LlmStatus, PollerState } from './types';

export const POLLER_LABELS: Record<PollerState, string> = {
  off: 'aus',
  idle: 'wartet',
  running: 'fragt gerade ab',
  blocked: 'pausiert',
};

export const DETECTION_LABELS: Record<PollerState, string> = {
  off: 'aus',
  idle: 'bereit',
  running: 'erkennt gerade',
  blocked: 'pausiert',
};

/** The usage kinds of each part of the external AI. */
export const PART_KINDS = { detection: ['detect'], poll: ['property', 'verdict'] } as const;
export type LlmPart = keyof typeof PART_KINDS;

/** What a part cost so far (the usage meter's rows of its kinds). */
export function partUsage(status: Pick<LlmStatus, 'usage'>, part: LlmPart): { calls: number; usd: number } {
  const kinds: readonly string[] = PART_KINDS[part];
  let calls = 0;
  let usd = 0;
  for (const row of status.usage.by_kind) {
    if (!kinds.includes(row.kind)) continue;
    calls += row.calls;
    usd += row.cost_usd;
  }
  return { calls, usd };
}

/** Why a part is off although its own switch may be on, else null. */
export function partOffReason(status: Pick<LlmStatus, 'config' | 'key'>, partOn: boolean): string | null {
  if (!status.config.enabled) return 'Externe KI ist aus.';
  if (!partOn) return 'ausgeschaltet';
  if (!status.key.set || !status.key.valid) return 'Kein gültiger API-Schlüssel.';
  return null;
}

/**
 * Why nothing can go to the external AI right now (the red hint next to every AI feature):
 * `off` (master switch „Externe KI verwenden“ off), `key` (no usable key), null: ready.
 */
export function aiUnavailable(status: Pick<LlmStatus, 'config' | 'key'> | undefined): 'off' | 'key' | null {
  if (!status) return null;
  if (!status.config.enabled) return 'off';
  if (!status.key.set || !status.key.valid) return 'key';
  return null;
}

export const EFFORT_LABELS: Record<Effort, string> = {
  low: 'gering (Standard)',
  medium: 'mittel',
  high: 'hoch',
};

/** 1–60 whole minutes (the server takes 60–3600 s). */
export function parseMinutes(text: string): number | null {
  const t = text.trim();
  if (!/^\d{1,2}$/.test(t)) return null;
  const n = Number(t);
  return n >= 1 && n <= 60 ? n : null;
}

const NO_KEY: Omit<LlmKeyState, 'provider'> = { set: false, set_at: null, valid: false };

/** The stored key state of one provider (one key each). */
export function keyOf(status: LlmStatus, provider: string): LlmKeyState {
  return (
    status.keys.find((k) => k.provider === provider) ??
    (status.key.provider === provider ? status.key : { ...NO_KEY, provider })
  );
}

/** „gesetzt“ / „nicht gesetzt“; never anything of the key itself. */
export function keyStatusText(key: LlmKeyState): string {
  if (!key.set) return 'nicht gesetzt';
  if (!key.valid) return 'Schlüssel ungültig, bitte neu eingeben';
  return 'gesetzt';
}

/** German text of a failed test run. */
export function testErrorText(err: unknown): string {
  if (isApiError(err) && err.code === 'worker_off') return 'Die Analyse läuft gerade nicht.';
  return errorText(err);
}

/** Why the external AI can't take the test image (null: it can). */
export function externalBlocked(llm: LlmStatus | undefined): string | null {
  if (!llm) return 'Der KI-Dienst ist nicht eingerichtet.';
  const provider = llm.providers.find((p) => p.id === llm.config.provider);
  if (provider && !provider.vision) return `${provider.title} kann keine Fotos ansehen.`;
  if (!llm.config.enabled) return 'Externe KI ist aus.';
  if (!llm.key.set) return 'Erst einen API-Schlüssel setzen.';
  if (!llm.key.valid) return 'Der API-Schlüssel ist ungültig.';
  if (llm.usage.blocked) return 'Budget erreicht – externe KI pausiert.';
  return null;
}

export const PROPERTY_NAME_RE = /^[a-z][a-z0-9_]{1,30}$/;
export const PROPERTY_PROMPT_MAX = 2000;

export function validateProperty(name: string, prompt: string): { name?: string; prompt?: string } {
  const out: { name?: string; prompt?: string } = {};
  if (!PROPERTY_NAME_RE.test(name)) {
    out.name = 'Kleinbuchstaben, Ziffern und _, 2 bis 31 Zeichen, vorne ein Buchstabe.';
  }
  const p = prompt.trim();
  if (p.length < 1 || p.length > PROPERTY_PROMPT_MAX) {
    out.prompt = `Der Prompt braucht 1 bis ${formatNumber(PROPERTY_PROMPT_MAX)} Zeichen.`;
  }
  return out;
}

/** How full a meter is, 0..1; null without a limit. */
export function fill(used: number, limit: number | null): number | null {
  if (limit === null) return null;
  if (limit <= 0) return 1;
  return Math.min(1, Math.max(0, used / limit));
}

/** "" = no limit (null); money with up to 2 places, calls whole; 'bad' on bad input. */
export function parseLimit(text: string, money: boolean): number | null | 'bad' {
  const t = text.trim();
  if (!t) return null;
  const n = parseDecimal(t);
  if (!Number.isFinite(n) || n < 0) return 'bad';
  if (!money && !Number.isInteger(n)) return 'bad';
  return money ? Math.round(n * 100) / 100 : n;
}
