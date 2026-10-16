/**
 * The category editor's pure part (spec.test.ts), categories v2: the form draft of a
 * CategorySpec (one building block, the measure: a photo value or objects(filter).agg(field),
 * used in the pool, the ranking and the caption), client-side validation that mirrors the
 * server's (engine.validate), the round trip draft ⇄ spec, the plain-German sentences
 * („Höchster coolness-Wert unter allen Objekten“, as engine.describe/explain) and the caption
 * text as the wall shows it (engine.value_text). Inputs stay text while typing; toSpec
 * parses them.
 */
import type { Effort, VerdictOptions } from '../../ml/types';
import type {
  Aggregate,
  CaptionFormat,
  CategorySpec,
  LabelInfo,
  Measure,
  MeasureObjects,
  PoolCondition,
  PoolOp,
  RankOrder,
  ValuesOut,
} from '../types';

// ------------------------------------------------------------------ labels

export const OP_LABELS: Record<PoolOp, string> = {
  gte: '≥',
  gt: '>',
  lte: '≤',
  lt: '<',
  eq: '=',
  ne: '≠',
  between: 'zwischen',
  exists: 'hat einen Wert',
  not_exists: 'hat keinen Wert',
};

/** The comparisons of a pool row, in menu order. */
export const POOL_OP_ORDER: readonly PoolOp[] = [
  'gte',
  'gt',
  'lte',
  'lt',
  'eq',
  'ne',
  'between',
  'exists',
  'not_exists',
];

export const FORMAT_LABELS: Record<CaptionFormat, string> = {
  count: 'Anzahl („7 Personen“)',
  percent: 'Prozent („82 % Drama“)',
  decimal: 'Dezimalzahl („0,93 Coolness“)',
  number: 'Zahl („Farbwert 73“)',
  time: 'Uhrzeit („um 19:42“)',
  text: 'Fester Text',
  none: 'Kein Wert',
};

/** The building blocks („Was zählt?“ › D) as the editor names them. */
export const AGG_LABELS: Record<Aggregate, string> = {
  max: 'höchster Wert (zeigt das Objekt)',
  min: 'niedrigster Wert (zeigt das Objekt)',
  mean: 'Durchschnitt',
  sum: 'Summe',
  top_k_mean: 'Mittel der besten k',
  count_ge: 'Anzahl mit Wert ≥ t',
  count: 'Anzahl bewerteter Objekte',
};
export const FIELD_AGGS: readonly Aggregate[] = [
  'max',
  'min',
  'mean',
  'sum',
  'top_k_mean',
  'count_ge',
  'count',
];

export const ORDER_WORDS: Record<RankOrder, string> = { desc: 'höchsten', asc: 'niedrigsten' };

/** „zählt erst ab mindestens 3“ / „höchstens 80“: the word follows the direction. */
export function thresholdWord(order: RankOrder): string {
  return order === 'desc' ? 'mindestens' : 'höchstens';
}

export const EFFORT_LABELS: Record<Effort, string> = { low: 'niedrig', medium: 'mittel', high: 'hoch' };

// ------------------------------------------------------------------- the draft

export interface MeasureDraft {
  kind: 'value' | 'objects';
  /** value: the photo value */
  key: string;
  /** objects: only these labels (any of them); empty = all */
  labels: string[];
  exclude: string[];
  /** 0–1 as text, '' = none */
  minConfidence: string;
  /** '' = the objects are counted; `confidence` or `prop:<name>` */
  field: string;
  agg: Aggregate;
  k: string;
  t: string;
}

/** A pool row: what the „+ Bedingung“ menu offers. */
export type ConditionType = 'value' | 'has' | 'has_not' | 'objects';

export interface ConditionDraft {
  /** local React key, not sent */
  uid: number;
  type: ConditionType;
  measure: MeasureDraft;
  op: PoolOp;
  a: string;
  b: string;
}

export interface ThenDraft {
  uid: number;
  by: MeasureDraft;
  order: RankOrder;
}

export interface CategoryDraft {
  id: string;
  emoji: string;
  title: string;
  line: string;
  pool: ConditionDraft[];
  by: MeasureDraft;
  order: RankOrder;
  /** '' = no threshold */
  threshold: string;
  thenBy: ThenDraft[];
  count: string;
  onePerGuest: boolean;
  /** the caption shows the ranking's value */
  captionSame: boolean;
  captionValue: MeasureDraft;
  format: CaptionFormat;
  one: string;
  many: string;
  showObject: boolean;
  verdictOn: boolean;
  /** '' = the default prompt */
  verdictPrompt: string;
  verdictCount: string;
  /** '' = the provider's cheapest */
  verdictModel: string;
  verdictEffort: Effort;
}

