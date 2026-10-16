import { describe, expect, it } from 'vitest';
import { verdictOptions } from '../../ml/fixtures';
import { categoryItems, measure, spec, valuesOut } from '../fixtures';
import { CAPTION_FORMATS, POOL_OPS, type CategorySpec, type Measure } from '../types';
import {
  captionParts,
  conditionText,
  describe as describeMeasure,
  draftProperties,
  emptyCondition,
  emptyDraft,
  emptyMeasure,
  explainRank,
  FORMAT_LABELS,
  freeId,
  fromSpec,
  graphemes,
  hasFocus,
  localToUnix,
  measureDraft,
  measureSpec,
  moveId,
  OP_LABELS,
  parseDecimal,
  priceText,
  ruleText,
  serverField,
  slugify,
  suggestCaption,
  thresholdWord,
  toSpec,
  unixToLocal,
  validate,
  valueText,
  verdictPrice,
  type CategoryDraft,
  type MeasureDraft,
} from './spec';

const ctx = { values: valuesOut };

function valid(over: Partial<CategoryDraft> = {}): CategoryDraft {
  return {
    ...emptyDraft(),
    id: 'meine',
    title: 'Meine',
    by: emptyMeasure('value', 'people'),
    one: 'Person',
    many: 'Personen',
    ...over,
  };
}

const objects = (over: Partial<MeasureDraft> = {}): MeasureDraft => ({ ...emptyMeasure('objects'), ...over });

/** a spec through the editor and back */
const roundTrip = (s: CategorySpec) => toSpec(fromSpec('x', s, valuesOut), valuesOut);

describe('labels', () => {
  it('names every comparison and format', () => {
    for (const op of POOL_OPS) expect(OP_LABELS[op]).toBeTruthy();
    for (const f of CAPTION_FORMATS) expect(FORMAT_LABELS[f]).toBeTruthy();
  });

  it('says „mindestens“ for the highest and „höchstens“ for the lowest', () => {
    expect(thresholdWord('desc')).toBe('mindestens');
    expect(thresholdWord('asc')).toBe('höchstens');
  });
});

