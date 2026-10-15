/**
 * The "Du" sheet, opened from the guest pass: who you are at this party (the name the
 * others see, the random name and why it is random), your „Anzeigename“ (empty: the
 * default, i.e. your Instagram name, else the random name), your Instagram name (edit,
 * remove), „Meine Fotos nicht automatisch auswerten“ while the Live-Wall analysis
 * runs, „Keine Weitergabe an externe KI“ while the host has an external AI on, and
 * whether you can upload, in plain words. Test id `guest-sheet`.
 */
import { useId, useRef, useState, type FormEvent } from 'react';
import type { GuestUser } from '@/api/types';
import { isApiError } from '@/api/errors';
import { msg, t } from '@/lib/messages.de';
import { Button } from '@/ui/Button';
import { Sheet } from '@/ui/Sheet';
import { Switch } from '@/ui/Switch';
import { TextField } from '@/ui/TextField';
import { showToast } from '@/ui/Toast';
import { ANALYSIS_OPT_OUT, DISPLAY_NAME, EXTERNAL_AI_OPT_OUT, defaultName } from '../identity';
import {
  setAnalysisOptOut,
  setDisplayName,
  setExternalAiOptOut,
  setInstagram,
  useJoinText,
  useSession,
} from '../session';
import { useGuestStatus } from '../status';
import { HandleField } from './HandleField';
import { StatusDot } from './StatusSlot';

export interface GuestSheetProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}

function errorOf(err: unknown): string {
  return isApiError(err) ? err.message : msg.generic;
}

/** „Anzeigename“: empty = the default (shown as the placeholder). Saved with its own button. */
function DisplayNameForm({ user, onDone }: { user: GuestUser; onDone: () => void }) {
  const saved = user.display_name ?? '';
  const [value, setValue] = useState(saved);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    if (value.trim() === saved) {
      onDone();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const next = await setDisplayName(value);
      onDone();
      showToast({
        tone: 'success',
        message: next.display_name ? `Du heißt jetzt ${next.shown_name}` : `Wieder ${next.shown_name}`,
      });
    } catch (err) {
      setError(errorOf(err));
      inputRef.current?.focus();
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-3" data-testid="display-name-form">
      <TextField
        label={DISPLAY_NAME.label}
        description={DISPLAY_NAME.help}
        name="display-name"
        autoComplete="nickname"
        placeholder={defaultName(user)}
        maxLength={40}
        value={value}
        onChange={(next) => {
          setValue(next);
          setError(null);
        }}
        errorMessage={error}
        inputRef={inputRef}
        data-testid="display-name"
      />
      <div className="flex flex-wrap gap-2">
        <Button
          type="submit"
          variant="primary"
          size="md"
          isPending={busy}
          pendingLabel={t.sending}
          data-testid="display-name-save"
        >
          Name speichern
        </Button>
      </div>
    </form>
  );
}

function InstagramForm({ user, onDone }: { user: GuestUser; onDone: () => void }) {
  const saved = user.instagram ?? '';
  const [value, setValue] = useState(saved);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'save' | 'remove' | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

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
      setError(errorOf(err));
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

  return (
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
  );
}

function Body({ onDone }: { onDone: () => void }) {
  const session = useSession();
  const status = useGuestStatus();
  const joinText = useJoinText();
  const user = session.status === 'ready' || session.status === 'banned' ? session.user : null;
  const titleId = useId();
  if (!user) return null;

  const uploadText =
    status.kind === 'ok' || status.kind === 'offline' || status.kind === 'waiting'
      ? 'Du kannst Fotos machen und hochladen.'
      : status.text;
  const uploadTone = status.kind === 'offline' || status.kind === 'waiting' ? 'ok' : status.tone;

  return (
    <div className="grid gap-6">
      <p className="text-ink-muted">
        Deinen Namen <span translate="no">„{user.name}“</span> hat die Seite zufällig für dich ausgesucht. So
        bleibst du anonym, und die Gastgeber sehen trotzdem, welche Fotos zusammengehören.
      </p>

      <DisplayNameForm user={user} onDone={onDone} />
      <section className="border-t border-line pt-4">
        <InstagramForm user={user} onDone={onDone} />
      </section>

      {joinText?.analysis ? (
        <OptOutSwitch
          isSelected={user.analysis_opt_out}
          label={ANALYSIS_OPT_OUT.label}
          help={ANALYSIS_OPT_OUT.help}
          save={setAnalysisOptOut}
          on="Deine Fotos werden nicht mehr ausgewertet"
          off="Deine Fotos werden wieder ausgewertet"
          testid="guest-analysis-opt-out"
        />
      ) : null}
      {joinText?.external_ai ? (
        <OptOutSwitch
          isSelected={user.ai_opt_out}
          label={EXTERNAL_AI_OPT_OUT.label}
          help={EXTERNAL_AI_OPT_OUT.help}
          save={setExternalAiOptOut}
          on="Nichts von dir geht an eine externe KI"
          off="Deine Fotos dürfen wieder an die externe KI"
          testid="guest-ai-opt-out"
        />
      ) : null}

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

/** An opt-out switch that saves at once (analysis, external AI). */
function OptOutSwitch({
  isSelected,
  label,
  help,
  save,
  on,
  off,
  testid,
}: {
  isSelected: boolean;
  label: string;
  help: string;
  save: (optOut: boolean) => Promise<unknown>;
  on: string;
  off: string;
  testid: string;
}) {
  const [busy, setBusy] = useState(false);
  const change = async (next: boolean) => {
    setBusy(true);
    try {
      await save(next);
      showToast({ tone: 'success', message: next ? on : off });
    } catch (err) {
      showToast({ tone: 'error', message: errorOf(err) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="grid gap-1.5 border-t border-line pt-4">
      <Switch
        isSelected={isSelected}
        isPending={busy}
        onChange={(next) => void change(next)}
        description={help}
        data-testid={testid}
      >
        {label}
      </Switch>
    </section>
  );
}

export function GuestSheet({ isOpen, onOpenChange }: GuestSheetProps) {
  const session = useSession();
  const name = session.status === 'ready' || session.status === 'banned' ? session.user.shown_name : '';
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