export const LIMITS = {
  title: 40,
  line: 80,
  pool: 8,
  count: [1, 10],
  thenBy: 2,
  words: 40,
  verdict: 1000,
  comments: [1, 5],
  k: [2, 5],
  labels: 20,
} as const;

let uidSeq = 0;
export const nextUid = () => ++uidSeq;

export function emptyMeasure(kind: MeasureDraft['kind'] = 'value', key = ''): MeasureDraft {
  return { kind, key, labels: [], exclude: [], minConfidence: '', field: '', agg: 'count', k: '2', t: '0,5' };
}

/** A new pool row of the menu's kind. */
export function emptyCondition(type: ConditionType = 'value', field = ''): ConditionDraft {
  const measure = emptyMeasure(type === 'value' ? 'value' : 'objects');
  if (field) {
    measure.field = field;
    measure.agg = 'max';
  }
  return { uid: nextUid(), type, measure, op: 'gte', a: '', b: '' };
}

export function emptyDraft(): CategoryDraft {
  return {
    id: '',
    emoji: '⭐',
    title: '',
    line: '',
    pool: [],
    by: emptyMeasure('value', ''),
    order: 'desc',
    threshold: '',
    thenBy: [],
    count: '3',
    onePerGuest: true,
    captionSame: true,
    captionValue: emptyMeasure(),
    format: 'count',
    one: '',
    many: '',
    showObject: false,
    verdictOn: false,
    verdictPrompt: '',
    verdictCount: '3',
    verdictModel: '',
    verdictEffort: 'low',
  };
}

// ------------------------------------------------------------- numbers, times

/** A number as the editor shows it: German decimal comma. */
export function numberText(n: number): string {
  return String(n).replace('.', ',');
}

/** "0,5" / "0.5" / " 3 " → number; anything else NaN. */
export function parseDecimal(text: string): number {
  const t = text.trim().replace(',', '.');
  return /^-?\d+(\.\d+)?$/.test(t) || /^-?\.\d+$/.test(t) ? Number(t) : Number.NaN;
}

const pad2 = (n: number) => String(n).padStart(2, '0');

/** unix seconds ⇄ the value of an <input type="datetime-local"> (local time). */
export function unixToLocal(seconds: number): string {
  const d = new Date(seconds * 1000);
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}T${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

export function localToUnix(text: string): number {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(text)) return Number.NaN;
  const ms = new Date(text).getTime();
  return Number.isNaN(ms) ? Number.NaN : Math.round(ms / 1000);
}

/** The catalogue's kind of a measure (time values take a date, the rest a number). */
export function measureKind(
  m: MeasureDraft | Measure,
  values: Pick<ValuesOut, 'photo_values'>,
): 'number' | 'count' | 'time' {
  if (m.kind === 'value') return values.photo_values.find((v) => v.key === m.key)?.kind ?? 'number';
  const agg = m.field ? m.agg : 'count';
  return agg === 'count' || agg === 'count_ge' ? 'count' : 'number';
}

function readNumber(text: string, time: boolean): number {
  return time ? localToUnix(text) : parseDecimal(text);
}

function operandText(n: number, time: boolean): string {
  return time ? unixToLocal(n) : numberText(n);
}

// ------------------------------------------------------------ draft ⇄ spec

export function measureDraft(m: Measure): MeasureDraft {
  if (m.kind === 'value') return emptyMeasure('value', m.key);
  return {
    kind: 'objects',
    key: '',
    labels: [...m.where.labels],
    exclude: [...m.where.exclude],
    minConfidence: m.where.min_confidence === null ? '' : numberText(m.where.min_confidence),
    field: m.field ?? '',
    agg: m.field ? m.agg : 'count',
    k: m.k === null ? '2' : String(m.k),
    t: m.t === null ? '0,5' : numberText(m.t),
  };
}

/** The draft's measure as the server takes it. Validate first. */
export function measureSpec(d: MeasureDraft): Measure {
  if (d.kind === 'value') return { kind: 'value', key: d.key };
  const agg: Aggregate = d.field ? d.agg : 'count';
  const conf = d.minConfidence.trim();
  return {
    kind: 'objects',
    where: {
      labels: [...d.labels],
      exclude: [...d.exclude],
      min_confidence: conf ? parseDecimal(conf) : null,
    },
    field: d.field || null,
    agg,
    k: agg === 'top_k_mean' ? Number(d.k.trim()) : null,
    t: agg === 'count_ge' ? parseDecimal(d.t) : null,
  };
}

