/**
 * The category editor's inputs: a value picker grouped like GET /values (`group`),
 * an object-label combobox (known labels, or any typed one) and a multi-label chip
 * list. Styled like ui/Select and ui/TextField.
 */
import { Check, ChevronDown, X } from 'lucide-react';
import { useState } from 'react';
import {
  Button as AriaButton,
  ComboBox,
  Header,
  Input,
  Label,
  ListBox,
  ListBoxItem,
  ListBoxSection,
  Popover,
  Select,
  SelectValue,
} from 'react-aria-components';
import { cx } from '@/ui/cx';
import { useSurface } from '@/ui/Surface';
import type { LabelInfo } from '../types';
import { labelFor, type ValueChoice } from './spec';

const TRIGGER = cx(
  'flex h-10 min-w-0 cursor-pointer items-center gap-2 rounded-control border bg-field-bg pr-2.5 pl-3 text-left text-sm text-ink',
  'outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
  'hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-50',
);
const POPOVER =
  'max-h-80 min-w-(--trigger-width) overflow-auto rounded-control border border-line bg-surface-raised p-1 text-ink shadow-float outline-none entering:animate-fade-in exiting:animate-fade-out';
const ITEM =
  'flex min-h-10 cursor-pointer items-center gap-2 rounded-small px-3 text-sm outline-none hover:bg-surface-hover focus-visible:bg-surface-hover focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus selected:font-semibold disabled:cursor-not-allowed disabled:opacity-50';

function groupsOf(choices: readonly ValueChoice[]): Array<{ group: string; items: ValueChoice[] }> {
  const out: Array<{ group: string; items: ValueChoice[] }> = [];
  for (const c of choices) {
    const g = out.find((x) => x.group === c.group);
    if (g) g.items.push(c);
    else out.push({ group: c.group, items: [c] });
  }
  return out;
}

export function ValuePicker({
  label,
  choices,
  value,
  onChange,
  numericOnly = false,
  error,
  hideLabel = false,
  testid,
}: {
  label: string;
  choices: readonly ValueChoice[];
  value: string;
  onChange: (value: string) => void;
  /** sorting needs numbers: lists are left out */
  numericOnly?: boolean;
  error?: string | undefined;
  hideLabel?: boolean;
  testid?: string;
}) {
  const surface = useSurface();
  const list = numericOnly ? choices.filter((c) => c.kind !== 'labels') : choices;
  return (
    <Select
      selectedKey={value || null}
      onSelectionChange={(key) => {
        if (key !== null) onChange(String(key));
      }}
      placeholder="Wert wählen…"
      isInvalid={Boolean(error)}
      {...(hideLabel ? { 'aria-label': label } : {})}
      className="group grid min-w-0 content-start gap-1.5"
      data-testid={testid}
    >
      {hideLabel ? null : <Label className="text-sm font-semibold">{label}</Label>}
      <AriaButton className={cx(TRIGGER, error ? 'border-danger' : 'border-field')}>
        <SelectValue className="min-w-0 flex-1 truncate placeholder-shown:text-ink-muted" />
        <ChevronDown aria-hidden="true" className="size-4 shrink-0" strokeWidth={2.25} />
      </AriaButton>
      {error ? <span className="text-sm text-danger">{error}</span> : null}
      <Popover offset={6} data-surface={surface} className={POPOVER}>
        <ListBox className="outline-none">
          {groupsOf(list).map((g) => (
            <ListBoxSection key={g.group} className="pb-1">
              <Header className="px-3 pt-2 pb-1 text-xs font-bold text-ink-muted uppercase">{g.group}</Header>
              {g.items.map((c) => (
                <ListBoxItem key={c.id} id={c.id} textValue={c.title} className={ITEM} data-value={c.id}>
                  {({ isSelected }) => (
                    <>
                      <span className="min-w-0 flex-1 truncate">
                        {c.title}
                        {c.inactive ? <span className="text-ink-muted"> (inaktiv)</span> : null}
                        {!c.available ? <span className="text-ink-muted"> (gerade aus)</span> : null}
                      </span>
                      {isSelected ? (
                        <Check aria-hidden="true" className="size-4 shrink-0" strokeWidth={2.5} />
                      ) : null}
                    </>
                  )}
                </ListBoxItem>
              ))}
            </ListBoxSection>
          ))}
        </ListBox>
      </Popover>
    </Select>
  );
}

/** A short single choice without a visible label (the operator of a condition). */
export function PlainPicker<K extends string>({
  label,
  options,
  value,
  onChange,
  testid,
}: {
  /** the accessible name */
  label: string;
  options: ReadonlyArray<{ id: K; label: string }>;
  value: K;
  onChange: (value: K) => void;
  testid?: string;
}) {
  const surface = useSurface();
  return (
    <Select
      aria-label={label}
      selectedKey={value}
      onSelectionChange={(key) => {
        const hit = options.find((o) => o.id === key);
        if (hit) onChange(hit.id);
      }}
      className="group grid min-w-0 content-start"
      data-testid={testid}
    >
      <AriaButton className={cx(TRIGGER, 'border-field')}>
        <SelectValue className="min-w-0 flex-1 truncate" />
        <ChevronDown aria-hidden="true" className="size-4 shrink-0" strokeWidth={2.25} />
      </AriaButton>
      <Popover offset={6} data-surface={surface} className={POPOVER}>
        <ListBox className="outline-none" items={options}>
          {(o) => (
            <ListBoxItem id={o.id} textValue={o.label} className={ITEM}>
              {o.label}
            </ListBoxItem>
          )}
        </ListBox>
      </Popover>
    </Select>
  );
}

