import { describe, expect, it } from 'vitest';
import { ApiError } from '@/api/client';
import { analysisStatus } from '../wall/fixtures';
import { llmStatus } from './fixtures';
import {
  aiUnavailable,
  externalBlocked,
  fill,
  keyStatusText,
  parseLimit,
  parseMinutes,
  testErrorText,
  validateProperty,
} from './forms';
import {
  ageText,
  modelText,
  queueText,
  sizeText,
  sourceText,
  statsText,
  usageKindText,
  usdText,
} from './text';

describe('ML-Pipeline lines', () => {
  it('formats sizes, stats and the queue', () => {
    expect(sizeText(12)).toBe('12 MB');
    expect(sizeText(3.44)).toBe('3,4 MB');
    expect(statsText({ processed: 128, errors: 2, avg_ms: 340, last_ms: 290 })).toBe(
      'Ø 340 ms · zuletzt 290 ms · 128 Fotos · 2 Fehler',
    );
    expect(statsText({ processed: 1, errors: 0, avg_ms: null, last_ms: null })).toBe('1 Foto · 0 Fehler');
    expect(queueText(analysisStatus.queue)).toBe('Warteschlange: 3 Fotos (ältestes seit 12 s)');
    expect(queueText({ pending: 1, running: 0, oldest_pending_s: 200 })).toBe(
      'Warteschlange: 1 Foto (seit 3 min)',
    );
    expect(queueText({ pending: 0, running: 0, oldest_pending_s: null })).toBe('Warteschlange: leer');
    expect(ageText(7200)).toBe('2 h');
  });

  it('formats money, models and usage kinds', () => {
    expect(usdText(1.25)).toBe('1,25 $');
    expect(usdText(0.0022)).toBe('0,0022 $');
    expect(
      modelText({
        id: 'm',
        provider: 'anthropic',
        title: 'Haiku',
        usd_in_mtok: 1,
        usd_out_mtok: 5,
        currency: 'USD',
        price_in_mtok: 1,
        price_out_mtok: 5,
      }),
    ).toBe('Haiku · 1 $ / 5 $ pro Mio. Tokens');
    // DeutschlandGPT: its own currency, not the converted dollars
    const dgpt = llmStatus().models.find((m) => m.provider === 'deutschlandgpt');
    expect(dgpt && modelText(dgpt).replaceAll('\u00a0', ' ')).toBe(
      'Claude Haiku 5.5 · 0,83 € / 4,13 € pro Mio. Tokens',
    );
    expect(sourceText('deutschlandgpt')).toBe('DeutschlandGPT');
    expect(usageKindText({ kind: 'detect', ref: null })).toBe('Erkennung');
    expect(usageKindText({ kind: 'property', ref: 'coolness' })).toBe('Eigenschaft „coolness“');
    expect(usageKindText({ kind: 'verdict', ref: 'coolstes_objekt' })).toBe('Urteil „coolstes_objekt“');
    expect(usageKindText({ kind: 'test', ref: null })).toBe('Test');
  });
});

describe('ML-Pipeline forms', () => {
  it('reads the poll interval in whole minutes 1–60', () => {
    expect(parseMinutes('3')).toBe(3);
    expect(parseMinutes(' 60 ')).toBe(60);
    expect(parseMinutes('0')).toBeNull();
    expect(parseMinutes('61')).toBeNull();
    expect(parseMinutes('2,5')).toBeNull();
  });

  it('reads limits: empty = none, money to the cent, calls whole', () => {
    expect(parseLimit('', true)).toBeNull();
    expect(parseLimit('2,505', true)).toBe(2.51);
    expect(parseLimit('100', false)).toBe(100);
    expect(parseLimit('1,5', false)).toBe('bad');
    expect(parseLimit('-1', true)).toBe('bad');
    expect(fill(1, 4)).toBe(0.25);
    expect(fill(9, 4)).toBe(1);
    expect(fill(1, null)).toBeNull();
    expect(fill(0, 0)).toBe(1);
  });

  it('validates a new property', () => {
    expect(validateProperty('coolness', 'Wie cool?')).toEqual({});
    expect(Object.keys(validateProperty('Cool ness', ''))).toEqual(['name', 'prompt']);
    expect(validateProperty('c', 'x').name).toBeTruthy();
    expect(validateProperty('most_giraffe', 'x'.repeat(2001)).prompt).toBeTruthy();
  });

  it('says what the key is, never more', () => {
    expect(keyStatusText({ set: false, set_at: null, provider: null, valid: false })).toBe('nicht gesetzt');
    expect(keyStatusText({ set: true, set_at: null, provider: 'anthropic', valid: true })).toBe('gesetzt');
    expect(keyStatusText({ set: true, set_at: null, provider: 'anthropic', valid: false })).toBe(
      'Schlüssel ungültig, bitte neu eingeben',
    );
  });

  it('knows when the external AI is off or has no key (the red hint)', () => {
    const key = { set: true, set_at: null, provider: 'anthropic', valid: true };
    expect(aiUnavailable(undefined)).toBeNull();
    expect(aiUnavailable(llmStatus())).toBe('key');
    expect(aiUnavailable(llmStatus({ key: { ...key, valid: false } }))).toBe('key');
    expect(aiUnavailable(llmStatus({ key }))).toBeNull();
    const off = llmStatus({ key });
    off.config = { ...off.config, enabled: false };
    expect(aiUnavailable(off)).toBe('off');
    expect(externalBlocked(off)).toBe('Externe KI ist aus.');
    const dgpt = llmStatus({ key });
    dgpt.config = { ...dgpt.config, provider: 'deutschlandgpt', model: 'claude-haiku-5.5' };
    expect(externalBlocked(dgpt)).toBe('DeutschlandGPT (Claude, Deutschland) kann keine Fotos ansehen.');
  });

  it('knows when the test image may go to Claude', () => {
    expect(externalBlocked(undefined)).toBeTruthy();
    expect(externalBlocked(llmStatus())).toBe('Erst einen API-Schlüssel setzen.');
    const ready = llmStatus({ key: { set: true, set_at: null, provider: 'anthropic', valid: true } });
    expect(externalBlocked(ready)).toBeNull();
    expect(externalBlocked({ ...ready, usage: { ...ready.usage, blocked: true } })).toBe(
      'Budget erreicht – externe KI pausiert.',
    );
    expect(testErrorText(new ApiError(409, 'worker_off', 'x'))).toBe('Die Analyse läuft gerade nicht.');
    expect(testErrorText(new ApiError(409, 'llm_budget_exhausted', 'Budget erreicht.'))).toBe(
      'Budget erreicht.',
    );
  });
});
