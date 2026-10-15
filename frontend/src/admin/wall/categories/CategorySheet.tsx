/**
 * The category editor sheet: emoji, title and line; the conditions (value, operator,
 * operand); the selection (Top/Bottom, Anzahl, nach, danach, one per guest); the label
 * on the wall; the optional AI verdict prompt; and a live preview of the current
 * winners (POST /categories/preview, 400 ms after the last change). Validation mirrors
 * the server's (spec.ts); a server 400 lands at the field it names.
 */
import { useQueryClient } from '@tanstack/react-query';
import { ArrowDownWideNarrow, Plus, Trash2, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { isApiError } from '@/api/client';
import { formatNumber } from '@/lib/format';
import { Button } from '@/ui/Button';
import { Checkbox } from '@/ui/Checkbox';
import { ConfirmDialog } from '@/ui/ConfirmDialog';
import { cx } from '@/ui/cx';
import { IconButton } from '@/ui/IconButton';
import { SegmentedControl } from '@/ui/SegmentedControl';
import { Select } from '@/ui/Select';
import { Sheet } from '@/ui/Sheet';
import { Spinner } from '@/ui/Spinner';
import { TextField } from '@/ui/TextField';
import { showToast } from '@/ui/Toast';
import { errorText } from '../../common/usePhotoActions';
import { createCategory, deleteCategory, previewCategory, saveCategory } from '../api';
import { wk } from '../keys';
import { optionsOf } from '../labels';
import {
  LABEL_STYLES,
  SELECT_ORDERS,
  type CategoryItem,
  type CategoryPreview,
  type ConditionOp,
  type ValuesOut,
} from '../types';
import { LabelPicker, LabelsPicker, ValuePicker } from './pickers';
import {
  emptyCondition,
  emptyDraft,
  freeId,
  fromSpec,
  kindOf,
  LIMITS,
  nextUid,
  OP_LABELS,
  operandShape,
  opsFor,
  ORDER_LABELS,
  serverField,
  STYLE_LABELS,
  toSpec,
  validate,
  valueChoices,
  type CategoryDraft,
  type ConditionDraft,
  type DraftErrors,
  type ValueChoice,
} from './spec';

const ORDER_OPTIONS = optionsOf(SELECT_ORDERS, ORDER_LABELS);
const STYLE_OPTIONS = optionsOf(LABEL_STYLES, STYLE_LABELS);
/** „Zahl aus“: the label shows the `nach` value (label.value null) */
const SAME_AS_BY: ValueChoice = {
  id: '=by',
  title: 'wie „nach“',
  group: 'Standard',
  kind: 'number',
  available: true,
  reason: null,
  archived: false,
};

function Section({ title, children, testid }: { title: string; children: ReactNode; testid?: string }) {
  return (
    <fieldset className="grid min-w-0 gap-3 border-t border-line pt-3" data-testid={testid}>
      <legend className="float-left mb-1 w-full text-md font-bold">{title}</legend>
      {children}
    </fieldset>
  );
}

function ConditionRow({
  index,
  cond,
  choices,
  values,
  errors,
  onChange,
  onRemove,
}: {
  index: number;
  cond: ConditionDraft;
  choices: readonly ValueChoice[];
  values: ValuesOut;
  errors: DraftErrors;
  onChange: (next: ConditionDraft) => void;
  onRemove: () => void;
}) {
  const f = `where.${index}`;
  const kind = kindOf(cond.value, choices);
  const ops = kind ? opsFor(kind) : opsFor('number');
  const shape = operandShape(cond.op);
  const time = kind === 'time';
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
  return (
    <li
      className="grid gap-2 rounded-control bg-surface-sunk/60 p-2 sm:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1.3fr)_auto] sm:items-start"
      data-testid="condition"
    >
      <div className="grid min-w-0 gap-1.5">
        <ValuePicker
          label={`Bedingung ${index + 1}: Wert`}
          hideLabel
          choices={choices}
          value={cond.value}
          onChange={(value) => {
            const k = kindOf(value, choices);
            const nextOps = k ? opsFor(k) : opsFor('number');
            onChange({ ...cond, value, op: nextOps.includes(cond.op) ? cond.op : (nextOps[0] ?? 'gte') });
          }}
          error={errors[`${f}.value`]}
          testid="cond-value"
        />
        {cond.value.endsWith(':') ? (
          <LabelPicker
            label={`Bedingung ${index + 1}: Objekt`}
            hideLabel
            labels={values.labels}
            value={cond.param}
            onChange={(param) => onChange({ ...cond, param })}
            error={errors[`${f}.value.param`]}
            testid="cond-param"
          />
        ) : null}
      </div>
      <div className="grid min-w-0 gap-1">
        <Select<ConditionOp>
          label={`Bedingung ${index + 1}: Vergleich`}
          inlineLabel
          size="sm"
          options={ops.map((op) => ({ id: op, label: OP_LABELS[op] }))}
          value={cond.op}
          onChange={(op) => onChange({ ...cond, op })}
          data-testid="cond-op"
        />
        {errors[`${f}.op`] ? <span className="text-sm text-danger">{errors[`${f}.op`]}</span> : null}
      </div>
      <div className="grid min-w-0 gap-1.5">
        {shape === 'number' ? numberField('a', `Bedingung ${index + 1}: Zahl`) : null}
        {shape === 'range' ? (
          <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-start gap-1.5">
            {numberField('a', `Bedingung ${index + 1}: von`)}
            <span className="pt-2 text-sm text-ink-muted">und</span>
            {numberField('b', `Bedingung ${index + 1}: bis`)}
          </div>
        ) : null}
        {shape === 'label' ? (
          <LabelPicker
            label={`Bedingung ${index + 1}: Objekt`}
            hideLabel
            labels={values.labels}
            value={cond.a}
            onChange={(a) => onChange({ ...cond, a })}
            error={errors[`${f}.a`]}
            testid="cond-label"
          />
        ) : null}
        {shape === 'labels' ? (
          <LabelsPicker
            label={`Bedingung ${index + 1}: Objekte`}
            labels={values.labels}
            value={cond.labels}
            onChange={(labels) => onChange({ ...cond, labels })}
            error={errors[`${f}.labels`]}
            testid="cond-labels"
          />
        ) : null}
      </div>
      <IconButton label={`Bedingung ${index + 1} entfernen`} icon={X} onPress={onRemove} />
    </li>
  );
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
            {formatNumber(state.data.matched)} {state.data.matched === 1 ? 'Foto passt' : 'Fotos passen'}
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

export interface CategorySheetProps {
  /** null = a new category */
  item: CategoryItem | null;
  values: ValuesOut;
  /** every id in use (for a new id) */
  taken: readonly string[];
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CategorySheet({ item, values, taken, isOpen, onOpenChange }: CategorySheetProps) {
  const qc = useQueryClient();
  const choices = useMemo(() => valueChoices(values.values), [values.values]);
  const isNew = item === null;
  const [draft, setDraft] = useState<CategoryDraft>(() =>
    item
      ? fromSpec(item.id, item.spec, (key) => kindOf(key, choices) === 'time')
      : { ...emptyDraft(), by: choices.some((c) => c.id === 'people') ? 'people' : '' },
  );
  const [idTouched, setIdTouched] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const [serverErrors, setServerErrors] = useState<DraftErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const errorRef = useRef<HTMLParagraphElement>(null);

  const errors = validate(draft, { choices, taken, isNew });
  const valid = Object.keys(errors).length === 0;
  const shown: DraftErrors = { ...(showErrors ? errors : {}), ...serverErrors };
  const spec = valid ? toSpec(draft, choices) : null;
  const preview = usePreview(spec ? JSON.stringify(spec) : null);

  const update = (change: Partial<CategoryDraft>) => {
    setServerErrors({});
    setFormError(null);
    setDraft((d) => {
      const next = { ...d, ...change };
      if (isNew && !idTouched && change.title !== undefined) next.id = freeId(change.title, taken);
      return next;
    });
  };

  const setCondition = (i: number, c: ConditionDraft) =>
    update({ where: draft.where.map((x, j) => (j === i ? c : x)) });

  const done = async (message: string) => {
    await qc.invalidateQueries({ queryKey: wk.categories });
    showToast({ message, tone: 'success' });
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
      if (isNew) await createCategory(draft.id, spec, true);
      else await saveCategory(item.id, spec, item.enabled);
      await done(isNew ? `„${spec.title}“ angelegt.` : `„${spec.title}“ gespeichert.`);
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

  const labelWords =
    draft.style === 'count'
      ? (['one', 'many'] as const)
      : draft.style === 'fixed' || draft.style === 'percent' || draft.style === 'number'
        ? (['one'] as const)
        : ([] as const);
  const wordLabel = (key: 'one' | 'many') =>
    draft.style === 'count'
      ? key === 'one'
        ? 'Einzahl (1 …)'
        : 'Mehrzahl (7 …)'
      : draft.style === 'fixed'
        ? 'Text'
        : 'Wort zur Zahl';

  return (
    <Sheet
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title={isNew ? 'Neue Kategorie' : 'Kategorie bearbeiten'}
      size="lg"
      data-testid="category-sheet"
      footer={
        <div className="grid gap-2">
          {formError ? (
            <p
              ref={errorRef}
              tabIndex={-1}
              role="alert"
              className="text-sm text-danger outline-none"
              data-testid="category-form-error"
            >
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
            <Button
              size="sm"
              variant="primary"
              isPending={busy}
              onPress={() => void save()}
              data-testid="category-save"
            >
              {isNew ? 'Anlegen' : 'Speichern'}
            </Button>
          </div>
        </div>
      }
    >
      <div className="grid gap-5">
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
        <TextField
          label="Untertitel"
          size="sm"
          value={draft.line}
          maxLength={100}
          onChange={(line) => update({ line })}
          errorMessage={shown.line ?? null}
          description="Eine Zeile unter dem Titel auf der Live-Wall."
          data-testid="category-line"
        />
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

        <Section title="Bedingungen" testid="category-conditions">
          {draft.where.length === 0 ? (
            <p className="text-sm text-ink-muted">Ohne Bedingung zählt jedes Foto.</p>
          ) : (
            <ol className="grid gap-2">
              {draft.where.map((c, i) => (
                <ConditionRow
                  key={c.uid}
                  index={i}
                  cond={c}
                  choices={choices}
                  values={values}
                  errors={shown}
                  onChange={(next) => setCondition(i, next)}
                  onRemove={() => update({ where: draft.where.filter((_, j) => j !== i) })}
                />
              ))}
            </ol>
          )}
          {shown.where ? <p className="text-sm text-danger">{shown.where}</p> : null}
          <Button
            size="xs"
            variant="secondary"
            icon={Plus}
            isDisabled={draft.where.length >= LIMITS.where}
            onPress={() => update({ where: [...draft.where, emptyCondition()] })}
            className="justify-self-start"
            data-testid="condition-add"
          >
            Bedingung hinzufügen
          </Button>
          <p className="text-xs text-ink-muted">Alle Bedingungen müssen stimmen.</p>
        </Section>

        <Section title="Auswahl: Top / Bottom" testid="category-selection">
          <div className="grid gap-3 sm:grid-cols-[auto_6rem_minmax(0,1fr)] sm:items-start">
            <div className="grid gap-1.5">
              <span className="text-sm font-semibold">Reihenfolge</span>
              <SegmentedControl
                label="Auswahl"
                size="sm"
                options={ORDER_OPTIONS}
                value={draft.order}
                onChange={(order) => update({ order })}
                data-testid="category-order"
              />
            </div>
            <TextField
              label="Anzahl"
              size="sm"
              inputMode="numeric"
              value={draft.count}
              onChange={(count) => update({ count })}
              errorMessage={shown.count ?? null}
              data-testid="category-count"
            />
            <div className="grid min-w-0 gap-1.5">
              <ValuePicker
                label="nach"
                choices={choices}
                numericOnly
                value={draft.by}
                onChange={(by) => update({ by, byParam: by.endsWith(':') ? draft.byParam : '' })}
                error={shown.by}
                testid="category-by"
              />
              {draft.by.endsWith(':') ? (
                <LabelPicker
                  label="nach: Objekt"
                  hideLabel
                  labels={values.labels}
                  value={draft.byParam}
                  onChange={(byParam) => update({ byParam })}
                  error={shown['by.param']}
                />
              ) : null}
            </div>
          </div>
          {draft.thenBy.map((t, i) => (
            <div
              key={t.uid}
              className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-start"
              data-testid="category-then"
            >
              <div className="grid min-w-0 gap-1.5">
                <ValuePicker
                  label={i === 0 ? 'danach' : 'und danach'}
                  choices={choices}
                  numericOnly
                  value={t.by}
                  onChange={(by) =>
                    update({ thenBy: draft.thenBy.map((x, j) => (j === i ? { ...x, by, param: '' } : x)) })
                  }
                  error={shown[`then_by.${i}`]}
                />
                {t.by.endsWith(':') ? (
                  <LabelPicker
                    label="danach: Objekt"
                    hideLabel
                    labels={values.labels}
                    value={t.param}
                    onChange={(param) =>
                      update({ thenBy: draft.thenBy.map((x, j) => (j === i ? { ...x, param } : x)) })
                    }
                    error={shown[`then_by.${i}.param`]}
                  />
                ) : null}
              </div>
              <SegmentedControl
                label={i === 0 ? 'danach: Reihenfolge' : 'und danach: Reihenfolge'}
                size="sm"
                options={ORDER_OPTIONS}
                value={t.order}
                onChange={(order) =>
                  update({ thenBy: draft.thenBy.map((x, j) => (j === i ? { ...x, order } : x)) })
                }
                className="sm:mt-6.5"
              />
              <IconButton
                label={`${i === 0 ? 'danach' : 'und danach'} entfernen`}
                icon={X}
                onPress={() => update({ thenBy: draft.thenBy.filter((_, j) => j !== i) })}
                className="sm:mt-6"
              />
            </div>
          ))}
          {shown.then_by ? <p className="text-sm text-danger">{shown.then_by}</p> : null}
          {draft.thenBy.length < LIMITS.thenBy ? (
            <Button
              size="xs"
              variant="secondary"
              icon={ArrowDownWideNarrow}
              onPress={() =>
                update({ thenBy: [...draft.thenBy, { uid: nextUid(), by: '', param: '', order: 'top' }] })
              }
              className="justify-self-start"
              data-testid="category-then-add"
            >
              Bei Gleichstand danach sortieren
            </Button>
          ) : null}
          <Checkbox isSelected={draft.onePerGuest} onChange={(onePerGuest) => update({ onePerGuest })}>
            Pro Gast höchstens ein Foto
          </Checkbox>
          <p className="text-xs text-ink-muted">Bei Gleichstand gewinnt das neuere Foto.</p>
        </Section>

        <Section title="Beschriftung auf der Wall" testid="category-label">
          <div className="grid gap-3 sm:grid-cols-2">
            <Select
              label="Art"
              size="sm"
              options={STYLE_OPTIONS}
              value={draft.style}
              onChange={(style) => update({ style })}
              data-testid="category-style"
            />
            <ValuePicker
              label="Zahl aus"
              choices={[SAME_AS_BY, ...choices]}
              numericOnly
              value={draft.labelValue || SAME_AS_BY.id}
              onChange={(v) => update({ labelValue: v === SAME_AS_BY.id ? '' : v })}
              error={shown['label.value']}
            />
          </div>
          {labelWords.length > 0 ? (
            <div className={cx('grid gap-3', labelWords.length === 2 && 'sm:grid-cols-2')}>
              {labelWords.map((key) => (
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
        </Section>

        <Section title="Urteil der KI (Prompt)" testid="category-verdict">
          <label className="grid gap-1.5">
            <span className="sr-only">Urteil der KI (Prompt)</span>
            <textarea
              value={draft.verdict}
              onChange={(e) => update({ verdict: e.target.value })}
              rows={3}
              maxLength={LIMITS.verdict + 200}
              placeholder="z. B. Werte das coolste Objekt aus den Ergebnissen raus und sag mir, von wem und was."
              aria-invalid={shown.verdict ? true : undefined}
              aria-describedby="category-verdict-help"
              className={cx(
                'min-h-20 rounded-control border bg-field-bg px-3 py-2 text-md text-ink outline-none focus-visible:outline-2 focus-visible:outline-focus sm:text-sm',
                shown.verdict ? 'border-danger' : 'border-field',
              )}
              data-testid="category-verdict-prompt"
            />
          </label>
          {shown.verdict ? <p className="text-sm text-danger">{shown.verdict}</p> : null}
          <p id="category-verdict-help" className="text-xs text-ink-muted">
            Optional. Bei jeder Abfrage schreibt die externe KI dazu einen Satz, der unter dem Gewinnerfoto
            steht. Leer = kein Urteil.
          </p>
        </Section>

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
            {item.preset
              ? 'Sie ist eine Vorlage: „Vorlagen wiederherstellen“ holt sie zurück.'
              : 'Das lässt sich nicht rückgängig machen.'}
          </p>
        </ConfirmDialog>
      )}
    </Sheet>
  );
}