describe('draft ⇄ spec', () => {
  it('round-trips every fixture category unchanged', () => {
    for (const item of categoryItems()) expect(roundTrip(item.spec)).toEqual(item.spec);
  });

  it('round-trips measures with filters, k and t', () => {
    const top: Measure = {
      kind: 'objects',
      where: { labels: ['hat'], exclude: ['person'], min_confidence: 0.4 },
      field: 'prop:coolness',
      agg: 'top_k_mean',
      k: 3,
      t: null,
    };
    const ge: Measure = { ...top, agg: 'count_ge', k: null, t: 0.75 };
    const conf: Measure = { ...top, field: 'confidence', agg: 'min', k: null };
    for (const m of [top, ge, conf, measure.objects('count'), measure.value('smiles')]) {
      expect(measureSpec(measureDraft(m))).toEqual(m);
    }
    expect(measureDraft(top).minConfidence).toBe('0,4');
    expect(measureDraft(ge).t).toBe('0,75');
  });

  it('round-trips a full spec: pool rows, threshold, tie-breakers, caption measure, verdict', () => {
    const s = spec({
      pool: [
        { measure: measure.value('smiles'), op: 'between', operand: [1, 4] },
        { measure: measure.objects('count', null, ['hat']), op: 'gte', operand: 1 },
        { measure: measure.objects('count', null, ['wine glass']), op: 'eq', operand: 0 },
        { measure: measure.objects('max', 'prop:coolness'), op: 'gte', operand: 0.5 },
        { measure: measure.value('happy_max'), op: 'exists', operand: null },
      ],
      rank: {
        by: measure.objects('max', 'prop:coolness'),
        order: 'asc',
        threshold: 0.2,
        then_by: [{ by: measure.value('people'), order: 'desc' }],
      },
      select: { count: 5, one_per_guest: false },
      caption: { value: measure.value('people'), format: 'count', one: 'Person', many: 'Personen', show_object: false },
      verdict: { prompt: 'Sei frech.', count: 2, model: 'claude-sonnet-5-5', effort: 'medium' },
    });
    expect(roundTrip(s)).toEqual(s);
    const d = fromSpec('x', s, valuesOut);
    expect(d.pool.map((c) => c.type)).toEqual(['value', 'has', 'has_not', 'objects', 'value']);
    expect(d.threshold).toBe('0,2');
    expect(d.captionSame).toBe(false);
  });

  it('writes „enthält (kein) Objekt“ as a count with ≥ 1 / = 0', () => {
    const has = { ...emptyCondition('has'), measure: objects({ labels: ['hat'] }) };
    const hasNot = { ...emptyCondition('has_not'), measure: objects({ labels: ['hat', 'wine glass'] }) };
    const out = toSpec(valid({ pool: [has, hasNot] }), valuesOut);
    expect(out.pool).toEqual([
      { measure: measure.objects('count', null, ['hat']), op: 'gte', operand: 1 },
      { measure: measure.objects('count', null, ['hat', 'wine glass']), op: 'eq', operand: 0 },
    ]);
  });

  it('takes times as local date and time', () => {
    const at = localToUnix('2026-10-16T19:42');
    const s = spec({ rank: { by: measure.value('photo.created_at'), order: 'asc', threshold: at, then_by: [] } });
    const d = fromSpec('x', s, valuesOut);
    expect(d.threshold).toBe('2026-10-16T19:42');
    expect(unixToLocal(at)).toBe('2026-10-16T19:42');
    expect(roundTrip(s).rank.threshold).toBe(at);
  });

  it('trims texts, drops the caption object without a focus, and the verdict when off', () => {
    const out = toSpec(valid({ title: '  Hallo ', emoji: ' 🎉 ', showObject: true, verdictOn: false }), valuesOut);
    expect(out.title).toBe('Hallo');
    expect(out.emoji).toBe('🎉');
    expect(out.caption.show_object).toBe(false); // a photo value has no object
    expect(out.verdict).toBeNull();
    expect(out.rank.threshold).toBeNull();
    const on = toSpec(valid({ verdictOn: true, verdictPrompt: '  ', verdictCount: '4' }), valuesOut);
    expect(on.verdict).toEqual({ prompt: null, count: 4, model: null, effort: 'low' });
  });

  it('knows the properties a draft reads and whether a measure has an object', () => {
    const d = valid({ by: objects({ field: 'prop:coolness', agg: 'max' }), pool: [{ ...emptyCondition('objects', 'prop:glitzer') }] });
    expect(draftProperties(d)).toEqual(['glitzer', 'coolness']);
    expect(hasFocus(measure.objects('count'))).toBe(false);
    expect(hasFocus(measure.objects('count', null, ['hat']))).toBe(true);
    expect(hasFocus(measure.objects('mean', 'confidence'))).toBe(true);
    expect(hasFocus(measure.value('people'))).toBe(false);
  });
});