/** „Enthält Objekt X“ is `objects({labels: [X]}).count ≥ 1`, „enthält kein“ `= 0`. */
function conditionType(c: PoolCondition): ConditionType {
  const m = c.measure;
  if (m.kind === 'value') return 'value';
  const plainCount =
    m.field === null &&
    m.agg === 'count' &&
    m.where.labels.length > 0 &&
    m.where.exclude.length === 0 &&
    m.where.min_confidence === null;
  if (plainCount && c.op === 'gte' && c.operand === 1) return 'has';
  if (plainCount && c.op === 'eq' && c.operand === 0) return 'has_not';
  return 'objects';
}

function conditionDraft(c: PoolCondition, values: Pick<ValuesOut, 'photo_values'>): ConditionDraft {
  const time = measureKind(c.measure, values) === 'time';
  const d: ConditionDraft = {
    uid: nextUid(),
    type: conditionType(c),
    measure: measureDraft(c.measure),
    op: c.op,
    a: '',
    b: '',
  };
  const o = c.operand;
  if (Array.isArray(o)) {
    d.a = operandText(o[0], time);
    d.b = operandText(o[1], time);
  } else if (typeof o === 'number') d.a = operandText(o, time);
  return d;
}

/** A spec from the server as an editable draft. */
export function fromSpec(
  id: string,
  spec: CategorySpec,
  values: Pick<ValuesOut, 'photo_values'>,
): CategoryDraft {
  const time = measureKind(spec.rank.by, values) === 'time';
  const v = spec.verdict;
  return {
    id,
    emoji: spec.emoji,
    title: spec.title,
    line: spec.line,
    pool: spec.pool.map((c) => conditionDraft(c, values)),
    by: measureDraft(spec.rank.by),
    order: spec.rank.order,
    threshold: spec.rank.threshold === null ? '' : operandText(spec.rank.threshold, time),
    thenBy: spec.rank.then_by.map((t) => ({ uid: nextUid(), by: measureDraft(t.by), order: t.order })),
    count: String(spec.select.count),
    onePerGuest: spec.select.one_per_guest,
    captionSame: spec.caption.value === null,
    captionValue: spec.caption.value ? measureDraft(spec.caption.value) : measureDraft(spec.rank.by),
    format: spec.caption.format,
    one: spec.caption.one,
    many: spec.caption.many,
    showObject: spec.caption.show_object,
    verdictOn: v !== null,
    verdictPrompt: v?.prompt ?? '',
    verdictCount: String(v?.count ?? 3),
    verdictModel: v?.model ?? '',
    verdictEffort: v?.effort ?? 'low',
  };
}

function conditionSpec(c: ConditionDraft, values: Pick<ValuesOut, 'photo_values'>): PoolCondition {
  if (c.type === 'has' || c.type === 'has_not') {
    const measure = measureSpec({ ...c.measure, field: '', agg: 'count', exclude: [], minConfidence: '' });
    return c.type === 'has' ? { measure, op: 'gte', operand: 1 } : { measure, op: 'eq', operand: 0 };
  }
  const measure = measureSpec(c.measure);
  const time = measureKind(measure, values) === 'time';
  if (c.op === 'exists' || c.op === 'not_exists') return { measure, op: c.op, operand: null };
  if (c.op === 'between')
    return { measure, op: c.op, operand: [readNumber(c.a, time), readNumber(c.b, time)] };
  return { measure, op: c.op, operand: readNumber(c.a, time) };
}

/** The draft as the JSON the server takes. Call {@link validate} first. */
export function toSpec(draft: CategoryDraft, values: Pick<ValuesOut, 'photo_values'>): CategorySpec {
  const by = measureSpec(draft.by);
  const threshold = draft.threshold.trim();
  const time = measureKind(by, values) === 'time';
  const prompt = draft.verdictPrompt.trim();
  const shown = draft.captionSame ? by : measureSpec(draft.captionValue);
  return {
    version: 2,
    emoji: draft.emoji.trim(),
    title: draft.title.trim(),
    line: draft.line.trim(),
    pool: draft.pool.map((c) => conditionSpec(c, values)),
    rank: {
      by,
      order: draft.order,
      threshold: threshold ? readNumber(threshold, time) : null,
      then_by: draft.thenBy.map((t) => ({ by: measureSpec(t.by), order: t.order })),
    },
    select: { count: Number(draft.count.trim()), one_per_guest: draft.onePerGuest },
    caption: {
      value: draft.captionSame ? null : shown,
      format: draft.format,
      one: draft.one.trim(),
      many: draft.many.trim(),
      show_object: draft.showObject && hasFocus(shown),
    },
    verdict: draft.verdictOn
      ? {
          prompt: prompt || null,
          count: Number(draft.verdictCount.trim()),
          model: draft.verdictModel || null,
          effort: draft.verdictEffort,
        }
      : null,
  };
}