function labelText(labels: readonly LabelInfo[], label: string): string {
  return labels.find((l) => l.label === label)?.label_de ?? label;
}

/**
 * One object label: pick a known one or type any (English canonical or German name).
 * The input text is the combobox's own; a pick shows the German name.
 */
export function LabelPicker({
  label,
  labels,
  value,
  onChange,
  error,
  hideLabel = false,
  clearOnPick = false,
  testid,
}: {
  label: string;
  labels: readonly LabelInfo[];
  value: string;
  onChange: (label: string) => void;
  error?: string | undefined;
  hideLabel?: boolean;
  /** for adding to a list: empty again after a pick (Enter adds a typed label) */
  clearOnPick?: boolean;
  testid?: string;
}) {
  const surface = useSurface();
  // a fresh, empty combobox after each pick (clearOnPick)
  const [round, setRound] = useState(0);
  const [text, setText] = useState('');
  const known = labels.some((l) => l.label === value);
  const add = (picked: string) => {
    onChange(picked);
    setText('');
    setRound((r) => r + 1);
  };
  return (
    <ComboBox
      key={round}
      defaultInputValue={clearOnPick || !value ? '' : labelText(labels, value)}
      onInputChange={(t) => {
        setText(t);
        if (!clearOnPick) onChange(labelFor(labels, t));
      }}
      selectedKey={clearOnPick || !known ? null : value}
      onSelectionChange={(key) => {
        if (key === null) return;
        if (clearOnPick) add(String(key));
        else onChange(String(key));
      }}
      allowsCustomValue
      isInvalid={Boolean(error)}
      {...(hideLabel ? { 'aria-label': label } : {})}
      className="group grid min-w-0 content-start gap-1.5"
      data-testid={testid}
    >
      {hideLabel ? null : <Label className="text-sm font-semibold">{label}</Label>}
      <div className={cx(TRIGGER, 'cursor-text pr-1', error ? 'border-danger' : 'border-field')}>
        <Input
          className="h-full min-w-0 flex-1 bg-transparent text-md outline-none placeholder:text-ink-muted sm:text-sm"
          placeholder="Objekt…"
          onKeyDown={(e) => {
            if (clearOnPick && e.key === 'Enter' && text.trim()) add(labelFor(labels, text));
          }}
        />
        <AriaButton className="grid size-8 shrink-0 place-items-center rounded-small outline-none hover:bg-surface-hover">
          <ChevronDown aria-hidden="true" className="size-4" strokeWidth={2.25} />
        </AriaButton>
      </div>
      {error ? <span className="text-sm text-danger">{error}</span> : null}
      <Popover offset={6} data-surface={surface} className={POPOVER}>
        <ListBox className="outline-none" items={labels.map((l) => ({ ...l, id: l.label }))}>
          {(l) => (
            <ListBoxItem id={l.label} textValue={l.label_de} className={ITEM}>
              <span className="min-w-0 flex-1 truncate">{l.label_de}</span>
              <span className="text-xs text-ink-muted tabular">{l.count}</span>
            </ListBoxItem>
          )}
        </ListBox>
      </Popover>
    </ComboBox>
  );
}

/** Several labels as chips, with a picker to add one. */
export function LabelsPicker({
  label,
  labels,
  value,
  onChange,
  error,
  testid,
}: {
  label: string;
  labels: readonly LabelInfo[];
  value: readonly string[];
  onChange: (labels: string[]) => void;
  error?: string | undefined;
  testid?: string;
}) {
  return (
    <div className="grid min-w-0 gap-1.5" data-testid={testid}>
      {value.length > 0 ? (
        <ul className="flex flex-wrap gap-1" aria-label={label}>
          {value.map((l) => (
            <li
              key={l}
              className="inline-flex h-7 items-center gap-1 rounded-small bg-surface-sunk pl-2 text-xs font-semibold"
            >
              {labelText(labels, l)}
              <AriaButton
                aria-label={`${labelText(labels, l)} entfernen`}
                onPress={() => onChange(value.filter((x) => x !== l))}
                className="grid size-7 place-items-center rounded-small outline-none hover:bg-surface-hover focus-visible:outline-2 focus-visible:outline-focus"
              >
                <X aria-hidden="true" className="size-3.5" strokeWidth={2.5} />
              </AriaButton>
            </li>
          ))}
        </ul>
      ) : null}
      <LabelPicker
        label={label}
        hideLabel
        labels={labels.filter((l) => !value.includes(l.label))}
        value=""
        clearOnPick
        onChange={(l) => {
          if (l && !value.includes(l)) onChange([...value, l]);
        }}
        error={error}
      />
    </div>
  );
}
