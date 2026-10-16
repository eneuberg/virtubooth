/**
 * „Messgröße wählen“ (PLAN §5, step 3), the one building block of a category:
 *
 *   A  Quelle: „Fotowert“ or „Objekte im Foto“
 *   B  Welche Objekte: all, only [labels], without [labels], a minimum confidence
 *   C  Was zählt: the number of objects, a property ▾, or the detection confidence
 *   D  Baustein: highest (shows the object), lowest, mean, sum, mean of the best k,
 *      number with a value ≥ t
 *
 * and the measure in plain German under it. Persons are not filtered out by default
 * (host decision §8.4: the property's prompt lets the AI decide).
 */
import { useId } from 'react';
import { SegmentedControl } from '@/ui/SegmentedControl';
import { Select } from '@/ui/Select';
import { TextField } from '@/ui/TextField';
import type { Aggregate, RankOrder, ValuesOut } from '../types';
import { LabelsPicker, ValuePicker } from './pickers';
import {
  AGG_LABELS,
  checkMeasure,
  describe,
  FIELD_AGGS,
  measureSpec,
  type DraftErrors,
  type MeasureDraft,
} from './spec';

const SOURCES = [
  { id: 'value', label: 'Fotowert' },
  { id: 'objects', label: 'Objekte im Foto' },
] as const;

/** „Was zählt?“: '' is the number of objects. */
function fieldOptions(values: ValuesOut, current: string): Array<{ id: string; label: string }> {
  const out = [{ id: 'count', label: 'Anzahl der Objekte' }];
  for (const f of values.object_fields) {
    out.push({
      id: f.field,
      label: f.property ? `Eigenschaft „${f.title}“` : f.title,
    });
  }
  if (current && !out.some((o) => o.id === current)) {
    // a property in the Papierkorb or not there (yet): still shown, the lock says why
    out.push({ id: current, label: `Eigenschaft „${current.replace(/^prop:/, '')}“ (fehlt)` });
  }
  return out;
}

export interface MeasurePickerProps {
  /** the accessible name's start („Rang“, „Bedingung 2“) */
  label: string;
  value: MeasureDraft;
  onChange: (next: MeasureDraft) => void;
  values: ValuesOut;
  /** the errors' key of this measure (`rank.by`, `pool.1`) */
  name: string;
  errors: DraftErrors;
  /** only objects (the pool's „Anzahl Objekte“ and „Eigenschaft“ rows) */
  objectsOnly?: boolean;
  /** the direction for the sentence under it; none: no sentence */
  order?: RankOrder;
  testid?: string;
}

export function MeasurePicker({
  label,
  value: m,
  onChange,
  values,
  name,
  errors,
  objectsOnly = false,
  order,
  testid,
}: MeasurePickerProps) {
  const sentenceId = useId();
  const set = (change: Partial<MeasureDraft>) => onChange({ ...m, ...change });
  const own: DraftErrors = {};
  checkMeasure(own, name, m, values);
  const sentence = order && Object.keys(own).length === 0 ? describe(measureSpec(m), order, values) : null;
  const fieldId = m.field || 'count';
  return (
    <div className="grid min-w-0 gap-2" data-testid={testid} data-kind={m.kind}>
      {objectsOnly ? null : (
        <SegmentedControl
          label={`${label}: Quelle`}
          size="sm"
          options={SOURCES}
          value={m.kind}
          onChange={(kind) => set(kind === 'objects' ? { kind, field: m.field } : { kind })}
          className="justify-self-start"
          data-testid="measure-source"
        />
      )}
      {m.kind === 'value' ? (
        <ValuePicker
          label={`${label}: Fotowert`}
          hideLabel
          choices={values.photo_values}
          value={m.key}
          onChange={(key) => set({ key })}
          error={errors[name]}
          testid="measure-value"
        />
      ) : (
        <div className="grid gap-2">
          {values.objects_available ? null : (
            <p className="text-xs text-ink-muted">{values.objects_reason}</p>
          )}
          <div className="grid gap-2 sm:grid-cols-2">
            <Select
              label="Was zählt?"
              size="sm"
              options={fieldOptions(values, m.field)}
              value={fieldId}
              onChange={(id) => {
                const field = id === 'count' ? '' : id;
                // a property's highest value shows its object: the first choice
                set({ field, agg: field ? (m.field ? m.agg : 'max') : 'count' });
              }}
              data-testid="measure-field"
            />
            {m.field ? (
              <Select<Aggregate>
                label="Baustein"
                size="sm"
                options={FIELD_AGGS.map((a) => ({ id: a, label: AGG_LABELS[a] }))}
                value={m.agg}
                onChange={(agg) => set({ agg })}
                data-testid="measure-agg"
              />
            ) : null}
          </div>
          {m.field && m.agg === 'top_k_mean' ? (
            <TextField
              label="k (die besten wie viele?)"
              size="sm"
              inputMode="numeric"
              value={m.k}
              onChange={(k) => set({ k })}
              errorMessage={errors[`${name}.k`] ?? null}
              className="max-w-48"
              data-testid="measure-k"
            />
          ) : null}
          {m.field && m.agg === 'count_ge' ? (
            <TextField
              label="t (Wert ab, 0 bis 1)"
              size="sm"
              inputMode="decimal"
              value={m.t}
              onChange={(t) => set({ t })}
              errorMessage={errors[`${name}.t`] ?? null}
              className="max-w-48"
              data-testid="measure-t"
            />
          ) : null}
          <fieldset className="grid gap-2 rounded-control bg-surface-sunk/50 p-2" data-testid="measure-filter">
            <legend className="sr-only">Welche Objekte?</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              <div className="grid content-start gap-1">
                <span className="text-xs font-semibold text-ink-muted">Nur diese Objekte (leer: alle)</span>
                <LabelsPicker
                  label={`${label}: nur diese Objekte`}
                  labels={values.labels}
                  value={m.labels}
                  onChange={(labels) => set({ labels })}
                  testid="measure-labels"
                />
              </div>
              <div className="grid content-start gap-1">
                <span className="text-xs font-semibold text-ink-muted">Ohne diese Objekte</span>
                <LabelsPicker
                  label={`${label}: ohne diese Objekte`}
                  labels={values.labels}
                  value={m.exclude}
                  onChange={(exclude) => set({ exclude })}
                  testid="measure-exclude"
                />
              </div>
            </div>
            <TextField
              label="Mindestsicherheit (0 bis 1, leer: jede)"
              size="sm"
              inputMode="decimal"
              value={m.minConfidence}
              onChange={(minConfidence) => set({ minConfidence })}
              errorMessage={errors[`${name}.min`] ?? null}
              className="max-w-64"
              data-testid="measure-min"
            />
          </fieldset>
          {errors[name] ? <p className="text-sm text-danger">{errors[name]}</p> : null}
        </div>
      )}
      {sentence ? (
        <p id={sentenceId} className="text-sm text-ink-muted" data-testid="measure-sentence">
          {sentence}
        </p>
      ) : null}
    </div>
  );
}