// ------------------------------------------------------------------ measures

/** A winner gets a focus object (the frame on the wall) from this measure. */
export function hasFocus(m: Measure | MeasureDraft): boolean {
  if (m.kind !== 'objects') return false;
  const field = 'where' in m ? m.field : m.field || null;
  const agg = field ? m.agg : 'count';
  const labels = 'where' in m ? m.where.labels : m.labels;
  if (agg === 'count' && !field) return labels.length > 0;
  return true;
}

/** The property a measure reads, or null. */
export function propertyOf(m: Measure | MeasureDraft): string | null {
  if (m.kind !== 'objects') return null;
  return m.field?.startsWith('prop:') ? m.field.slice(5) : null;
}

/** Every property a draft reads (the badge „braucht externe KI“). */
export function draftProperties(d: CategoryDraft): string[] {
  const all = [
    ...d.pool.map((c) => c.measure),
    d.by,
    ...d.thenBy.map((t) => t.by),
    ...(d.captionSame ? [] : [d.captionValue]),
  ];
  return [...new Set(all.map(propertyOf).filter((p): p is string => p !== null))];
}

export type LabelNames = ReadonlyArray<Pick<LabelInfo, 'label' | 'label_de'>>;

/** A label's German name when it is known. */
export function labelName(labels: LabelNames, label: string): string {
  return labels.find((l) => l.label === label)?.label_de ?? label;
}

/** The canonical label for typed text: a known label (German or English name), else the text. */
export function labelFor(labels: LabelNames, text: string): string {
  const t = text.trim().toLowerCase();
  const hit = labels.find((l) => l.label_de.toLowerCase() === t || l.label === t);
  return hit ? hit.label : t;
}

export interface Catalogue {
  photo_values: ValuesOut['photo_values'];
  labels: LabelNames;
}

function fieldTitle(field: string | null): string {
  if (field === 'confidence') return 'Erkennungssicherheit';
  return field?.startsWith('prop:') ? field.slice(5) : 'Objekte';
}

function decimal(x: number): string {
  return x.toFixed(2).replace('.', ',');
}

function filterText(m: MeasureObjects, cat: Catalogue): string {
  const parts: string[] = [];
  const names = (ls: readonly string[]) => ls.map((l) => labelName(cat.labels, l)).join(', ');
  if (m.where.labels.length) parts.push(`nur ${names(m.where.labels)}`);
  if (m.where.exclude.length) parts.push(`ohne ${names(m.where.exclude)}`);
  if (m.where.min_confidence !== null)
    parts.push(`Sicherheit ab ${Math.round(m.where.min_confidence * 100)} %`);
  return parts.length ? ` (${parts.join('; ')})` : '';
}

/**
 * The measure as a German phrase with its direction (engine.describe): „Höchster
 * coolness-Wert unter allen Objekten“, „Die meisten Objekte (ohne Person)“.
 */
export function describe(m: Measure, order: RankOrder, cat: Catalogue): string {
  const hi = order === 'desc';
  if (m.kind === 'value') {
    if (m.key === 'photo.created_at') return hi ? 'Das neueste Foto' : 'Das früheste Foto';
    if (m.key === 'photo.guest_photos')
      return hi ? 'Die meisten Fotos eines Gasts' : 'Die wenigsten Fotos eines Gasts';
    const title = cat.photo_values.find((v) => v.key === m.key)?.title ?? m.key;
    return `${hi ? 'Höchster' : 'Niedrigster'} Wert bei „${title}“`;
  }
  const most = hi ? 'Die meisten' : 'Die wenigsten';
  const where = filterText(m, cat);
  const title = fieldTitle(m.field);
  if (m.field === null) return `${most} Objekte${where}`;
  if (m.agg === 'count') return `${most} bewerteten Objekte (${title})${where}`;
  if (m.agg === 'count_ge') return `${most} Objekte mit ${title} ab ${decimal(m.t ?? 0)}${where}`;
  const words: Record<Exclude<Aggregate, 'count' | 'count_ge'>, [string, string, string]> = {
    max: ['Höchster', 'Niedrigster', `${title}-Wert unter allen Objekten`],
    min: ['Niedrigster', 'Höchster', `${title}-Wert unter allen Objekten`],
    mean: ['Höchster', 'Niedrigster', `Durchschnitt von ${title}`],
    sum: ['Höchste', 'Niedrigste', `Summe von ${title}`],
    top_k_mean: ['Höchster', 'Niedrigster', `Schnitt der besten ${m.k ?? 2} ${title}-Werte`],
  };
  const [up, down, rest] = words[m.agg];
  return `${hi ? up : down} ${rest}${where}`;
}

