import { describe, expect, it } from 'vitest';
import { categoryItems, spec, valuesOut } from '../fixtures';
import { must } from '../../testing';
import { CONDITION_OPS, LABEL_STYLES, type CategorySpec } from '../types';
import {
  emptyCondition,
  emptyDraft,
  freeId,
  fromSpec,
  graphemes,
  kindOf,
  localToUnix,
  moveId,
  OP_LABELS,
  operandShape,
  opsFor,
  parseDecimal,
  serverField,
  slugify,
  splitKey,
  STYLE_LABELS,
  toSpec,
  unixToLocal,
  validate,
  valueChoices,
  type CategoryDraft,
} from './spec';

const choices = valueChoices(valuesOut.values);
const then = (by: string) => ({ uid: 1, by, param: '', order: 'top' as const });
const ctx = { choices };

function valid(over: Partial<CategoryDraft> = {}): CategoryDraft {
  return {
    ...emptyDraft(),
    id: 'meine',
    title: 'Meine',
    by: 'people',
    one: 'Person',
    many: 'Personen',
    ...over,
  };
}

describe('operators', () => {
  it('has a German symbol for every op', () => {
    for (const op of CONDITION_OPS) expect(OP_LABELS[op]).toBeTruthy();
    expect(OP_LABELS.gte).toBe('≥');
    expect(OP_LABELS.ne).toBe('≠');
    expect(OP_LABELS.contains_any).toBe('enthält eins von');
    for (const style of LABEL_STYLES) expect(STYLE_LABELS[style]).toBeTruthy();
  });

  it('offers number ops for numbers, counts and times, label ops for lists', () => {
    for (const kind of ['number', 'count', 'time'] as const) {
      expect(opsFor(kind)).toEqual(['gte', 'gt', 'lte', 'lt', 'eq', 'ne', 'between', 'exists', 'not_exists']);
    }
    expect(opsFor('labels')).toEqual(['contains', 'not_contains', 'contains_any']);
    // every op is reachable from some kind
    const all = new Set([...opsFor('number'), ...opsFor('labels')]);
    expect([...all].toSorted()).toEqual([...CONDITION_OPS].toSorted());
  });

  it('knows the operand per op', () => {
    expect(operandShape('gt')).toBe('number');
    expect(operandShape('between')).toBe('range');
    expect(operandShape('exists')).toBe('none');
    expect(operandShape('not_exists')).toBe('none');
    expect(operandShape('contains')).toBe('label');
    expect(operandShape('not_contains')).toBe('label');
    expect(operandShape('contains_any')).toBe('labels');
  });
});

describe('value catalogue', () => {
  it('adds the parametrised values as templates', () => {
    const ids = choices.map((c) => c.id);
    expect(ids).toContain('objects.count:');
    expect(ids).toContain('prop.coolness.at:');
    expect(ids.filter((id) => id === 'prop.coolness.at:')).toHaveLength(1);
    expect(kindOf('objects.count:hat', choices)).toBe('count');
    expect(kindOf('prop.coolness.at:hat', choices)).toBe('number');
    expect(kindOf('objects', choices)).toBe('labels');
    expect(kindOf('nope', choices)).toBeNull();
    expect(splitKey('objects.count:wine glass')).toEqual({ base: 'objects.count:', param: 'wine glass' });
    expect(splitKey('people')).toEqual({ base: 'people', param: null });
  });
});

describe('numbers and times', () => {
  it('reads German and English decimals', () => {
    expect(parseDecimal('0,5')).toBe(0.5);
    expect(parseDecimal(' 3 ')).toBe(3);
    expect(parseDecimal('-1.25')).toBe(-1.25);
    expect(parseDecimal('')).toBeNaN();
    expect(parseDecimal('3a')).toBeNaN();
  });

  it('turns local date-times into unix seconds and back', () => {
    const unix = localToUnix('2026-10-15T19:42');
    expect(unixToLocal(unix)).toBe('2026-10-15T19:42');
    expect(localToUnix('19:42')).toBeNaN();
  });
});

