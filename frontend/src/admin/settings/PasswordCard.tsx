/**
 * „Admin-Passwort“: change it with the current one. Afterwards every other admin device
 * is logged out; this one stays. A forgotten password is reset on the server (CLI).
 */
import { useQueryClient } from '@tanstack/react-query';
import { KeyRound } from 'lucide-react';
import { useRef, useState, type FormEvent, type RefObject } from 'react';
import { formatDateTime } from '@/lib/format';
import { Button } from '@/ui/Button';
import { HelpDisclosure } from '@/ui/HelpDisclosure';
import { TextField } from '@/ui/TextField';
import { showToast } from '@/ui/Toast';
import { changePassword, type PasswordState } from './api';
import {
  changedText,
  checkPasswordForm,
  placeServerError,
  type PasswordErrors,
  type PasswordField,
} from './rules';
import { SettingsCard } from './SettingsCard';

const MAX = 256;

function statusText(state: PasswordState): string {
  if (state.source === 'admin' && state.changed_at) {
    return `Hier geändert am ${formatDateTime(state.changed_at)}. VB_ADMIN_PASSWORD gilt nicht mehr.`;
  }
  if (state.source === 'admin') return 'Hier geändert. VB_ADMIN_PASSWORD gilt nicht mehr.';
  return 'Gerade gilt das Passwort aus VB_ADMIN_PASSWORD.';
}

export function PasswordCard({ state }: { state: PasswordState }) {
  const qc = useQueryClient();
  const [values, setValues] = useState<Record<PasswordField, string>>({ current: '', next: '', repeat: '' });
  const [errors, setErrors] = useState<PasswordErrors>({});
  const [pending, setPending] = useState(false);
  const currentRef = useRef<HTMLInputElement>(null);
  const nextRef = useRef<HTMLInputElement>(null);
  const repeatRef = useRef<HTMLInputElement>(null);
  const refs: Record<PasswordField, RefObject<HTMLInputElement | null>> = {
    current: currentRef,
    next: nextRef,
    repeat: repeatRef,
  };

  const focusFirstError = (found: PasswordErrors) => {
    const field = (['current', 'next', 'repeat'] as const).find((f) => found[f]);
    if (field) refs[field].current?.select();
  };

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (pending) return;
    const found = checkPasswordForm(values.current, values.next, values.repeat);
    setErrors(found);
    if (Object.keys(found).length) {
      focusFirstError(found);
      return;
    }
    setPending(true);
    try {
      const ended = await changePassword(qc, values.current, values.next);
      setValues({ current: '', next: '', repeat: '' });
      showToast({ message: changedText(ended), tone: 'success' });
    } catch (err) {
      const placed = placeServerError(err);
      setErrors(placed);
      focusFirstError(placed);
    } finally {
      setPending(false);
    }
  };

  const field = (name: PasswordField, label: string, autoComplete: string, description?: string) => (
    <TextField
      label={label}
      name={name === 'current' ? 'current-password' : `new-password-${name}`}
      type="password"
      autoComplete={autoComplete}
      maxLength={MAX}
      value={values[name]}
      onChange={(value) => {
        setValues((v) => ({ ...v, [name]: value }));
        setErrors((e) => ({ ...e, [name]: undefined, form: undefined }));
      }}
      errorMessage={errors[name] ?? null}
      inputRef={refs[name]}
      {...(description ? { description } : {})}
    />
  );

  return (
    <SettingsCard title="Admin-Passwort" icon={KeyRound} testid="settings-password">
      <p className="text-sm text-ink-muted" data-testid="password-source">
        {statusText(state)}
      </p>
      <form noValidate onSubmit={(e) => void submit(e)} className="grid gap-3">
        {field('current', 'Aktuelles Passwort', 'current-password')}
        {field(
          'next',
          'Neues Passwort',
          'new-password',
          'Mindestens 12 Zeichen, besser 16 oder mehr. Danach sind alle anderen Geräte abgemeldet; dieses bleibt angemeldet.',
        )}
        {field('repeat', 'Neues Passwort wiederholen', 'new-password')}
        {errors.form ? (
          <p role="alert" className="text-sm font-semibold text-danger" data-testid="password-error">
            {errors.form}
          </p>
        ) : null}
        <Button
          type="submit"
          variant="primary"
          size="sm"
          isPending={pending}
          pendingLabel="Prüfe…"
          className="justify-self-start"
          data-testid="password-save"
        >
          Passwort ändern
        </Button>
      </form>
      <HelpDisclosure summary="Passwort vergessen?">
        <p>
          Auf dem Server:{' '}
          <code translate="no" className="text-xs break-all text-ink">
            docker compose exec app virtubooth reset-admin-password --from-env
          </code>
          , dann gilt wieder VB_ADMIN_PASSWORD. Ohne{' '}
          <code translate="no" className="text-xs text-ink">
            --from-env
          </code>{' '}
          fragt der Befehl nach einem neuen Passwort. Danach sind alle Geräte abgemeldet.
        </p>
      </HelpDisclosure>
    </SettingsCard>
  );
}