function shortNumber(x: number): string {
  return Math.abs(x - Math.round(x)) < 1e-9 ? String(Math.round(x)) : numberText(Number(x.toFixed(2)));
}

/** The ranking in one line (engine.explain): „Höchster Wert bei „Personen“, mindestens 3“. */
export function explainRank(rank: CategorySpec['rank'], cat: Catalogue): string {
  let text = describe(rank.by, rank.order, cat);
  if (rank.threshold !== null) {
    const time = measureKind(rank.by, cat) === 'time';
    text += `, ${thresholdWord(rank.order)} ${time ? timeText(rank.threshold) : shortNumber(rank.threshold)}`;
  }
  return text.slice(0, 80);
}

/** A measure's name without direction („Personen“, „Anzahl Objekte (nur Hut)“, „höchster coolness“). */
export function measureName(m: Measure, cat: Catalogue): string {
  if (m.kind === 'value') return cat.photo_values.find((v) => v.key === m.key)?.title ?? m.key;
  const where = filterText(m, cat);
  if (m.field === null) return `Anzahl Objekte${where}`;
  const agg =
    m.agg === 'top_k_mean'
      ? `Mittel der besten ${m.k ?? 2}`
      : m.agg === 'count_ge'
        ? `Anzahl ≥ ${decimal(m.t ?? 0)}`
        : AGG_SHORT[m.agg];
  return `${fieldTitle(m.field)}: ${agg}${where}`;
}

const AGG_SHORT: Record<Aggregate, string> = {
  max: 'höchster Wert',
  min: 'niedrigster Wert',
  mean: 'Durchschnitt',
  sum: 'Summe',
  top_k_mean: 'Mittel der besten k',
  count_ge: 'Anzahl ≥ t',
  count: 'Anzahl bewerteter Objekte',
};

