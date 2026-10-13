/**
 * „Neuer QR-Code“: Ziel, Notiz and the token (generated, or an own one: a printed
 * code's link pasted from the phone). The server picks the number and the animal.
 */
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Button } from '@/ui/Button';
import { Sheet } from '@/ui/Sheet';
import { showToast } from '@/ui/Toast';
import { showError } from '../common/usePhotoActions';
import { createCode, fieldErrors, type Activities, type AdminCode, type FieldErrors } from './api';
import { readTokenInput, targetFromLinkNote } from './codeUrl';
import { NoteField, TargetSelect } from './fields';
import { TokenChoice, type TokenMode } from './TokenChoice';

export function NewCodeSheet({
  isOpen,
  onOpenChange,
  activities,
  partyOrigin,
  onCreated,
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  activities: Activities;
  partyOrigin: string;
  onCreated: (code: AdminCode) => void;
}) {
  const qc = useQueryClient();
  const [target, setTarget] = useState('');
  const [note, setNote] = useState('');
  const [mode, setMode] = useState<TokenMode>('generate');
  const [input, setInput] = useState('');
  const [targetNote, setTargetNote] = useState<string | null>(null);
  const [tried, setTried] = useState(false);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [busy, setBusy] = useState(false);

  const pasted = mode === 'own' ? readTokenInput(input, { partyOrigin, activities: activities.byId }) : null;

  const reset = () => {
    setTarget('');
    setNote('');
    setMode('generate');
    setInput('');
    setTargetNote(null);
    setTried(false);
    setErrors({});
  };

  const changeInput = (value: string) => {
    setInput(value);
    setErrors((e) => ({ ...e, token: undefined }));
    const read = readTokenInput(value, { partyOrigin, activities: activities.byId });
    if (read.target !== null && read.target !== target) {
      setTarget(read.target);
      setTargetNote(targetFromLinkNote(read.target, activities.byId));
    } else if (read.target === null) {
      setTargetNote(null);
    }
  };

  const submit = async () => {
    setTried(true);
    if (pasted?.error) return;
    setBusy(true);
    setErrors({});
    try {
      const code = await createCode(qc, { token: pasted?.token ?? null, target, note: note.trim() });
      showToast({ message: `QR-Code ${code.name} angelegt.`, tone: 'success' });
      reset();
      onOpenChange(false);
      onCreated(code);
    } catch (err) {
      const fields = fieldErrors(err);
      if (fields) setErrors(fields);
      else showError(err);
    } finally {
      setBusy(false);
    }
  };

  const looksComplete = input.trim().length >= 16 || /[/?:#=]/.test(input);
  return (
    <Sheet
      isOpen={isOpen}
      onOpenChange={(open) => {
        if (busy) return;
        if (!open) reset();
        onOpenChange(open);
      }}
      title="Neuer QR-Code"
      description="Nummer und Tiername vergibt die App."
      size="md"
      data-testid="new-code-sheet"
      footer={
        <Button
          variant="primary"
          block
          isPending={busy}
          onPress={() => void submit()}
          data-testid="code-create"
        >
          Anlegen
        </Button>
      }
    >
      <form
        className="grid gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <TargetSelect
          value={target}
          onChange={(value) => {
            setTarget(value);
            setTargetNote(null);
          }}
          activities={activities}
        />
        <NoteField
          value={note}
          onChange={(value) => {
            setNote(value);
            setErrors((e) => ({ ...e, note: undefined }));
          }}
          errorMessage={errors.note ?? null}
        />
        <TokenChoice
          mode={mode}
          onModeChange={(value) => {
            setMode(value);
            setErrors((e) => ({ ...e, token: undefined }));
          }}
          input={input}
          onInputChange={changeInput}
          pasted={pasted}
          showError={tried || looksComplete}
          serverError={errors.token ?? null}
          targetNote={targetNote}
        />
      </form>
    </Sheet>
  );
}