describe('validation', () => {
  it('accepts a minimal draft', () => {
    expect(validate(valid(), { ...ctx, isNew: true, taken: [] })).toEqual({});
  });

  it('checks id, emoji, title, line and count', () => {
    const errors = validate(valid({ id: 'Neu!', emoji: '🎉🎉', title: '', line: 'x'.repeat(81), count: '11' }), {
      ...ctx,
      isNew: true,
    });
    expect(Object.keys(errors).toSorted()).toEqual(['count', 'emoji', 'id', 'line', 'title']);
    expect(validate(valid({ id: 'meine' }), { ...ctx, isNew: true, taken: ['meine'] }).id).toBe('Diese Kennung gibt es schon.');
    expect(validate(valid({ id: 'Neu!' }), ctx).id).toBeUndefined();
    expect(validate(valid({ count: '0' }), ctx).count).toBeTruthy();
    expect(validate(valid({ count: '10' }), ctx).count).toBeUndefined();
  });

  it('counts an emoji with a skin tone or ZWJ as one', () => {
    expect(graphemes('👍🏽')).toBe(1);
    expect(graphemes('👩‍👩‍👧')).toBe(1);
    expect(validate(valid({ emoji: '👩‍👩‍👧' }), ctx).emoji).toBeUndefined();
    expect(validate(valid({ emoji: '' }), ctx).emoji).toBeTruthy();
  });

  it('checks every pool row by its kind', () => {
    const pool = [
      { ...emptyCondition('value'), measure: emptyMeasure('value', 'people'), a: 'drei' },
      { ...emptyCondition('value'), measure: emptyMeasure('value', 'people'), op: 'between' as const, a: '5', b: '2' },
      { ...emptyCondition('has') },
      { ...emptyCondition('value') },
      { ...emptyCondition('value'), measure: emptyMeasure('value', 'weg'), a: '1' },
      { ...emptyCondition('objects'), measure: objects({ minConfidence: '2' }), a: '1' },
      { ...emptyCondition('value'), measure: emptyMeasure('value', 'smiles'), op: 'exists' as const },
    ];
    expect(validate(valid({ pool }), ctx)).toEqual({
      'pool.0.a': 'Bitte eine Zahl.',
      'pool.1.b': 'Muss mindestens so groß sein.',
      'pool.2': 'Bitte ein Objekt wählen.',
      'pool.3': 'Bitte einen Wert wählen.',
      'pool.4': 'Diesen Wert gibt es nicht (mehr).',
      'pool.5.min': 'Eine Zahl von 0 bis 1.',
    });
    const nine = Array.from({ length: 9 }, () => ({ ...emptyCondition('value'), measure: emptyMeasure('value', 'smiles'), op: 'exists' as const }));
    expect(validate(valid({ pool: nine }), ctx).pool).toBe('Höchstens 8 Bedingungen.');
  });

  it('checks the ranking: measure, k, t, threshold, at most two tie-breakers', () => {
    expect(validate(valid({ by: emptyMeasure('value') }), ctx)['rank.by']).toBe('Bitte einen Wert wählen.');
    expect(validate(valid({ by: objects({ field: 'prop:coolness', agg: 'top_k_mean', k: '7' }) }), ctx)['rank.by.k']).toBe(
      'k: 2 bis 5.',
    );
    expect(validate(valid({ by: objects({ field: 'prop:coolness', agg: 'count_ge', t: '1,5' }) }), ctx)['rank.by.t']).toBeTruthy();
    expect(validate(valid({ threshold: 'viele' }), ctx)['rank.threshold']).toBe('Bitte eine Zahl.');
    expect(validate(valid({ threshold: '3' }), ctx)['rank.threshold']).toBeUndefined();
    const then = () => ({ uid: 1, by: emptyMeasure('value', 'smiles'), order: 'desc' as const });
    expect(validate(valid({ thenBy: [then(), then(), then()] }), ctx)['rank.then_by']).toBe('Höchstens 2.');
    expect(validate(valid({ thenBy: [{ ...then(), by: emptyMeasure('value') }] }), ctx)['rank.then_by.0']).toBeTruthy();
    // a property that is not there (any more) is the lock's business, not the form's
    expect(validate(valid({ by: objects({ field: 'prop:weg', agg: 'max' }) }), ctx)).toEqual({});
  });

  it('asks for the caption words the format needs, and checks the comments', () => {
    expect(validate(valid({ one: '', many: '' }), ctx)).toMatchObject({ one: expect.any(String), many: expect.any(String) });
    expect(validate(valid({ format: 'text', one: '', many: '' }), ctx)).toEqual({ one: 'Bitte den Text.' });
    expect(validate(valid({ format: 'decimal', one: '', many: '' }), ctx)).toEqual({});
    expect(validate(valid({ verdictOn: true, verdictPrompt: 'x'.repeat(1001) }), ctx).verdict).toBeTruthy();
    expect(validate(valid({ verdictOn: true, verdictCount: '6' }), ctx)['verdict.count']).toBeTruthy();
    expect(validate(valid({ verdictOn: false, verdictCount: '6' }), ctx)['verdict.count']).toBeUndefined();
  });
});

