/**
 * Building blocks of the Live-Wall section: a card, a whole-number field and a colour
 * field that keep what is typed while the draft holds the parsed value.
 */
import type { LucideIcon } from 'lucide-react';
import { useId, useState, type ReactNode } from 'react';
import { cx } from '@/ui/cx';
import { TextField } from '@/ui/TextField';
import { normalizeHex } from './draft';

export function Card({
  id,
  title,
  icon: Icon,
  intro,
  children,
  className,
}: {
  id: string;
  title: string;
  icon: LucideIcon;
  intro?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const headingId = `wall-${id}-title`;
  return (
    <section
      aria-labelledby={headingId}
      data-testid={`wall-card-${id}`}
      className={cx('grid min-w-0 content-start gap-4 border-t-2 border-ink pt-3', className)}
    >
      <div className="grid gap-1">
        <h2 id={headingId} className="flex items-center gap-2 text-lg font-bold">
          <Icon aria-hidden="true" className="size-5" strokeWidth={2} />
          {title}
        </h2>
        {intro ? <p className="max-w-prose text-sm text-ink-muted">{intro}</p> : null}
      </div>
      {children}
    </section>
  );
}

function parseWhole(text: string): number {
  const t = text.trim();
  return /^\d{1,7}$/.test(t) ? Number(t) : Number.NaN;
}

const same = (a: number, b: number) => a === b || (Number.isNaN(a) && Number.isNaN(b));

export function NumberField({
  label,
  value,
  onChange,
  error,
  description,
  className,
  testid,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  error?: string | undefined;
  description?: ReactNode;
  className?: string;
  testid?: string;
}) {
  const [text, setText] = useState(String(value));
  // what was typed, unless the value changed from outside (Verwerfen, a reset)
  const shown = same(parseWhole(text), value) ? text : Number.isNaN(value) ? '' : String(value);
  return (
    <TextField
      label={label}
      size="sm"
      inputMode="numeric"
      value={shown}
      onChange={(next) => {
        setText(next);
        onChange(parseWhole(next));
      }}
      errorMessage={error ?? null}
      description={description}
      className={className}
      data-testid={testid}
    />
  );
}

export function ColorField({
  label,
  value,
  onChange,
  error,
  testid,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  error?: string | undefined;
  testid?: string;
}) {
  const [text, setText] = useState(value);
  const shown = (normalizeHex(text) ?? text) === value ? text : value;
  const pickerId = useId();
  const valid = normalizeHex(value);
  return (
    <div className="flex items-start gap-2" data-testid={testid}>
      <input
        id={pickerId}
        type="color"
        aria-label={`${label} wählen`}
        value={valid ?? '#000000'}
        onChange={(e) => onChange(e.target.value.toLowerCase())}
        className="mt-6.5 h-10 w-12 shrink-0 cursor-pointer rounded-control border border-field bg-field-bg p-1"
      />
      <TextField
        label={label}
        size="sm"
        value={shown}
        maxLength={7}
        spellCheck="false"
        onChange={(next) => {
          setText(next);
          onChange(normalizeHex(next) ?? next);
        }}
        errorMessage={error ?? null}
        className="min-w-0 flex-1"
      />
    </div>
  );
}
