/**
 * „Eventname“: the name guests see (Start, the join sheet's title, the Fotobox's party
 * frame, the posters). Stored on the server; „Zurück zu …“ brings VB_PARTY_NAME back.
 */
import { useQueryClient } from '@tanstack/react-query';
import { PartyPopper, RotateCcw } from 'lucide-react';
import { useRef, useState, type FormEvent } from 'react';
import { quoted } from '@/lib/messages.de';
import { Button } from '@/ui/Button';
import { TextField } from '@/ui/TextField';
import { showToast } from '@/ui/Toast';
import { errorText } from '../common/usePhotoActions';
import { saveEventName, type EventSettings } from './api';
import { SettingsCard } from './SettingsCard';

export const EVENT_NAME_MAX = 60;
const INVALID = 'Der Name braucht 1 bis 60 Zeichen.';

type Busy = 'save' | 'reset' | null;

export function EventNameCard({ event }: { event: EventSettings }) {
  const qc = useQueryClient();
  // null: not edited, the field shows the current name (also when another admin changes it)
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const input = useRef<HTMLInputElement>(null);
  const value = draft ?? event.name;

  const save = async (name: string | null, which: Exclude<Busy, null>, done: string) => {
    if (busy) return;
    setBusy(which);
    setError(null);
    try {
      await saveEventName(qc, name);
      setDraft(null);
      showToast({ message: done, tone: 'success' });
    } catch (err) {
      setError(errorText(err));
      input.current?.focus();
    } finally {
      setBusy(null);
    }
  };

  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!value.trim()) {
      // blank would reset on the server: that is what the reset button is for
      setError(INVALID);
      input.current?.focus();
      return;
    }
    void save(value, 'save', 'Eventname gespeichert.');
  };

  return (
    <SettingsCard title="Eventname" icon={PartyPopper} testid="settings-event">
      <form noValidate onSubmit={submit} className="grid gap-3">
        <TextField
          label="Name des Events"
          name="event-name"
          description="Steht auf der Startseite, im Beitritts-Fenster („Willkommen bei …!“), im Party-Rahmen der Fotobox und auf den Plakaten. Gäste sehen den neuen Namen spätestens nach einer Minute."
          maxLength={EVENT_NAME_MAX}
          autoComplete="off"
          value={value}
          onChange={(next) => {
            setDraft(next);
            setError(null);
          }}
          errorMessage={error}
          inputRef={input}
          data-testid="event-name"
        />
        <div className="flex flex-wrap gap-2">
          <Button
            type="submit"
            variant="primary"
            size="sm"
            isPending={busy === 'save'}
            pendingLabel="Speichert…"
            data-testid="event-name-save"
          >
            Speichern
          </Button>
          {event.custom ? (
            <Button
              variant="secondary"
              size="sm"
              icon={RotateCcw}
              isPending={busy === 'reset'}
              pendingLabel="Setzt zurück…"
              onPress={() => void save(null, 'reset', 'Eventname zurückgesetzt.')}
              // a long VB_PARTY_NAME wraps instead of leaving the card
              className="h-auto min-h-11 py-2 text-left whitespace-normal"
              data-testid="event-name-reset"
            >
              Zurück zu {quoted(event.default_name)}
            </Button>
          ) : null}
        </div>
      </form>
    </SettingsCard>
  );
}