function timeText(seconds: number): string {
  const d = new Date(seconds * 1000);
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

/** A pool condition in plain German: „Personen ≥ 3“, „enthält Hut“, „enthält kein Glas“. */
export function conditionText(c: PoolCondition, cat: Catalogue): string {
  const m = c.measure;
  const type = conditionType(c);
  if (m.kind === 'objects' && (type === 'has' || type === 'has_not')) {
    const names = m.where.labels.map((l) => labelName(cat.labels, l)).join(' oder ');
    return `${type === 'has' ? 'enthält' : 'enthält kein'} ${names}`;
  }
  const name = measureName(m, cat);
  const time = measureKind(m, cat) === 'time';
  const n = (x: number) => (time ? timeText(x) : shortNumber(x));
  if (c.op === 'exists' || c.op === 'not_exists') return `${name} ${OP_LABELS[c.op]}`;
  if (c.op === 'between' && Array.isArray(c.operand))
    return `${name} zwischen ${n(c.operand[0])} und ${n(c.operand[1])}`;
  return `${name} ${OP_LABELS[c.op]} ${typeof c.operand === 'number' ? n(c.operand) : ''}`.trim();
}

/** The whole rule in plain German (the Live screen's expanded category). */
export function ruleText(
  spec: CategorySpec,
  cat: Catalogue,
): { pool: string; rank: string; ties: string[]; select: string } {
  const pool = spec.pool.length ? spec.pool.map((c) => conditionText(c, cat)).join(' und ') : 'Alle Fotos';
  const n = spec.select.count;
  const select = `${n === 1 ? 'Ein Gewinner' : `${n} Gewinner`}${spec.select.one_per_guest ? ', ein Foto pro Gast' : ''}`;
  return {
    pool,
    rank: explainRank(spec.rank, cat),
    ties: spec.rank.then_by.map((t) => describe(t.by, t.order, cat)),
    select,
  };
}

// ------------------------------------------------------------------- caption

/**
 * What the caption should be for a measure (when the host has not chosen): a count →
 * count with Einzahl/Mehrzahl, a value 0–1 → decimal, a time → time; the highest or
 * lowest of a property shows the object.
 */
export function suggestCaption(
  m: Measure,
  values: Pick<ValuesOut, 'photo_values'>,
): { format: CaptionFormat; showObject: boolean } {
  if (m.kind === 'value') {
    const info = values.photo_values.find((v) => v.key === m.key);
    if (info?.kind === 'time') return { format: 'time', showObject: false };
    if (info?.kind === 'count') return { format: 'count', showObject: false };
    return { format: info?.unit === '0–1' ? 'decimal' : 'number', showObject: false };
  }
  if (m.field === null || m.agg === 'count' || m.agg === 'count_ge')
    return { format: 'count', showObject: false };
  return { format: 'decimal', showObject: m.agg === 'max' || m.agg === 'min' };
}

/** The word after a decimal value: „0,93 Coolness“ (a property's name), „0,80 Sicherheit“. */
export function unitWord(m: Measure): string {
  if (m.kind !== 'objects' || !m.field) return '';
  if (m.field === 'confidence') return 'Sicherheit';
  const name = m.field.slice(5).replaceAll('_', ' ');
  return name.charAt(0).toUpperCase() + name.slice(1);
}

/** „7 Personen“, „82 % Drama“, „0,93 Coolness“, „Farbwert 73“, „um 19:42“ (engine.value_text). */
export function valueText(format: CaptionFormat, value: number | null, one: string, many: string): string {
  if (format === 'text') return one;
  if (format === 'none') return '';
  if (value === null) return one;
  if (format === 'count') {
    const n = Math.round(value);
    return `${n} ${n === 1 ? one : many}`.trim();
  }
  if (format === 'percent') return `${Math.round(value * 100)} % ${one}`.trim();
  if (format === 'decimal') return `${decimal(value)} ${one}`.trim();
  if (format === 'number') return `${one} ${value.toFixed(0)}`.trim();
  return `um ${timeText(value)}`;
}

/** (headline, detail) as the wall shows them (engine.caption). */
export function captionParts(
  caption: Pick<CategorySpec['caption'], 'format' | 'one' | 'many' | 'show_object'>,
  value: number | null,
  objectLabel: string | null,
): { headline: string; detail: string | null } {
  const text = valueText(caption.format, value, caption.one, caption.many);
  if (!caption.show_object) return { headline: text, detail: null };
  const headline = objectLabel ?? (caption.one || 'Objekt');
  return { headline, detail: text && text !== headline ? text : null };
}

/** A believable value for the mini preview of a format (no winner yet). */
export function sampleValue(format: CaptionFormat): number | null {
  switch (format) {
    case 'count':
      return 7;
    case 'percent':
      return 0.82;
    case 'decimal':
      return 0.93;
    case 'number':
      return 73;
    case 'time':
      return Math.round(new Date(2026, 9, 16, 19, 42).getTime() / 1000);
    default:
      return null;
  }
}

// ------------------------------------------------------------------- AI comments

/** The model a verdict runs on and its estimated price per comment for the chosen effort. */
export function verdictPrice(
  options: VerdictOptions | undefined,
  model: string,
  effort: Effort,
): { model: string; title: string; price: number; currency: string; measured: boolean } | null {
  if (!options) return null;
  const id = model || options.default_model;
  const m =
    options.models.find((x) => x.id === id) ?? options.models.find((x) => x.id === options.default_model);
  if (!m) return null;
  const e = m.efforts.find((x) => x.effort === (options.thinking ? effort : 'low')) ?? m.efforts[0];
  if (!e) return null;
  return {
    model: m.id,
    title: m.title,
    price: e.price_per_comment,
    currency: m.currency,
    measured: e.measured,
  };
}

/** „≈ 0,0014 $“ (two significant digits: these are fractions of a cent). */
export function priceText(price: number, currency: string): string {
  return `≈ ${new Intl.NumberFormat('de-DE', { style: 'currency', currency, maximumSignificantDigits: 2 }).format(price)}`;
}

// ------------------------------------------------------------------ validation

export const ID_RE = /^[a-z][a-z0-9_]{1,40}$/;
const FIELD_RE = /^(confidence|prop:[a-z][a-z0-9_]{1,30})$/;

/** How many user-perceived characters (an emoji with skin tone or ZWJ counts once). */
export function graphemes(text: string): number {
  return [...new Intl.Segmenter('de', { granularity: 'grapheme' }).segment(text)].length;
}

/** A category id from a title: „Prost! Gläser“ → "prost_glaeser". */
export function slugify(title: string): string {
  const base = title
    .toLowerCase()
    .replaceAll('ä', 'ae')
    .replaceAll('ö', 'oe')
    .replaceAll('ü', 'ue')
    .replaceAll('ß', 'ss')
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 36);
  if (!base) return 'kategorie';
  const id = /^[a-z]/.test(base) ? base : `k_${base}`;
  return id.length >= 2 ? id : 'kategorie';
}