describe('round trip', () => {
  it('keeps every preset spec unchanged', () => {
    for (const item of categoryItems()) {
      const legacy = must(item.legacy_spec);
      const draft = fromSpec(item.id, legacy);
      expect(validate(draft, ctx)).toEqual({});
      expect(toSpec(draft, choices)).toEqual(legacy);
    }
  });

  it('serialises every operand shape', () => {
    const s: CategorySpec = spec({
      where: [
        { value: 'people', op: 'between', operand: [2, 4] },
        { value: 'colorfulness', op: 'gt', operand: 40.5 },
        { value: 'smiles', op: 'exists', operand: null },
        { value: 'objects', op: 'not_contains', operand: 'hat' },
        { value: 'objects', op: 'contains_any', operand: ['hat', 'wine glass'] },
        { value: 'objects.count:hat', op: 'gte', operand: 2 },
        { value: 'prop.coolness.at:hat', op: 'lt', operand: 0.5 },
        { value: 'photo.created_at', op: 'gte', operand: localToUnix('2026-10-15T22:00') },
      ],
      select: {
        by: 'prop.coolness.max',
        order: 'bottom',
        count: 10,
        then_by: [
          { by: 'smiles', order: 'top' },
          { by: 'objects.count:hat', order: 'bottom' },
        ],
        one_per_guest: false,
      },
      label: { value: 'people', style: 'percent', one: 'Drama', many: '' },
      verdict: { prompt: 'Wer ist am coolsten?' },
    });
    const draft = fromSpec('x', s, (key) => key === 'photo.created_at');
    expect(draft.where[0]?.a).toBe('2');
    expect(draft.where[1]?.a).toBe('40,5');
    expect(draft.where[5]).toMatchObject({ value: 'objects.count:', param: 'hat' });
    expect(draft.where[7]?.a).toBe('2026-10-15T22:00');
    expect(validate(draft, ctx)).toEqual({});
    expect(toSpec(draft, choices)).toEqual(s);
  });

  it('trims texts and drops an empty verdict', () => {
    const out = toSpec(valid({ title: '  Hallo ', verdict: '   ', emoji: ' 🎉 ' }), choices);
    expect(out.title).toBe('Hallo');
    expect(out.emoji).toBe('🎉');
    expect(out.verdict).toBeNull();
    expect(out.label.value).toBeNull();
    expect(out.select.count).toBe(3);
  });
});

