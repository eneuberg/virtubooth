/**
 * The category editor sheet (categories v2, PLAN §5) in numbered steps:
 *
 *   1 Kopf: emoji, title, the line (empty: the generated explanation, „Vorschlag übernehmen“)
 *   2 Welche Fotos machen mit? „Alle Fotos“, or rows: Fotowert, Enthält (kein) Objekt,
 *     Anzahl Objekte, Eigenschaft
 *   3 Wer gewinnt? „Gewinner ist das Foto mit dem [höchsten|niedrigsten] [Messgröße]“,
 *     „zählt erst ab [mindestens|höchstens] …“, tie-breakers folded away
 *   4 Wie viele? 1–10, one photo per guest
 *   5 Beschriftung: suggested from the measure, with a mini preview as on the wall
 *   6 KI-Kommentare (optional): how many, the prompt (empty: the default), model and
 *     Denkaufwand with the estimated price per comment
 *
 * and the live preview of the current winners (POST /categories/preview, 400 ms after the
 * last change). A category that reads a property carries „braucht externe KI“; one that
 * is locked (property missing or in the Papierkorb, external AI off) can be saved, but
 * only switched off. Validation mirrors the server's (spec.ts); a server 400 lands at the
 * field it names.
 */
import { useQueryClient } from '@tanstack/react-query';
import { ArrowDownWideNarrow, Lock, Plus, Sparkles, Trash2, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Button as AriaButton, Link, Menu, MenuItem, MenuTrigger, Popover } from 'react-aria-components';
import { isApiError } from '@/api/client';
import { formatNumber } from '@/lib/format';
import { Badge } from '@/ui/Badge';
import { Button, buttonStyles } from '@/ui/Button';
import { Checkbox } from '@/ui/Checkbox';
import { ConfirmDialog } from '@/ui/ConfirmDialog';
import { cx } from '@/ui/cx';
import { HelpDisclosure } from '@/ui/HelpDisclosure';
import { IconButton } from '@/ui/IconButton';
import { SegmentedControl } from '@/ui/SegmentedControl';
import { Select } from '@/ui/Select';
import { Sheet } from '@/ui/Sheet';
import { Spinner } from '@/ui/Spinner';
import { useSurface } from '@/ui/Surface';
import { Switch } from '@/ui/Switch';
import { TextField } from '@/ui/TextField';
import { showToast } from '@/ui/Toast';
import { errorText } from '../../common/usePhotoActions';
import { ExternalAiHint } from '../../ml/ExternalAiHint';
import { useLlm } from '../../ml/hooks';
import { EFFORTS, type Effort, type VerdictOptions } from '../../ml/types';
import { createCategory, deleteCategory, previewCategory, saveCategory } from '../api';
import { wk } from '../keys';
import {
  CAPTION_FORMATS,
  POOL_OPS,
  type CaptionFormat,
  type CategoryItem,
  type CategoryLock,
  type CategoryPreview,
  type PoolOp,
  type RankOrder,
  type ValuesOut,
} from '../types';
import { MeasurePicker } from './MeasurePicker';
import { LabelsPicker, PlainPicker } from './pickers';
import {
  captionParts,
  draftProperties,
  EFFORT_LABELS,
  emptyCondition,
  emptyDraft,
  emptyMeasure,
  explainRank,
  FORMAT_LABELS,
  freeId,
  fromSpec,
  hasFocus,
  LIMITS,
  measureKind,
  measureSpec,
  nextUid,
  OP_LABELS,
  priceText,
  sampleValue,
  serverField,
  suggestCaption,
  thresholdWord,
  toSpec,
  unitWord,
  validate,
  verdictPrice,
  type CategoryDraft,
  type ConditionDraft,
  type ConditionType,
  type DraftErrors,
} from './spec';

const FORMAT_OPTIONS = CAPTION_FORMATS.map((f) => ({ id: f, label: FORMAT_LABELS[f] }));
const ORDER_OPTIONS = [
  { id: 'desc', label: 'höchsten' },
  { id: 'asc', label: 'niedrigsten' },
] as const;
const THEN_ORDER_OPTIONS = [
  { id: 'desc', label: 'höher zuerst' },
  { id: 'asc', label: 'niedriger zuerst' },
] as const;
/** the model Select's id for `model: null` (react-aria keys are not empty) */
const DEFAULT_MODEL = 'standard';

