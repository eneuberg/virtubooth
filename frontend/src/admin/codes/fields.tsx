/** The fields the code sheets share: „Ziel“ and „Notiz“. */
import { Select } from '@/ui/Select';
import { TextField } from '@/ui/TextField';
import { optionTarget, targetOption, type Activities } from './api';
import { NOTE_MAX } from './codeUrl';

export function TargetSelect({
  value,
  onChange,
  activities,
}: {
  value: string;
  onChange: (target: string) => void;
  activities: Activities;
}) {
  const known = value === '' || activities.byId.has(value);
  return (
    <div className="grid gap-1.5">
      <Select
        label="Ziel"
        options={activities.options}
        value={known ? targetOption(value) : null}
        placeholder="Ziel nicht verfügbar"
        onChange={(option) => onChange(optionTarget(option))}
        data-testid="code-target"
      />
      <p className="text-xs text-ink-muted">Wohin der Code führt. Start zeigt alle Aktivitäten.</p>
    </div>
  );
}

export function NoteField({
  value,
  onChange,
  errorMessage,
}: {
  value: string;
  onChange: (note: string) => void;
  errorMessage: string | null;
}) {
  return (
    <TextField
      label="Notiz (freiwillig)"
      placeholder="z. B. Eingang, Bar"
      maxLength={NOTE_MAX}
      value={value}
      onChange={onChange}
      errorMessage={errorMessage}
      autoComplete="off"
      data-testid="code-note"
    />
  );
}