describe('validation', () => {
  it('accepts a minimal draft', () => {
    expect(validate(valid(), { ...ctx, isNew: true, taken: [] })).toEqual({});
  });

  it('checks id, emoji, title, line and count', () => {
    const errors = validate(
      valid({ id: 'Neu!', emoji: '🎉🎉', title: '', line: 'x'.repeat(81), count: '11' }),
      { ...ctx, isNew: true },
    );
    expect(Object.keys(errors).toSorted()).toEqual(['count', 'emoji', 'id', 'line', 'title']);
    expect(validate(valid({ id: 'meine' }), { ...ctx, isNew: true, taken: ['meine'] }).id).toBe(
      'Diese Kennung gibt es schon.',
    );
    // existing categories keep their id
    expect(validate(valid({ id: 'Neu!' }), ctx).id).toBeUndefined();
    expect(validate(valid({ count: '0' }), ctx).count).toBeTruthy();
    expect(validate(valid({ count: '10' }), ctx).count).toBeUndefined();
    expect(validate(valid({ title: 'x'.repeat(41) }), ctx).title).toBeTruthy();
  });

  it('counts an emoji with a skin tone or ZWJ as one', () => {
    expect(graphemes('👍🏽')).toBe(1);
    expect(graphemes('👩‍👩‍👧')).toBe(1);
    expect(validate(valid({ emoji: '👩‍👩‍👧' }), ctx).emoji).toBeUndefined();
    expect(validate(valid({ emoji: '' }), ctx).emoji).toBeTruthy();
  });

  it('checks every condition by its shape', () => {
    const where = [
      { ...emptyCondition('people', 'gte'), a: 'drei' },
      { ...emptyCondition('people', 'between'), a: '5', b: '2' },
      { ...emptyCondition('objects', 'contains') },
      { ...emptyCondition('objects', 'contains_any') },
      { ...emptyCondition('objects', 'gte'), a: '1' },
      { ...emptyCondition('objects.count:', 'gte'), a: '1' },
      { ...emptyCondition('', 'gte') },
      { ...emptyCondition('weg', 'gte'), a: '1' },
    ];
    const errors = validate(valid({ where }), ctx);
    expect(errors).toEqual({
      'where.0.a': 'Bitte eine Zahl.',
      'where.1.b': 'Muss mindestens so groß sein.',
      'where.2.a': 'Bitte ein Objekt wählen.',
      'where.3.labels': 'Bitte mindestens ein Objekt wählen.',
      'where.4.op': 'Dieser Vergleich passt nicht zum Wert.',
      'where.5.value.param': 'Bitte ein Objekt wählen.',
      'where.6.value': 'Bitte einen Wert wählen.',
      'where.7.value': 'Diesen Wert gibt es nicht (mehr).',
    });
    const nine = Array.from({ length: 9 }, () => ({ ...emptyCondition('smiles', 'exists') }));
    expect(validate(valid({ where: nine }), ctx).where).toBe('Höchstens 8 Bedingungen.');
  });

  it('sorts only by numbers, at most two tie-breakers', () => {
    expect(validate(valid({ by: 'objects' }), ctx).by).toBe('Nach einer Liste lässt sich nicht sortieren.');
    expect(validate(valid({ by: '' }), ctx).by).toBe('Bitte einen Wert wählen.');
    expect(
      validate(valid({ thenBy: [then('smiles'), then('people'), then('sharpness')] }), ctx).then_by,
    ).toBe('Höchstens 2.');
    expect(validate(valid({ thenBy: [then('objects')] }), ctx)['then_by.0']).toBeTruthy();
  });

  it('asks for the label words the style needs', () => {
    expect(validate(valid({ one: '', many: '' }), ctx)).toMatchObject({
      one: expect.any(String),
      many: expect.any(String),
    });
    expect(validate(valid({ style: 'fixed', one: '', many: '' }), ctx)).toEqual({ one: 'Bitte den Text.' });
    expect(validate(valid({ style: 'object', one: '', many: '' }), ctx)).toEqual({});
    expect(validate(valid({ verdict: 'x'.repeat(1001) }), ctx).verdict).toBeTruthy();
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

  it('finds the field a server error is about', () => {
    expect(serverField('Titel: höchstens 40 Zeichen.')).toBe('title');
    expect(serverField('Untertitel: zu lang.')).toBe('line');
    expect(serverField('Bedingung 2: unbekannter Wert.')).toBe('where');
    expect(serverField('Anzahl: 1 bis 10.')).toBe('count');
    expect(serverField('Etwas anderes.')).toBeNull();
    expect(serverField('egal', { error: 'invalid_category', field: 'emoji' })).toBe('emoji');
  });

  it('moves ids up and down', () => {
    expect(moveId(['a', 'b', 'c'], 'b', -1)).toEqual(['b', 'a', 'c']);
    expect(moveId(['a', 'b', 'c'], 'b', 1)).toEqual(['a', 'c', 'b']);
    expect(moveId(['a', 'b', 'c'], 'a', -1)).toEqual(['a', 'b', 'c']);
    expect(moveId(['a', 'b', 'c'], 'x', 1)).toEqual(['a', 'b', 'c']);
  });
});