describe('plain German', () => {
  it('describes measures as the server does', () => {
    const d = (m: Measure, order: 'desc' | 'asc' = 'desc') => describeMeasure(m, order, valuesOut);
    expect(d(measure.value('people'))).toBe('Höchster Wert bei „Personen“');
    expect(d(measure.value('photo.created_at'), 'asc')).toBe('Das früheste Foto');
    expect(d(measure.objects('max', 'prop:coolness'))).toBe('Höchster coolness-Wert unter allen Objekten');
    expect(d(measure.objects('min', 'prop:coolness'), 'desc')).toBe('Niedrigster coolness-Wert unter allen Objekten');
    expect(d({ ...measure.objects('count'), where: { labels: [], exclude: ['person'], min_confidence: 0.5 } })).toBe(
      'Die meisten Objekte (ohne Person; Sicherheit ab 50 %)',
    );
    expect(d(measure.objects('count', null, ['hat']), 'asc')).toBe('Die wenigsten Objekte (nur Hut)');
    expect(d({ ...measure.objects('top_k_mean', 'prop:coolness'), k: 2 })).toBe('Höchster Schnitt der besten 2 coolness-Werte');
    expect(d({ ...measure.objects('count_ge', 'confidence'), t: 0.8 })).toBe('Die meisten Objekte mit Erkennungssicherheit ab 0,80');
  });

  it('explains the ranking with its threshold', () => {
    expect(explainRank(spec().rank, valuesOut)).toBe('Höchster Wert bei „Personen“, mindestens 3');
    const blur = { by: measure.value('sharpness'), order: 'asc' as const, threshold: 80, then_by: [] };
    expect(explainRank(blur, valuesOut)).toBe('Niedrigster Wert bei „Schärfe“, höchstens 80');
  });

  it('says the whole rule: pool, rank, tie-breakers, how many', () => {
    const s = spec({
      pool: [
        { measure: measure.objects('count', null, ['hat']), op: 'gte', operand: 1 },
        { measure: measure.value('smiles'), op: 'between', operand: [1, 4] },
      ],
      rank: { by: measure.value('people'), order: 'desc', threshold: 3, then_by: [{ by: measure.value('smiles'), order: 'desc' }] },
      select: { count: 1, one_per_guest: true },
    });
    expect(ruleText(s, valuesOut)).toEqual({
      pool: 'enthält Hut und Lächeln zwischen 1 und 4',
      rank: 'Höchster Wert bei „Personen“, mindestens 3',
      then: ['Höchster Wert bei „Lächeln“'],
      select: 'Ein Gewinner, ein Foto pro Gast',
    });
    expect(ruleText(spec({ select: { count: 3, one_per_guest: false } }), valuesOut).pool).toBe('Alle Fotos');
    expect(conditionText({ measure: measure.objects('count', null, ['wine glass']), op: 'eq', operand: 0 }, valuesOut)).toBe(
      'enthält kein Weinglas',
    );
    expect(conditionText({ measure: measure.objects('max', 'prop:coolness'), op: 'gte', operand: 0.5 }, valuesOut)).toBe(
      'coolness: höchster Wert ≥ 0,5',
    );
  });
});

