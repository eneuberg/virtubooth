/**
 * „Öffentliche Adresse“: where the QR codes, the posters and the Live-Wall's code point
 * to, e.g. https://party.example.com. Empty = the address the admin is open on (or
 * VB_PUBLIC_BASE_URL). Saving checks it on the server (`/healthz` with a probe only this
 * server can answer); „Jetzt prüfen“ repeats that. A failed check is a warning, never a
 * block: the server may not reach its own public address (hairpin NAT).
 */
import { useQueryClient } from '@tanstack/react-query';
import { CircleAlert, CircleCheck, Globe, RefreshCw } from 'lucide-react';
import { useRef, useState, type FormEvent } from 'react';
import { Button } from '@/ui/Button';
import { cx } from '@/ui/cx';
import { TextField } from '@/ui/TextField';
import { showToast } from '@/ui/Toast';
import { errorText, showError } from '../common/usePhotoActions';
import { ADDRESS_HINT, addressStatus } from './address';
import { checkPublicAddress, savePublicAddress, type PublicAddress } from './api';
import { SettingsCard } from './SettingsCard';

const MAX = 300;
type Busy = 'save' | 'check' | null;

export function AddressStatus({ state }: { state: PublicAddress }) {
  const { text, detail, tone } = addressStatus(state.check);
  const Icon = tone === 'ok' ? CircleCheck : tone === 'warn' ? CircleAlert : Globe;
  return (
    <p
      role="status"
      data-testid="address-status"
      data-status={state.check.status}
      className={cx(
        'grid grid-cols-[auto_1fr] items-start gap-x-2 gap-y-0.5 text-sm',
        tone === 'ok' && 'text-ok',
        tone === 'warn' && 'text-mark',
        tone === 'muted' && 'text-ink-muted',
      )}
    >
      <Icon aria-hidden="true" className="mt-0.5 size-4" strokeWidth={2.25} />
      <span className="font-semibold">{text}</span>
      {detail ? <span className="col-start-2 text-xs text-ink-muted">{detail}</span> : null}
    </p>
  );
}

export function PublicAddressCard({ state }: { state: PublicAddress }) {
  const qc = useQueryClient();
  // null: not edited, the field shows the stored address
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const input = useRef<HTMLInputElement>(null);
  const value = draft ?? state.address ?? '';

  const save = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (busy) return;
    setBusy('save');
    setError(null);
    try {
      const next = await savePublicAddress(qc, value.trim() || null);
      setDraft(null);
      const fine = next.check.status === 'ok' || next.check.status === 'auto';
      showToast(
        fine
          ? { message: 'Adresse gespeichert.', tone: 'success' }
          : { message: 'Adresse gespeichert, aber nicht erreichbar.', tone: 'info' },
      );
    } catch (err) {
      setError(errorText(err));
      input.current?.focus();
    } finally {
      setBusy(null);
    }
  };

  const check = async () => {
    if (busy) return;
    setBusy('check');
    try {
      await checkPublicAddress(qc);
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
  };

  return (
    <SettingsCard title="Öffentliche Adresse" icon={Globe} testid="settings-address">
      <form noValidate onSubmit={(e) => void save(e)} className="grid gap-3">
        <TextField
          label="Adresse für QR-Codes und Plakate"
          name="public-address"
          type="url"
          inputMode="url"
          autoComplete="off"
          spellCheck="false"
          placeholder="https://party.example.com…"
          description={
            state.source === 'env' && !draft
              ? `${ADDRESS_HINT}. Gerade gilt VB_PUBLIC_BASE_URL: ${state.effective ?? ''}`
              : ADDRESS_HINT
          }
          maxLength={MAX}
          value={value}
          onChange={(next) => {
            setDraft(next);
            setError(null);
          }}
          errorMessage={error}
          inputRef={input}
          data-testid="public-address"
        />
        <AddressStatus state={state} />
        <div className="flex flex-wrap gap-2">
          <Button
            type="submit"
            variant="primary"
            size="sm"
            isPending={busy === 'save'}
            pendingLabel="Speichert und prüft…"
            data-testid="public-address-save"
          >
            Speichern
          </Button>
          {state.check.status === 'auto' ? null : (
            <Button
              variant="secondary"
              size="sm"
              icon={RefreshCw}
              isPending={busy === 'check'}
              pendingLabel="Prüft…"
              onPress={() => void check()}
              data-testid="public-address-check"
            >
              Jetzt prüfen
            </Button>
          )}
        </div>
      </form>
    </SettingsCard>
  );
}