/** A free id: the slug, or slug_2, slug_3 … */
export function freeId(title: string, taken: readonly string[]): string {
  const base = slugify(title);
  if (!taken.includes(base)) return base;
  for (let i = 2; ; i++) {
    const id = `${base}_${i}`;
    if (!taken.includes(id)) return id;
  }
}

export type DraftErrors = Record<string, string>;

/** Errors of one measure at `f` (`f`, `f.min`, `f.k`, `f.t`). */
export function checkMeasure(
  errors: DraftErrors,
  f: string,
  m: MeasureDraft,
  values: Pick<ValuesOut, 'photo_values'>,
): void {
  if (m.kind === 'value') {
    if (!m.key) errors[f] = 'Bitte einen Wert wählen.';
    else if (!values.photo_values.some((v) => v.key === m.key))
      errors[f] = 'Diesen Wert gibt es nicht (mehr).';
    return;
  }
  if (m.labels.length > LIMITS.labels || m.exclude.length > LIMITS.labels) {
    errors[f] = `Höchstens ${LIMITS.labels} Objekte.`;
  }
  if (m.field && !FIELD_RE.test(m.field)) errors[f] = 'Bitte wählen, was zählt.';
  const conf = m.minConfidence.trim();
  if (conf) {
    const c = parseDecimal(conf);
    if (!(c >= 0 && c <= 1)) errors[`${f}.min`] = 'Eine Zahl von 0 bis 1.';
  }
  if (!m.field) return;
  if (m.agg === 'top_k_mean') {
    const k = m.k.trim();
    if (!/^\d$/.test(k) || Number(k) < LIMITS.k[0] || Number(k) > LIMITS.k[1]) {
      errors[`${f}.k`] = `k: ${LIMITS.k[0]} bis ${LIMITS.k[1]}.`;
    }
  }
  if (m.agg === 'count_ge') {
    const t = parseDecimal(m.t);
    if (!(t >= 0 && t <= 1)) errors[`${f}.t`] = 't: eine Zahl von 0 bis 1.';
  }
}

function checkNumber(errors: DraftErrors, field: string, text: string, time: boolean): number {
  const n = readNumber(text, time);
  if (!Number.isFinite(n)) errors[field] = time ? 'Bitte Datum und Uhrzeit.' : 'Bitte eine Zahl.';
  return n;
}

export interface ValidateContext {
  values: Pick<ValuesOut, 'photo_values'>;
  /** ids in use (new categories only) */
  taken?: readonly string[];
  isNew?: boolean;
}

/**
 * Field errors in German, keyed like the inputs (and like the server's `field`): `id`,
 * `emoji`, `title`, `line`, `pool`, `pool.<i>` (its measure; `.min`, `.k`, `.t`),
 * `pool.<i>.a`, `pool.<i>.b`, `rank.by` (`.min`, `.k`, `.t`), `rank.threshold`,
 * `rank.then_by`, `rank.then_by.<i>`, `count`, `caption.value`, `one`, `many`,
 * `caption.show_object`, `verdict`, `verdict.count`. Empty = valid.
 */