/** What „+ Bedingung“ offers (§5, step 2). */
const ADD_ROWS: ReadonlyArray<{ id: string; type: ConditionType; label: string; field?: string }> = [
  { id: 'value', type: 'value', label: 'Fotowert …' },
  { id: 'has', type: 'has', label: 'Enthält Objekt …' },
  { id: 'has_not', type: 'has_not', label: 'Enthält kein Objekt …' },
  { id: 'count', type: 'objects', label: 'Anzahl Objekte …' },
  { id: 'prop', type: 'objects', label: 'Eigenschaft …', field: 'prop' },
];

function Step({ n, title, children, testid }: { n: number; title: string; children: ReactNode; testid?: string }) {
  return (
    <fieldset className="grid min-w-0 gap-3 border-t border-line pt-3" data-testid={testid}>
      <legend className="float-left mb-1 flex w-full items-center gap-2 text-md font-bold">
        <span
          aria-hidden="true"
          className="grid size-6 shrink-0 place-items-center rounded-full bg-ink text-xs text-surface tabular"
        >
          {n}
        </span>
        {title}
      </legend>
      {children}
    </fieldset>
  );
}

const MENU_ITEM =
  'flex min-h-10 cursor-pointer items-center rounded-small px-3 text-sm text-ink outline-none hover:bg-surface-hover focus:bg-surface-hover focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus';

function AddCondition({ disabled, onAdd }: { disabled: boolean; onAdd: (row: ConditionDraft) => void }) {
  const surface = useSurface();
  return (
    <MenuTrigger>
      <AriaButton
        isDisabled={disabled}
        className={buttonStyles({ size: 'xs', variant: 'secondary', className: 'justify-self-start' })}
        data-testid="condition-add"
      >
        <Plus aria-hidden="true" className="size-4" strokeWidth={2.25} />
        Bedingung
      </AriaButton>
      <Popover
        data-surface={surface}
        placement="bottom start"
        offset={4}
        className="w-60 rounded-control border border-line bg-surface-raised text-ink shadow-float outline-none"
      >
        <Menu
          aria-label="Bedingung hinzufügen"
          onAction={(key) => {
            const row = ADD_ROWS.find((r) => r.id === key);
            if (row) onAdd(emptyCondition(row.type, row.field ?? ''));
          }}
          className="grid gap-0.5 p-1.5 outline-none"
        >
          {ADD_ROWS.map((r) => (
            <MenuItem key={r.id} id={r.id} textValue={r.label} className={MENU_ITEM} data-testid={`condition-add-${r.id}`}>
              {r.label}
            </MenuItem>
          ))}
        </Menu>
      </Popover>
    </MenuTrigger>
  );
}

function ConditionRow({
  index,
  cond,
  values,
  errors,
  onChange,
  onRemove,
}: {
  index: number;
  cond: ConditionDraft;
  values: ValuesOut;
  errors: DraftErrors;
  onChange: (next: ConditionDraft) => void;
  onRemove: () => void;
}) {
  const f = `pool.${index}`;
  const name = `Bedingung ${index + 1}`;
  const time = measureKind(cond.measure, values) === 'time';
  const numberField = (key: 'a' | 'b', label: string) => (
    <TextField
      label={label}
      hideLabel
      size="sm"
      type={time ? 'datetime-local' : 'text'}
      inputMode={time ? undefined : 'decimal'}
      value={cond[key]}
      onChange={(v) => onChange({ ...cond, [key]: v })}
      errorMessage={errors[`${f}.${key}`] ?? null}
      className="min-w-0"
      data-testid={`cond-${key}`}
    />
  );
  const objectRow = cond.type === 'has' || cond.type === 'has_not';
  return (
    <li className="grid gap-2 rounded-control bg-surface-sunk/60 p-2" data-testid="condition" data-type={cond.type}>
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold">
          {cond.type === 'has'
            ? 'Enthält Objekt'
            : cond.type === 'has_not'
              ? 'Enthält kein Objekt'
              : cond.type === 'value'
                ? 'Fotowert'
                : cond.measure.field
                  ? 'Eigenschaft der Objekte'
                  : 'Anzahl Objekte'}
        </span>
        <IconButton label={`${name} entfernen`} icon={X} onPress={onRemove} className="ml-auto" />
      </div>
      {objectRow ? (
        <LabelsPicker
          label={`${name}: Objekt`}
          labels={values.labels}
          value={cond.measure.labels}
          onChange={(labels) => onChange({ ...cond, measure: { ...cond.measure, labels } })}
          error={errors[f]}
          testid="cond-labels"
        />
      ) : (
        <>
          <MeasurePicker
            label={name}
            value={cond.measure}
            onChange={(measure) => onChange({ ...cond, measure })}
            values={values}
            name={f}
            errors={errors}
            objectsOnly={cond.type === 'objects'}
            testid="cond-measure"
          />
          <div className="grid gap-2 sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)] sm:items-start">
            <PlainPicker<PoolOp>
              label={`${name}: Vergleich`}
              options={POOL_OPS.map((op) => ({ id: op, label: OP_LABELS[op] }))}
              value={cond.op}
              onChange={(op) => onChange({ ...cond, op })}
              testid="cond-op"
            />
            {cond.op === 'exists' || cond.op === 'not_exists' ? null : cond.op === 'between' ? (
              <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-start gap-1.5">
                {numberField('a', `${name}: von`)}
                <span className="pt-2 text-sm text-ink-muted">und</span>
                {numberField('b', `${name}: bis`)}
              </div>
            ) : (
              numberField('a', `${name}: Zahl`)
            )}
          </div>
        </>
      )}
    </li>
  );
}