describe('caption', () => {
  it('suggests the format from the measure', () => {
    expect(suggestCaption(measure.value('people'), valuesOut)).toEqual({ format: 'count', showObject: false });
    expect(suggestCaption(measure.value('happy_max'), valuesOut)).toEqual({ format: 'decimal', showObject: false });
    expect(suggestCaption(measure.value('colorfulness'), valuesOut)).toEqual({ format: 'number', showObject: false });
    expect(suggestCaption(measure.value('photo.created_at'), valuesOut)).toEqual({ format: 'time', showObject: false });
    expect(suggestCaption(measure.objects('count'), valuesOut)).toEqual({ format: 'count', showObject: false });
    expect(suggestCaption(measure.objects('max', 'prop:coolness'), valuesOut)).toEqual({ format: 'decimal', showObject: true });
    expect(suggestCaption(measure.objects('mean', 'prop:coolness'), valuesOut)).toEqual({ format: 'decimal', showObject: false });
  });

  it('writes the value as the wall does', () => {
    expect(valueText('count', 7, 'Person', 'Personen')).toBe('7 Personen');
    expect(valueText('count', 1, 'Person', 'Personen')).toBe('1 Person');
    expect(valueText('percent', 0.82, 'Drama', '')).toBe('82 % Drama');
    expect(valueText('decimal', 0.931, 'Coolness', '')).toBe('0,93 Coolness');
    expect(valueText('number', 73.2, 'Farbwert', '')).toBe('Farbwert 73');
    expect(valueText('text', 5, 'volle Bewegung', '')).toBe('volle Bewegung');
    expect(valueText('none', 5, 'x', '')).toBe('');
    expect(valueText('time', localToUnix('2026-10-16T19:42'), '', '')).toBe('um 19:42');
    const cap = { format: 'decimal' as const, one: 'Coolness', many: '', show_object: true };
    expect(captionParts(cap, 0.93, 'Sonnenbrille')).toEqual({ headline: 'Sonnenbrille', detail: '0,93 Coolness' });
    expect(captionParts({ ...cap, show_object: false }, 0.93, 'Sonnenbrille')).toEqual({ headline: '0,93 Coolness', detail: null });
  });
});

describe('AI comments', () => {
  it('prices a comment for the chosen model and effort, estimates marked', () => {
    const opts = verdictOptions();
    expect(verdictPrice(opts, '', 'low')).toMatchObject({ model: 'claude-haiku-5-5', price: 0.0014, measured: true });
    expect(verdictPrice(opts, 'claude-sonnet-5-5', 'high')).toMatchObject({ price: 0.033, measured: false });
    // a provider without thinking: the low row
    expect(verdictPrice({ ...opts, thinking: false }, 'claude-sonnet-5-5', 'high')).toMatchObject({ price: 0.0042 });
    expect(verdictPrice(undefined, '', 'low')).toBeNull();
    expect(priceText(0.0014, 'USD')).toMatch(/^≈ 0,0014\s\$$/);
  });
});

describe('helpers', () => {
  it('makes ids from titles', () => {
    expect(slugify('Prost! Gläser')).toBe('prost_glaeser');
    expect(slugify('Größte Hüte')).toBe('groesste_huete');
    expect(slugify('42 Gründe')).toBe('k_42_gruende');
    expect(slugify('!')).toBe('kategorie');
    expect(freeId('Prost', ['prost', 'prost_2'])).toBe('prost_3');
  });

  it('parses German decimals', () => {
    expect(parseDecimal('0,5')).toBe(0.5);
    expect(parseDecimal(' 3 ')).toBe(3);
    expect(parseDecimal('drei')).toBeNaN();
  });

  it('finds the field a server error is about', () => {
    expect(serverField('egal', { error: 'invalid_category', field: 'rank.threshold' })).toBe('rank.threshold');
    expect(serverField('Titel: höchstens 40 Zeichen.')).toBe('title');
    expect(serverField('Bedingung 2: Messgröße.')).toBe('pool');
    expect(serverField('Rang: Schwelle.')).toBe('rank.threshold');
    expect(serverField('Rang: Messgröße.')).toBe('rank.by');
    expect(serverField('Etwas anderes.')).toBeNull();
  });

  it('moves ids up and down', () => {
    expect(moveId(['a', 'b', 'c'], 'b', -1)).toEqual(['b', 'a', 'c']);
    expect(moveId(['a', 'b', 'c'], 'b', 1)).toEqual(['a', 'c', 'b']);
    expect(moveId(['a', 'b', 'c'], 'a', -1)).toEqual(['a', 'b', 'c']);
    expect(moveId(['a', 'b', 'c'], 'x', 1)).toEqual(['a', 'b', 'c']);
  });
});
