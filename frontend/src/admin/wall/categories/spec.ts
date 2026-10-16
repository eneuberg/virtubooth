/**
 * The category editor's pure part (spec.test.ts): the form draft of a CategorySpec
 * (PLAN-NIGHT §4.2), operators per value kind, client-side validation that mirrors the
 * server's, and the round trip draft ⇄ spec. Inputs stay text while typing; toSpec
 * parses them.
 */
import type {
  CategorySpec,
  LabelInfo,
  Condition,
  ConditionOp,
  LabelStyle,
  SelectOrder,
  ThenBy,
  ValueInfo,
  ValueKind,
} from '../types';

// ------------------------------------------------------------------ operators

export const OP_LABELS: Record<ConditionOp, string> = {
  gt: '>',
  lt: '<',
  gte: '≥',
  lte: '≤',
  eq: '=',
  ne: '≠',
  between: 'zwischen',
  exists: 'existiert',
  not_exists: 'existiert nicht',
  contains: 'enthält',
  not_contains: 'enthält nicht',
  contains_any: 'enthält eins von',
};

const NUMBER_OPS: readonly ConditionOp[] = [
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
const LABEL_OPS: readonly ConditionOp[] = ['contains', 'not_contains', 'contains_any'];

/** The operators that fit a value kind, in menu order. */
export function opsFor(kind: ValueKind): readonly ConditionOp[] {
  return kind === 'labels' ? LABEL_OPS : NUMBER_OPS;
}

export type OperandShape = 'none' | 'number' | 'range' | 'label' | 'labels';

export function operandShape(op: ConditionOp): OperandShape {
  switch (op) {
    case 'exists':
    case 'not_exists':
      return 'none';
    case 'between':
      return 'range';
    case 'contains':
    case 'not_contains':
      return 'label';
    case 'contains_any':
      return 'labels';
    default:
      return 'number';
  }
}

export const STYLE_LABELS: Record<LabelStyle, string> = {
  count: 'Anzahl („7 Personen“)',
  percent: 'Prozent („82 % Drama“)',
  number: 'Zahl („Farbwert 73“)',
  time: 'Uhrzeit („um 19:42“)',
  fixed: 'Fester Text',
  object: 'Name des Objekts („Sonnenbrille“)',
};

export const ORDER_LABELS: Record<SelectOrder, string> = { top: 'Top', bottom: 'Bottom' };

// ------------------------------------------------------------- value catalogue

/**
 * Values with a parameter: the catalogue lists the base, the editor adds a label.
 * `objects.count:<label>` („Anzahl von <Label>“), `prop.<name>.at:<label>`.
 */
export interface ValueChoice {
  /** the key, or a template ending in ":" that still needs a label */
  id: string;
  title: string;
  group: string;
  kind: ValueKind;
  available: boolean;
  reason: string | null;
  inactive: boolean;
}

const PROP_RE = /^prop\.([a-z][a-z0-9_]*)\.(max|min|sum|mean|count)$/;

/** The picker's choices: the catalogue plus one template per parametrised value. */
export function valueChoices(values: readonly ValueInfo[]): ValueChoice[] {
  const out: ValueChoice[] = values.map((v) => ({
    id: v.key,
    title: v.title,
    group: v.group,
    kind: v.kind,
    available: v.available,
    reason: v.reason,
    inactive: false,
  }));
  const seen = new Set(out.map((c) => c.id));
  const add = (choice: ValueChoice) => {
    if (!seen.has(choice.id)) {
      seen.add(choice.id);
      out.push(choice);
    }
  };
  const objects = values.find((v) => v.key === 'objects' || v.key === 'objects.count');
  if (objects) {
    add({ ...choiceOf(objects), id: 'objects.count:', title: 'Anzahl von …', kind: 'count' });
  }
  for (const v of values) {
    const m = PROP_RE.exec(v.key);
    if (m) {
      add({ ...choiceOf(v), id: `prop.${m[1]}.at:`, title: `${m[1]} bei Objekt …`, kind: 'number' });
    }
  }
  return out;
}

function choiceOf(v: ValueInfo): ValueChoice {
  return {
    id: v.key,
    title: v.title,
    group: v.group,
    kind: v.kind,
    available: v.available,
    reason: v.reason,
    inactive: false,
  };
}

/** `objects.count:wine glass` → template `objects.count:` + param `wine glass`. */
export function splitKey(key: string): { base: string; param: string | null } {
  const i = key.indexOf(':');
  return i < 0 ? { base: key, param: null } : { base: key.slice(0, i + 1), param: key.slice(i + 1) };
}

/** The kind of a (possibly parametrised) value key, or null when the catalogue lacks it. */
export function kindOf(key: string, choices: readonly ValueChoice[]): ValueKind | null {
  const exact = choices.find((c) => c.id === key);
  if (exact) return exact.kind;
  const { base, param } = splitKey(key);
  if (param === null) return null;
  return choices.find((c) => c.id === base)?.kind ?? null;
}

/** The canonical label for typed text: a known label (German or English name), else the text. */
export function labelFor(labels: readonly LabelInfo[], text: string): string {
  const t = text.trim().toLowerCase();
  const hit = labels.find((l) => l.label_de.toLowerCase() === t || l.label === t);
  return hit ? hit.label : t;
}

// ------------------------------------------------------------------- the draft

export interface ConditionDraft {
  /** local React key, not sent */
  uid: number;
  /** a value key; a template („objects.count:“) takes its label from `param` */
  value: string;
  param: string;
  op: ConditionOp;
  a: string;
  b: string;
  labels: string[];
}

export interface ThenDraft {
  uid: number;
  by: string;
  param: string;
  order: SelectOrder;
}

export interface CategoryDraft {
  id: string;
  emoji: string;
  title: string;
  line: string;
  where: ConditionDraft[];
  by: string;
  byParam: string;
  order: SelectOrder;
  count: string;
  thenBy: ThenDraft[];
  onePerGuest: boolean;
  /** '' = the same value as `by` */
  labelValue: string;
  style: LabelStyle;
  one: string;
  many: string;
  /** '' = no verdict */
  verdict: string;
}

export const LIMITS = {
  title: 40,
  line: 80,
  where: 8,
  count: [1, 10],
  thenBy: 2,
  words: 40,
  verdict: 1000,
} as const;

let uidSeq = 0;
export const nextUid = () => ++uidSeq;

export function emptyCondition(value = '', op: ConditionOp = 'gte'): ConditionDraft {
  return { uid: nextUid(), value, param: '', op, a: '', b: '', labels: [] };
}

export function emptyDraft(): CategoryDraft {
  return {
    id: '',
    emoji: '⭐',
    title: '',
    line: '',
    where: [],
    by: '',
    byParam: '',
    order: 'top',
    count: '3',
    thenBy: [],
    onePerGuest: false,
    labelValue: '',
    style: 'count',
    one: '',
    many: '',
    verdict: '',
  };
}

/** A number as the editor shows it: German decimal comma. */
export function numberText(n: number): string {
  return String(n).replace('.', ',');
}

/** "0,5" / "0.5" / " 3 " → number; anything else NaN. */
export function parseDecimal(text: string): number {
  const t = text.trim().replace(',', '.');
  return /^-?\d+(\.\d+)?$/.test(t) || /^-?\.\d+$/.test(t) ? Number(t) : Number.NaN;
}

/** unix seconds ⇄ the value of an <input type="datetime-local"> (local time). */
const pad2 = (n: number) => String(n).padStart(2, '0');

export function unixToLocal(seconds: number): string {
  const d = new Date(seconds * 1000);
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}T${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

export function localToUnix(text: string): number {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(text)) return Number.NaN;
  const ms = new Date(text).getTime();
  return Number.isNaN(ms) ? Number.NaN : Math.round(ms / 1000);
}

function joinKey(base: string, param: string): string {
  return base.endsWith(':') ? `${base}${param.trim()}` : base;
}

function splitInto(key: string): { value: string; param: string } {
  const { base, param } = splitKey(key);
  return { value: param === null ? key : base, param: param ?? '' };
}

function operandText(n: number, time: boolean): string {
  return time ? unixToLocal(n) : numberText(n);
}

/** A spec from the server as an editable draft. `isTime` tells which values are times. */
export function fromSpec(
  id: string,
  spec: CategorySpec,
  isTime: (key: string) => boolean = () => false,
): CategoryDraft {
  const by = splitInto(spec.select.by);
  return {
    id,
    emoji: spec.emoji,
    title: spec.title,
    line: spec.line,
    where: spec.where.map((c) => conditionDraft(c, isTime(c.value))),
    by: by.value,
    byParam: by.param,
    order: spec.select.order,
    count: String(spec.select.count),
    thenBy: spec.select.then_by.map((t) => {
      const { value, param } = splitInto(t.by);
      return { uid: nextUid(), by: value, param, order: t.order };
    }),
    onePerGuest: spec.select.one_per_guest,
    labelValue: spec.label.value ?? '',
    style: spec.label.style,
    one: spec.label.one,
    many: spec.label.many,
    verdict: spec.verdict?.prompt ?? '',
  };
}

function conditionDraft(c: Condition, time: boolean): ConditionDraft {
  const { value, param } = splitInto(c.value);
  const d: ConditionDraft = { uid: nextUid(), value, param, op: c.op, a: '', b: '', labels: [] };
  const o = c.operand;
  if (Array.isArray(o)) {
    if (o.every((x): x is string => typeof x === 'string')) d.labels = [...o];
    else {
      d.a = operandText(o[0], time);
      d.b = operandText(o[1], time);
    }
  } else if (typeof o === 'number') d.a = operandText(o, time);
  else if (typeof o === 'string') d.a = o;
  return d;
}

/** Number text of a condition operand, as the value's kind reads it. */
function readNumber(text: string, kind: ValueKind | null): number {
  return kind === 'time' ? localToUnix(text) : parseDecimal(text);
}

/** The draft as the JSON the server takes. Call {@link validate} first. */
export function toSpec(draft: CategoryDraft, choices: readonly ValueChoice[]): CategorySpec {
  const where: Condition[] = draft.where.map((c) => {
    const value = joinKey(c.value, c.param);
    const kind = kindOf(value, choices);
    switch (operandShape(c.op)) {
      case 'none':
        return { value, op: c.op, operand: null };
      case 'range':
        return { value, op: c.op, operand: [readNumber(c.a, kind), readNumber(c.b, kind)] };
      case 'label':
        return { value, op: c.op, operand: c.a.trim() };
      case 'labels':
        return { value, op: c.op, operand: [...c.labels] };
      default:
        return { value, op: c.op, operand: readNumber(c.a, kind) };
    }
  });
  const thenBy: ThenBy[] = draft.thenBy.map((t) => ({ by: joinKey(t.by, t.param), order: t.order }));
  const verdict = draft.verdict.trim();
  return {
    emoji: draft.emoji.trim(),
    title: draft.title.trim(),
    line: draft.line.trim(),
    where,
    select: {
      by: joinKey(draft.by, draft.byParam),
      order: draft.order,
      count: Number(draft.count.trim()),
      then_by: thenBy,
      one_per_guest: draft.onePerGuest,
    },
    label: {
      value: draft.labelValue === '' ? null : draft.labelValue,
      style: draft.style,
      one: draft.one.trim(),
      many: draft.many.trim(),
    },
    verdict: verdict ? { prompt: verdict } : null,
  };
}

// ------------------------------------------------------------------ validation

export const ID_RE = /^[a-z][a-z0-9_]{1,40}$/;

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

function checkValue(
  errors: DraftErrors,
  field: string,
  base: string,
  param: string,
  choices: readonly ValueChoice[],
  numeric: boolean,
): ValueKind | null {
  if (!base) {
    errors[field] = 'Bitte einen Wert wählen.';
    return null;
  }
  if (base.endsWith(':') && !param.trim()) {
    errors[`${field}.param`] = 'Bitte ein Objekt wählen.';
    return null;
  }
  const kind = kindOf(joinKey(base, param), choices);
  if (kind === null) {
    errors[field] = 'Diesen Wert gibt es nicht (mehr).';
    return null;
  }
  if (numeric && kind === 'labels') {
    errors[field] = 'Nach einer Liste lässt sich nicht sortieren.';
    return null;
  }
  return kind;
}

function checkNumber(errors: DraftErrors, field: string, text: string, kind: ValueKind | null): number {
  const n = readNumber(text, kind);
  if (!Number.isFinite(n)) errors[field] = kind === 'time' ? 'Bitte Datum und Uhrzeit.' : 'Bitte eine Zahl.';
  return n;
}

export interface ValidateContext {
  choices: readonly ValueChoice[];
  /** ids in use (new categories only) */
  taken?: readonly string[];
  isNew?: boolean;
}

/**
 * Field errors in German, keyed like the inputs: `id`, `emoji`, `title`, `line`,
 * `where`, `where.<i>.value`, `where.<i>.value.param`, `where.<i>.op`, `where.<i>.a`,
 * `where.<i>.b`, `where.<i>.labels`, `by`, `by.param`, `count`, `then_by.<i>`,
 * `then_by.<i>.param`, `label.value`, `one`, `many`, `verdict`. Empty = valid.
 */
export function validate(draft: CategoryDraft, ctx: ValidateContext): DraftErrors {
  const errors: DraftErrors = {};
  const { choices } = ctx;
  if (ctx.isNew) {
    if (!ID_RE.test(draft.id)) {
      errors.id = 'Kleinbuchstaben, Ziffern und _, 2 bis 41 Zeichen, vorne ein Buchstabe.';
    } else if (ctx.taken?.includes(draft.id)) {
      errors.id = 'Diese Kennung gibt es schon.';
    }
  }
  if (graphemes(draft.emoji.trim()) !== 1) errors.emoji = 'Genau ein Emoji.';
  const title = draft.title.trim();
  if (title.length < 1 || title.length > LIMITS.title) {
    errors.title = `Der Titel braucht 1 bis ${LIMITS.title} Zeichen.`;
  }
  if (draft.line.trim().length > LIMITS.line) errors.line = `Höchstens ${LIMITS.line} Zeichen.`;
  if (draft.where.length > LIMITS.where) errors.where = `Höchstens ${LIMITS.where} Bedingungen.`;
  draft.where.forEach((c, i) => {
    const f = `where.${i}`;
    const kind = checkValue(errors, `${f}.value`, c.value, c.param, choices, false);
    if (kind === null) return;
    if (!opsFor(kind).includes(c.op)) {
      errors[`${f}.op`] = 'Dieser Vergleich passt nicht zum Wert.';
      return;
    }
    switch (operandShape(c.op)) {
      case 'number':
        checkNumber(errors, `${f}.a`, c.a, kind);
        break;
      case 'range': {
        const a = checkNumber(errors, `${f}.a`, c.a, kind);
        const b = checkNumber(errors, `${f}.b`, c.b, kind);
        if (Number.isFinite(a) && Number.isFinite(b) && a > b)
          errors[`${f}.b`] = 'Muss mindestens so groß sein.';
        break;
      }
      case 'label':
        if (!c.a.trim()) errors[`${f}.a`] = 'Bitte ein Objekt wählen.';
        break;
      case 'labels':
        if (c.labels.length === 0) errors[`${f}.labels`] = 'Bitte mindestens ein Objekt wählen.';
        break;
      default:
        break;
    }
  });
  checkValue(errors, 'by', draft.by, draft.byParam, choices, true);
  const count = draft.count.trim();
  const [min, max] = LIMITS.count;
  if (!/^\d{1,2}$/.test(count) || Number(count) < min || Number(count) > max) {
    errors.count = `Bitte eine ganze Zahl von ${min} bis ${max}.`;
  }
  if (draft.thenBy.length > LIMITS.thenBy) errors.then_by = `Höchstens ${LIMITS.thenBy}.`;
  draft.thenBy.forEach((t, i) => {
    checkValue(errors, `then_by.${i}`, t.by, t.param, choices, true);
  });
  if (draft.labelValue && kindOf(draft.labelValue, choices) === null) {
    errors['label.value'] = 'Diesen Wert gibt es nicht (mehr).';
  }
  if (draft.style === 'count') {
    if (!draft.one.trim()) errors.one = 'Wie heißt eins davon? (z. B. „Person“)';
    if (!draft.many.trim()) errors.many = 'Und mehrere? (z. B. „Personen“)';
  }
  if (draft.style === 'fixed' && !draft.one.trim()) errors.one = 'Bitte den Text.';
  if (draft.one.trim().length > LIMITS.words) errors.one = `Höchstens ${LIMITS.words} Zeichen.`;
  if (draft.many.trim().length > LIMITS.words) errors.many = `Höchstens ${LIMITS.words} Zeichen.`;
  if (draft.verdict.trim().length > LIMITS.verdict) {
    errors.verdict = `Höchstens ${LIMITS.verdict} Zeichen.`;
  }
  return errors;
}

/**
 * The input a server 400 `invalid_category` message is about: the message names the
 * field in German („Titel: …“); an explicit `field` in the body wins. null = the form.
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
    [/bedingung/, 'where'],
    [/anzahl/, 'count'],
    [/danach|then_by/, 'then_by'],
    [/urteil|prompt|verdict/, 'verdict'],
    [/auswahl|sortier|\bnach\b/, 'by'],
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