export function validate(draft: CategoryDraft, ctx: ValidateContext): DraftErrors {
  const errors: DraftErrors = {};
  const { values } = ctx;
  if (ctx.isNew) {
    if (!ID_RE.test(draft.id)) {
      errors.id = 'Kleinbuchstaben, Ziffern und _, 2 bis 41 Zeichen, vorne ein Buchstabe.';
    } else if (ctx.taken?.includes(draft.id)) {
      errors.id = 'Diese Kennung gibt es schon.';
    }
  }
  if (graphemes(draft.emoji.trim()) !== 1) errors.emoji = 'Genau ein Emoji.';
  const title = draft.title.trim();
  if (title.length < 1 || title.length > LIMITS.title)
    errors.title = `Der Titel braucht 1 bis ${LIMITS.title} Zeichen.`;
  if (draft.line.trim().length > LIMITS.line) errors.line = `Höchstens ${LIMITS.line} Zeichen.`;
  if (draft.pool.length > LIMITS.pool) errors.pool = `Höchstens ${LIMITS.pool} Bedingungen.`;
  draft.pool.forEach((c, i) => {
    const f = `pool.${i}`;
    if (c.type === 'has' || c.type === 'has_not') {
      if (c.measure.labels.length === 0) errors[f] = 'Bitte ein Objekt wählen.';
      return;
    }
    checkMeasure(errors, f, c.measure, values);
    if (errors[f]) return;
    const time = measureKind(c.measure, values) === 'time';
    if (c.op === 'exists' || c.op === 'not_exists') return;
    const a = checkNumber(errors, `${f}.a`, c.a, time);
    if (c.op === 'between') {
      const b = checkNumber(errors, `${f}.b`, c.b, time);
      if (Number.isFinite(a) && Number.isFinite(b) && a > b)
        errors[`${f}.b`] = 'Muss mindestens so groß sein.';
    }
  });
  checkMeasure(errors, 'rank.by', draft.by, values);
  if (draft.threshold.trim()) {
    checkNumber(errors, 'rank.threshold', draft.threshold, measureKind(draft.by, values) === 'time');
  }
  if (draft.thenBy.length > LIMITS.thenBy) errors['rank.then_by'] = `Höchstens ${LIMITS.thenBy}.`;
  draft.thenBy.forEach((t, i) => checkMeasure(errors, `rank.then_by.${i}`, t.by, values));
  const count = draft.count.trim();
  const [min, max] = LIMITS.count;
  if (!/^\d{1,2}$/.test(count) || Number(count) < min || Number(count) > max) {
    errors.count = `Bitte eine ganze Zahl von ${min} bis ${max}.`;
  }
  if (!draft.captionSame) checkMeasure(errors, 'caption.value', draft.captionValue, values);
  if (draft.format === 'count') {
    if (!draft.one.trim()) errors.one = 'Wie heißt eins davon? (z. B. „Person“)';
    if (!draft.many.trim()) errors.many = 'Und mehrere? (z. B. „Personen“)';
  }
  if (draft.format === 'text' && !draft.one.trim()) errors.one = 'Bitte den Text.';
  if (draft.one.trim().length > LIMITS.words) errors.one = `Höchstens ${LIMITS.words} Zeichen.`;
  if (draft.many.trim().length > LIMITS.words) errors.many = `Höchstens ${LIMITS.words} Zeichen.`;
  if (draft.verdictOn) {
    if (draft.verdictPrompt.trim().length > LIMITS.verdict)
      errors.verdict = `Höchstens ${LIMITS.verdict} Zeichen.`;
    const n = draft.verdictCount.trim();
    const [lo, hi] = LIMITS.comments;
    if (!/^\d$/.test(n) || Number(n) < lo || Number(n) > hi) {
      errors['verdict.count'] = `Bitte eine ganze Zahl von ${lo} bis ${hi}.`;
    }
  }
  return errors;
}

/**
 * The input a server 400 `invalid_category` is about: its `field` (the server names the
 * editor's key), else guessed from the German message („Titel: …“). null = the form.
 */
export function serverField(message: string, data?: unknown): string | null {
  if (data && typeof data === 'object' && 'field' in data && typeof data.field === 'string') {
    return data.field;
  }
  const m = message.toLowerCase();
  const rules: Array<[RegExp, string]> = [
    [/\bkennung|\bid\b/, 'id'],
    [/emoji/, 'emoji'],
    [/untertitel|zeile/, 'line'],
    [/titel/, 'title'],
    [/bedingung/, 'pool'],
    [/rang: danach/, 'rank.then_by'],
    [/schwelle/, 'rank.threshold'],
    [/rang/, 'rank.by'],
    [/anzahl/, 'count'],
    [/urteil|prompt|verdict/, 'verdict'],
    [/beschriftung|label/, 'one'],
  ];
  for (const [re, field] of rules) if (re.test(m)) return field;
  return null;
}

/** `ids` with `id` moved by `delta` places (clamped); the same array when it can't move. */
export function moveId(ids: readonly string[], id: string, delta: number): string[] {
  const from = ids.indexOf(id);
  const to = Math.min(ids.length - 1, Math.max(0, from + delta));
  if (from < 0 || from === to) return [...ids];
  const next = [...ids];
  next.splice(from, 1);
  next.splice(to, 0, id);
  return next;
}