interface PreviewState {
  loading: boolean;
  data: CategoryPreview | null;
  error: string | null;
}

export const PREVIEW_DELAY_MS = 400;

/** POST /categories/preview for a valid spec, 400 ms after the last change. */
function usePreview(specJson: string | null): PreviewState {
  const [state, setState] = useState<PreviewState>({ loading: false, data: null, error: null });
  useEffect(() => {
    if (specJson === null) return undefined;
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      setState((s) => ({ ...s, loading: true }));
      previewCategory(specJson, ctrl.signal).then(
        (data) => setState({ loading: false, data, error: null }),
        (err: unknown) => {
          if (ctrl.signal.aborted) return;
          setState({ loading: false, data: null, error: errorText(err) });
        },
      );
    }, PREVIEW_DELAY_MS);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [specJson]);
  return state;
}

function Preview({ state }: { state: PreviewState }) {
  return (
    <div className="grid gap-2" data-testid="category-preview" aria-live="polite">
      <h3 className="flex items-center gap-2 text-md font-bold">
        Vorschau: aktuelle Gewinner
        {state.loading ? <Spinner label="Lädt…" className="size-4" /> : null}
      </h3>
      {state.error ? (
        <p className="text-sm text-ink-muted">{state.error}</p>
      ) : state.data ? (
        <>
          <p className="text-sm text-ink-muted tabular" data-testid="category-preview-matched">
            {formatNumber(state.data.matched)} {state.data.matched === 1 ? 'Foto' : 'Fotos'} im Pool
            {state.data.reason ? ` · ${state.data.reason}` : ''}
          </p>
          {state.data.winners.length > 0 ? (
            <ol className="grid grid-cols-[repeat(auto-fill,minmax(4.5rem,1fr))] gap-2">
              {state.data.winners.map((w, i) => (
                <li key={w.photo_id} className="grid min-w-0 gap-1">
                  <img
                    src={w.thumb_url}
                    alt={`Platz ${i + 1}: ${w.label}`}
                    loading="lazy"
                    className="aspect-square w-full rounded-small bg-surface-sunk object-cover"
                  />
                  <span aria-hidden="true" className="truncate text-xs text-ink-muted tabular">
                    <span className="font-semibold text-ink">{i + 1}.</span> {w.label}
                  </span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-sm text-ink-muted">Gerade gewinnt kein Foto.</p>
          )}
        </>
      ) : (
        <p className="text-sm text-ink-muted">Sobald alles ausgefüllt ist, zeigt sie die Gewinner.</p>
      )}
    </div>
  );
}

/** The caption as the wall shows it under a winner: main line, value chip, „von …“. */
function CaptionPreview({ draft, preview }: { draft: CategoryDraft; preview: CategoryPreview | null }) {
  const first = preview?.winners[0];
  const showObject = draft.showObject && hasFocus(draft.captionSame ? draft.by : draft.captionValue);
  const parts = first
    ? { headline: first.headline, detail: first.detail }
    : captionParts(
        { format: draft.format, one: draft.one.trim(), many: draft.many.trim(), show_object: showObject },
        sampleValue(draft.format),
        showObject ? 'Sonnenbrille' : null,
      );
  return (
    <div
      className="grid grid-cols-[4.5rem_minmax(0,1fr)] items-center gap-3 rounded-control bg-surface-sunk/60 p-2"
      data-testid="caption-preview"
    >
      {first ? (
        <img src={first.thumb_url} alt="" className="aspect-square w-full rounded-small object-cover" />
      ) : (
        <div aria-hidden="true" className="grid aspect-square place-items-center rounded-small bg-surface-raised text-2xl">
          {draft.emoji.trim() || '⭐'}
        </div>
      )}
      <div className="grid min-w-0 gap-1">
        <span className="truncate text-md font-bold" data-testid="caption-preview-headline">
          {parts.headline || '—'}
        </span>
        {parts.detail ? (
          <span
            className="justify-self-start rounded-full bg-accent-tint px-2 py-0.5 text-xs font-semibold"
            data-testid="caption-preview-detail"
          >
            {parts.detail}
          </span>
        ) : null}
        <span className="text-xs text-ink-muted">von {first ? 'Gast' : 'Funky Flamingo'}</span>
      </div>
    </div>
  );
}

function VerdictPrice({ options, model, effort }: { options: VerdictOptions | undefined; model: string; effort: Effort }) {
  const price = verdictPrice(options, model, effort);
  if (!price) return null;
  return (
    <p className="text-xs text-ink-muted tabular" data-testid="verdict-price" data-measured={price.measured}>
      {priceText(price.price, price.currency)} pro Kommentar ({price.title})
      {price.measured ? ' · aus echten Läufen' : ' · Schätzung, noch nicht gemessen'}
    </p>
  );
}

function LockNotice({ lock }: { lock: CategoryLock }) {
  return (
    <p
      className="flex items-start gap-2 rounded-control p-2 text-sm text-mark ring-1 ring-current ring-inset"
      data-testid="category-locked"
      data-reason={lock.reason}
    >
      <Lock aria-hidden="true" className="mt-0.5 size-4 shrink-0" strokeWidth={2.25} />
      <span>
        Gesperrt: {lock.message} Speichern geht, aber nur ausgeschaltet.{' '}
        <Link href="/manage?tab=ml" className="font-semibold text-ink underline underline-offset-2">
          {lock.reason === 'ai_off' ? 'Zur Externen KI' : 'Zum Papierkorb der Eigenschaften'}
        </Link>
      </span>
    </p>
  );
}

export interface CategorySheetProps {
  /** null = a new category */
  item: CategoryItem | null;
  values: ValuesOut;
  /** every id in use (for a new id) */
  taken: readonly string[];
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}

function newDraft(values: ValuesOut): CategoryDraft {
  const people = values.photo_values.some((v) => v.key === 'people');
  return {
    ...emptyDraft(),
    by: emptyMeasure('value', people ? 'people' : ''),
    one: people ? 'Person' : '',
    many: people ? 'Personen' : '',
  };
}

export function CategorySheet({ item, values, taken, isOpen, onOpenChange }: CategorySheetProps) {
  const qc = useQueryClient();
  // the AI comments' models, prices and red hint
  const llm = useLlm(isOpen);
  const isNew = item === null;
  const [draft, setDraft] = useState<CategoryDraft>(() => (item ? fromSpec(item.id, item.spec, values) : newDraft(values)));
  // the host chose the caption's format: a new measure no longer suggests one
  const [captionTouched, setCaptionTouched] = useState(!isNew);
  const [idTouched, setIdTouched] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const [serverErrors, setServerErrors] = useState<DraftErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const errorRef = useRef<HTMLParagraphElement>(null);

  const errors = validate(draft, { values, taken, isNew });
  const valid = Object.keys(errors).length === 0;
  const shown: DraftErrors = { ...(showErrors ? errors : {}), ...serverErrors };
  const spec = useMemo(() => (valid ? toSpec(draft, values) : null), [valid, draft, values]);
  const preview = usePreview(spec ? JSON.stringify(spec) : null);
  const explanation = preview.data?.explanation ?? (spec ? explainRank(spec.rank, values) : '');
  const lock = preview.data?.locked ?? item?.locked ?? null;
  const props = draftProperties(draft);
  const verdictOptions = llm.data?.verdict;

  const update = (change: Partial<CategoryDraft>) => {
    setServerErrors({});
    setFormError(null);
    setDraft((d) => {
      const next = { ...d, ...change };
      if (isNew && !idTouched && change.title !== undefined) next.id = freeId(change.title, taken);
      // a new measure suggests its caption until the host picks one
      const measureChanged = change.by !== undefined || change.captionValue !== undefined || change.captionSame !== undefined;
      if (!captionTouched && measureChanged) {
        const measure = next.captionSame ? next.by : next.captionValue;
        if (measure.kind === 'objects' || measure.key) {
          const m = measureSpec(measure);
          const s = suggestCaption(m, values);
          if (s.format !== 'count' && s.format !== next.format) {
            // the count's words do not fit a decimal: its unit instead
            next.one = s.format === 'decimal' ? unitWord(m) : '';
            next.many = '';
          }
          next.format = s.format;
          next.showObject = s.showObject;
        }
      }
      return next;
    });
  };

  const setCondition = (i: number, c: ConditionDraft) => update({ pool: draft.pool.map((x, j) => (j === i ? c : x)) });

  const done = async (message: string, tone: 'success' | 'info' = 'success') => {
    await qc.invalidateQueries({ queryKey: wk.categories });
    showToast({ message, tone });
    onOpenChange(false);
  };

  const save = async () => {
    setShowErrors(true);
    if (!spec) {
      setFormError('Bitte die markierten Felder prüfen.');
      return;
    }
    setBusy(true);
    try {
      if (isNew) {
        const out = await createCategory(draft.id, spec, true);
        await done(
          out.enabled || !out.locked
            ? `„${spec.title}“ angelegt.`
            : `„${spec.title}“ angelegt, aber aus: ${out.locked.message}`,
          out.enabled ? 'success' : 'info',
        );
        return;
      }
      try {
        await saveCategory(item.id, spec, item.enabled);
        await done(`„${spec.title}“ gespeichert.`);
      } catch (err) {
        // locked: saved, but switched off (§5)
        if (!(isApiError(err) && err.code === 'category_locked')) throw err;
        const out = await saveCategory(item.id, spec, false);
        await done(`„${spec.title}“ gespeichert, aber ausgeschaltet: ${out.locked?.message ?? err.message}`, 'info');
      }
    } catch (err) {
      const field = isApiError(err) && err.status < 500 ? serverField(err.message, err.data) : null;
      if (isApiError(err) && err.code === 'category_exists') setServerErrors({ id: err.message });
      else if (field) setServerErrors({ [field]: errorText(err) });
      else setFormError(errorText(err));
      if (!field) errorRef.current?.focus();
    } finally {
      setBusy(false);
    }
  };

  const words =
    draft.format === 'count'
      ? (['one', 'many'] as const)
      : draft.format === 'none' || draft.format === 'time'
        ? ([] as const)
        : (['one'] as const);
  const wordLabel = (key: 'one' | 'many') =>
    draft.format === 'count'
      ? key === 'one'
        ? 'Einzahl (1 …)'
        : 'Mehrzahl (7 …)'
      : draft.format === 'text'
        ? 'Text'
        : 'Einheit zur Zahl';
  const shownMeasure = draft.captionSame ? draft.by : draft.captionValue;
  const thresholdTime = measureKind(draft.by, values) === 'time';

  return (
    <Sheet
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title={isNew ? 'Neue Kategorie' : 'Kategorie bearbeiten'}
      size="lg"
      // a click into a combobox's list counts as "outside" for a dismissable modal and
      // would close the sheet; "Abbrechen" closes it (no edit is lost by a stray click)
      isDismissable={false}
      data-testid="category-sheet"
      footer={
        <div className="grid gap-2">
          {formError ? (
            <p ref={errorRef} tabIndex={-1} role="alert" className="text-sm text-danger outline-none" data-testid="category-form-error">
              {formError}
            </p>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            {isNew ? null : (
              <Button
                size="sm"
                variant="danger-outline"
                icon={Trash2}
                onPress={() => {
                  setDeleteError(null);
                  setConfirmDelete(true);
                }}
                data-testid="category-delete"
              >
                Löschen…
              </Button>
            )}
            <Button size="sm" variant="quiet" onPress={() => onOpenChange(false)} className="ml-auto">
              Abbrechen
            </Button>
            <Button size="sm" variant="primary" isPending={busy} onPress={() => void save()} data-testid="category-save">
              {isNew ? 'Anlegen' : 'Speichern'}
            </Button>
          </div>
        </div>
      }
    >
      <div className="grid gap-5">
        {props.length > 0 || lock ? (
          <div className="grid gap-2">
            {props.length > 0 ? (
              <p className="flex flex-wrap items-center gap-2 text-xs text-ink-muted" data-testid="category-needs-ai">
                <Badge tone="mark" icon={Sparkles}>
                  braucht externe KI
                </Badge>
                liest {props.map((p) => `„${p}“`).join(', ')}; die Vorschau rechnet mit den Werten vom letzten Poll.
              </p>
            ) : null}
            {lock ? <LockNotice lock={lock} /> : null}
          </div>
        ) : null}

        <Step n={1} title="Kopf" testid="category-head">
          <div className="grid gap-3 sm:grid-cols-[6rem_minmax(0,1fr)]">
            <TextField
              label="Emoji"
              size="sm"
              value={draft.emoji}
              onChange={(emoji) => update({ emoji })}
              errorMessage={shown.emoji ?? null}
              data-testid="category-emoji"
            />
            <TextField
              label="Titel"
              size="sm"
              value={draft.title}
              maxLength={60}
              onChange={(title) => update({ title })}
              errorMessage={shown.title ?? null}
              data-testid="category-title"
            />
          </div>
          <div className="grid gap-1.5">
            <TextField
              label="Erklärung"
              size="sm"
              value={draft.line}
              maxLength={100}
              placeholder={explanation || 'Wird aus der Regel erzeugt'}
              onChange={(line) => update({ line })}
              errorMessage={shown.line ?? null}
              description="Die Zeile unter dem Titel auf der Wall. Leer: die automatische Erklärung."
              data-testid="category-line"
            />
            {explanation && draft.line.trim() !== explanation ? (
              <Button
                size="xs"
                variant="quiet"
                onPress={() => update({ line: explanation })}
                className="justify-self-start"
                data-testid="category-line-suggest"
              >
                Vorschlag übernehmen
              </Button>
            ) : null}
          </div>
          {isNew ? (
            <TextField
              label="Kennung"
              size="sm"
              value={draft.id}
              spellCheck="false"
              onChange={(id) => {
                setIdTouched(true);
                update({ id });
              }}
              errorMessage={shown.id ?? null}
              description="Intern, lässt sich später nicht ändern."
              className="font-mono"
              data-testid="category-id"
            />
          ) : null}
        </Step>

        <Step n={2} title="Welche Fotos machen mit?" testid="category-pool">
          {draft.pool.length === 0 ? (
            <p className="text-sm text-ink-muted" data-testid="category-pool-all">
              Alle Fotos.
            </p>
          ) : (
            <ol className="grid gap-2">
              {draft.pool.map((c, i) => (
                <ConditionRow
                  key={c.uid}
                  index={i}
                  cond={c}
                  values={values}
                  errors={shown}
                  onChange={(next) => setCondition(i, next)}
                  onRemove={() => update({ pool: draft.pool.filter((_, j) => j !== i) })}
                />
              ))}
            </ol>
          )}
          {shown.pool ? <p className="text-sm text-danger">{shown.pool}</p> : null}
          <AddCondition
            disabled={draft.pool.length >= LIMITS.pool}
            onAdd={(row) => {
              // „Eigenschaft …“: the first property there is
              if (row.measure.field === 'prop') {
                const prop = values.object_fields.find((f) => f.property)?.field ?? 'confidence';
                row.measure = { ...row.measure, field: prop };
              }
              update({ pool: [...draft.pool, row] });
            }}
          />
          {draft.pool.length > 0 ? <p className="text-xs text-ink-muted">Alle Bedingungen müssen stimmen.</p> : null}
        </Step>

        <Step n={3} title="Wer gewinnt?" testid="category-rank">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span>Gewinner ist das Foto mit dem</span>
            <SegmentedControl
              label="Richtung"
              size="sm"
              options={ORDER_OPTIONS}
              value={draft.order}
              onChange={(order: RankOrder) => update({ order })}
              data-testid="category-order"
            />
          </div>
          <MeasurePicker
            label="Rang"
            value={draft.by}
            onChange={(by) => update({ by })}
            values={values}
            name="rank.by"
            errors={shown}
            order={draft.order}
            testid="category-by"
          />
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span>zählt erst ab</span>
            <span className="font-semibold" data-testid="category-threshold-word">
              {thresholdWord(draft.order)}
            </span>
            <TextField
              label={`Schwelle (${thresholdWord(draft.order)})`}
              hideLabel
              size="sm"
              type={thresholdTime ? 'datetime-local' : 'text'}
              inputMode={thresholdTime ? undefined : 'decimal'}
              placeholder="leer: ohne"
              value={draft.threshold}
              onChange={(threshold) => update({ threshold })}
              errorMessage={shown['rank.threshold'] ?? null}
              className="w-40"
              data-testid="category-threshold"
            />
          </div>
          <HelpDisclosure
            variant="section"
            headingLevel={false}
            summary={`Bei Gleichstand${draft.thenBy.length ? ` (${draft.thenBy.length})` : ''}`}
            defaultExpanded={draft.thenBy.length > 0}
          >
            <div className="grid gap-3" data-testid="category-then">
              {draft.thenBy.map((t, i) => (
                <div key={t.uid} className="grid gap-2 rounded-control bg-surface-sunk/60 p-2" data-testid="category-then-row">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold">{i === 0 ? 'danach' : 'und danach'}</span>
                    <SegmentedControl
                      label={`danach ${i + 1}: Richtung`}
                      size="sm"
                      options={THEN_ORDER_OPTIONS}
                      value={t.order}
                      onChange={(order: RankOrder) =>
                        update({ thenBy: draft.thenBy.map((x, j) => (j === i ? { ...x, order } : x)) })
                      }
                    />
                    <IconButton
                      label={`danach ${i + 1} entfernen`}
                      icon={X}
                      onPress={() => update({ thenBy: draft.thenBy.filter((_, j) => j !== i) })}
                      className="ml-auto"
                    />
                  </div>
                  <MeasurePicker
                    label={`danach ${i + 1}`}
                    value={t.by}
                    onChange={(by) => update({ thenBy: draft.thenBy.map((x, j) => (j === i ? { ...x, by } : x)) })}
                    values={values}
                    name={`rank.then_by.${i}`}
                    errors={shown}
                    order={t.order}
                    testid="category-then-by"
                  />
                </div>
              ))}
              {shown['rank.then_by'] ? <p className="text-sm text-danger">{shown['rank.then_by']}</p> : null}
              {draft.thenBy.length < LIMITS.thenBy ? (
                <Button
                  size="xs"
                  variant="secondary"
                  icon={ArrowDownWideNarrow}
                  onPress={() =>
                    update({ thenBy: [...draft.thenBy, { uid: nextUid(), by: emptyMeasure('value'), order: 'desc' }] })
                  }
                  className="justify-self-start"
                  data-testid="category-then-add"
                >
                  Weitere Messgröße
                </Button>
              ) : null}
              <p className="text-xs text-ink-muted">Zuletzt immer: das neuere Foto.</p>
            </div>
          </HelpDisclosure>
        </Step>

        <Step n={4} title="Wie viele?" testid="category-select">
          <div className="flex flex-wrap items-start gap-4">
            <TextField
              label="Gewinner (1 bis 10)"
              size="sm"
              inputMode="numeric"
              value={draft.count}
              onChange={(count) => update({ count })}
              errorMessage={shown.count ?? null}
              className="w-40"
              data-testid="category-count"
            />
            <Checkbox isSelected={draft.onePerGuest} onChange={(onePerGuest) => update({ onePerGuest })} className="sm:mt-7">
              Ein Foto pro Gast
            </Checkbox>
          </div>
        </Step>

        <Step n={5} title="Beschriftung" testid="category-caption">
          <div className="grid gap-3 sm:grid-cols-2">
            <Select<CaptionFormat>
              label="Format"
              size="sm"
              options={FORMAT_OPTIONS}
              value={draft.format}
              onChange={(format) => {
                setCaptionTouched(true);
                update({ format });
              }}
              data-testid="category-format"
            />
            <Select<'same' | 'other'>
              label="Wert aus"
              size="sm"
              options={[
                { id: 'same', label: 'der Rang-Messgröße' },
                { id: 'other', label: 'einer anderen Messgröße' },
              ]}
              value={draft.captionSame ? 'same' : 'other'}
              onChange={(v) => update({ captionSame: v === 'same', captionValue: v === 'same' ? draft.captionValue : draft.by })}
              data-testid="category-caption-source"
            />
          </div>
          {draft.captionSame ? null : (
            <MeasurePicker
              label="Beschriftung"
              value={draft.captionValue}
              onChange={(captionValue) => update({ captionValue })}
              values={values}
              name="caption.value"
              errors={shown}
              testid="category-caption-value"
            />
          )}
          {words.length > 0 ? (
            <div className={cx('grid gap-3', words.length === 2 && 'sm:grid-cols-2')}>
              {words.map((key) => (
                <TextField
                  key={key}
                  label={wordLabel(key)}
                  size="sm"
                  value={draft[key]}
                  onChange={(v) => update({ [key]: v })}
                  errorMessage={shown[key] ?? null}
                  data-testid={`category-${key}`}
                />
              ))}
            </div>
          ) : null}
          {hasFocus(shownMeasure) ? (
            <Checkbox
              isSelected={draft.showObject}
              onChange={(showObject) => {
                setCaptionTouched(true);
                update({ showObject });
              }}
              data-testid="category-show-object"
            >
              Das Objekt nennen und auf dem Foto einrahmen
            </Checkbox>
          ) : null}
          {shown['caption.show_object'] ? <p className="text-sm text-danger">{shown['caption.show_object']}</p> : null}
          <CaptionPreview draft={draft} preview={preview.data} />
        </Step>

        <Step n={6} title="KI-Kommentare (optional)" testid="category-verdict">
          <Switch isSelected={draft.verdictOn} onChange={(verdictOn) => update({ verdictOn })} data-testid="category-verdict-on">
            Die KI kommentiert die besten Fotos
          </Switch>
          {draft.verdictOn ? (
            <div className="grid gap-3">
              <p className="text-xs text-ink-muted">
                Ein Satz unter dem Foto, je Gewinner einer, in Rangfolge. Die KI wählt nie selbst den Sieger.
                {item?.verdict_paused ? ' Gerade pausiert: die externe KI ist aus.' : ''}
              </p>
              <TextField
                label="Kommentare zu den besten (1 bis 5)"
                size="sm"
                inputMode="numeric"
                value={draft.verdictCount}
                onChange={(verdictCount) => update({ verdictCount })}
                errorMessage={shown['verdict.count'] ?? null}
                className="w-56"
                data-testid="category-verdict-count"
              />
              <label className="grid gap-1.5">
                <span className="text-sm font-semibold">Aufgabe für die KI (leer: Standard)</span>
                <textarea
                  value={draft.verdictPrompt}
                  onChange={(e) => update({ verdictPrompt: e.target.value })}
                  rows={3}
                  maxLength={LIMITS.verdict + 200}
                  placeholder={verdictOptions?.default_prompt.replace('{title}', draft.title.trim() || 'Titel') ?? ''}
                  aria-invalid={shown.verdict ? true : undefined}
                  className={cx(
                    'min-h-20 rounded-control border bg-field-bg px-3 py-2 text-md text-ink outline-none focus-visible:outline-2 focus-visible:outline-focus sm:text-sm',
                    shown.verdict ? 'border-danger' : 'border-field',
                  )}
                  data-testid="category-verdict-prompt"
                />
              </label>
              {shown.verdict ? <p className="text-sm text-danger">{shown.verdict}</p> : null}
              {verdictOptions ? (
                <HelpDisclosure summary="Was die KI immer mitbekommt (Systemprompt)" headingLevel={false}>
                  <pre className="text-xs whitespace-pre-wrap text-ink-muted" data-testid="verdict-system-prompt">
                    {verdictOptions.system_prompt}
                  </pre>
                </HelpDisclosure>
              ) : null}
              {verdictOptions && verdictOptions.models.length > 0 ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  <Select<string>
                    label="Modell"
                    size="sm"
                    options={[
                      {
                        id: DEFAULT_MODEL,
                        label: `Standard (${verdictOptions.models.find((m) => m.id === verdictOptions.default_model)?.title ?? verdictOptions.default_model})`,
                      },
                      ...verdictOptions.models.map((m) => ({ id: m.id, label: m.title })),
                    ]}
                    value={draft.verdictModel || DEFAULT_MODEL}
                    onChange={(id) => update({ verdictModel: id === DEFAULT_MODEL ? '' : id })}
                    data-testid="category-verdict-model"
                  />
                  {verdictOptions.thinking ? (
                    <Select<Effort>
                      label="Denkaufwand"
                      size="sm"
                      options={EFFORTS.map((e) => ({ id: e, label: EFFORT_LABELS[e] }))}
                      value={draft.verdictEffort}
                      onChange={(verdictEffort) => update({ verdictEffort })}
                      data-testid="category-verdict-effort"
                    />
                  ) : null}
                </div>
              ) : null}
              <VerdictPrice options={verdictOptions} model={draft.verdictModel} effort={draft.verdictEffort} />
              <ExternalAiHint status={llm.data} where="elsewhere" />
            </div>
          ) : null}
        </Step>

        <Preview state={preview} />
      </div>
      {isNew ? null : (
        <ConfirmDialog
          isOpen={confirmDelete}
          onOpenChange={setConfirmDelete}
          title={`„${item.spec.title}“ löschen?`}
          confirmLabel="Löschen"
          error={deleteError}
          onConfirm={async () => {
            try {
              await deleteCategory(item.id);
              await done(`„${item.spec.title}“ gelöscht.`);
            } catch (err) {
              setDeleteError(errorText(err));
              throw err;
            }
          }}
          data-testid="confirm"
        >
          <p>
            {item.preset ? 'Sie ist eine Vorlage: „Vorlagen wiederherstellen“ holt sie zurück.' : 'Das lässt sich nicht rückgängig machen.'}
          </p>
        </ConfirmDialog>
      )}
    </Sheet>
  );
}
