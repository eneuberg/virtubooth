/**
 * The "Du" sheet, opened from the guest pass: who you are at this party (the random
 * name and why it is random), your Instagram name (edit, remove), „Meine Fotos nicht
 * automatisch auswerten“ while the Live-Wall analysis runs, and whether you can upload,
 * in plain words. Test id `guest-sheet`.
 */
import { useId, useRef, useState, type FormEvent } from 'react';
import { isApiError } from '@/api/errors';
import { msg, t } from '@/lib/messages.de';
import { Button } from '@/ui/Button';
import { Sheet } from '@/ui/Sheet';
import { Switch } from '@/ui/Switch';
import { showToast } from '@/ui/Toast';
import { ANALYSIS_OPT_OUT } from '../identity';
import { setAnalysisOptOut, setInstagram, useJoinText, useSession } from '../session';
import { useGuestStatus } from '../status';
import { HandleField } from './HandleField';
import { StatusDot } from './StatusSlot';

export interface GuestSheetProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}

function Body({ onDone }: { onDone: () => void }) {
  const session = useSession();
  const status = useGuestStatus();
  const joinText = useJoinText();
  const user = session.status === 'ready' || session.status === 'banned' ? session.user : null;
  const saved = user?.instagram ?? '';
  const [value, setValue] = useState(saved);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'save' | 'remove' | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const titleId = useId();
  if (!user) return null;

  const run = async (kind: 'save' | 'remove', handle: string | null) => {
    setBusy(kind);
    setError(null);
    try {
      const next = await setInstagram(handle);
      onDone();
      showToast({
        tone: 'success',
        message: next.instagram ? `Gespeichert: @${next.instagram}` : 'Instagram-Name entfernt',
      });
    } catch (err) {
      setError(isApiError(err) ? err.message : msg.generic);
      inputRef.current?.focus();
    } finally {
      setBusy(null);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    if (value.trim() === saved) {
      onDone();
      return;
    }
    void run('save', value);
  };

  const uploadText =
    status.kind === 'ok' || status.kind === 'offline' || status.kind === 'waiting'
      ? 'Du kannst Fotos machen und hochladen.'
      : status.text;
  const uploadTone = status.kind === 'offline' || status.kind === 'waiting' ? 'ok' : status.tone;

  return (
    <div className="grid gap-6">
      <p className="text-ink-muted">
        Den Namen hat die Seite zufällig für dich ausgesucht. So bleibst du anonym, und die Gastgeber sehen
        trotzdem, welche Fotos zusammengehören.
      </p>

      <form onSubmit={submit} noValidate className="grid gap-3">
        <HandleField
          label={t.instagramName}
          description="Dann können die Gastgeber dich markieren, wenn sie ein Foto von dir posten."
          value={value}
          onChange={(next) => {
            setValue(next);
            setError(null);
          }}
          errorMessage={error}
          inputRef={inputRef}
        />
        <div className="flex flex-wrap gap-2">
          <Button
            type="submit"
            variant="primary"
            size="md"
            isPending={busy === 'save'}
            pendingLabel={t.sending}
            isDisabled={busy === 'remove'}
          >
            {t.save}
          </Button>
          {saved ? (
            <Button
              variant="quiet"
              size="md"
              isPending={busy === 'remove'}
              isDisabled={busy !== null}
              onPress={() => void run('remove', null)}
            >
              Entfernen
            </Button>
          ) : null}
        </div>
      </form>

      {joinText?.analysis ? <AnalysisSection optOut={user.analysis_opt_out} /> : null}

      <section aria-labelledby={titleId} className="grid gap-1.5 border-t border-line pt-4">
        <h3 id={titleId} className="text-sm font-semibold">
          {t.upload}
        </h3>
        <p className="flex items-baseline gap-2.5" data-testid="guest-upload-state">
          <StatusDot tone={uploadTone} className="translate-y-[-1px]" />
          <span>{uploadText}</span>
        </p>
      </section>
    </div>
  );
}

/** „Meine Fotos nicht automatisch auswerten“ (the Live-Wall's photo analysis): saved at once. */
function AnalysisSection({ optOut }: { optOut: boolean }) {
  const [busy, setBusy] = useState(false);
  const change = async (next: boolean) => {
    setBusy(true);
    try {
      await setAnalysisOptOut(next);
      showToast({
        tone: 'success',
        message: next ? 'Deine Fotos werden nicht mehr ausgewertet' : 'Deine Fotos werden wieder ausgewertet',
      });
    } catch (err) {
      showToast({ tone: 'error', message: isApiError(err) ? err.message : msg.generic });
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="grid gap-1.5 border-t border-line pt-4">
      <Switch
        isSelected={optOut}
        isPending={busy}
        onChange={(next) => void change(next)}
        description={ANALYSIS_OPT_OUT.help}
        data-testid="guest-analysis-opt-out"
      >
        {ANALYSIS_OPT_OUT.label}
      </Switch>
    </section>
  );
}

export function GuestSheet({ isOpen, onOpenChange }: GuestSheetProps) {
  const session = useSession();
  const name = session.status === 'ready' || session.status === 'banned' ? session.user.name : '';
  return (
    <Sheet
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title={<span translate="no">{name}</span>}
      description="Dein Name auf dieser Party"
      size="sm"
      data-testid="guest-sheet"
    >
      <Body onDone={() => onOpenChange(false)} />
    </Sheet>
  );
}
