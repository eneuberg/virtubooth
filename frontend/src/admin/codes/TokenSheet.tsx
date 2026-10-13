/**
 * „Token ändern“: a new token for a code (generated, or an own one, e.g. to take over
 * an already printed code: its link pasted). A pasted link to an activity sets the
 * code's Ziel too, as in the link.
 */
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Button } from '@/ui/Button';
import { Sheet } from '@/ui/Sheet';
import { showToast } from '@/ui/Toast';
import { showError } from '../common/usePhotoActions';
import { editCode, fieldErrors, setCodeToken, type Activities, type AdminCode } from './api';
import { readTokenInput, targetFromLinkNote } from './codeUrl';
import { TokenChoice, type TokenMode } from './TokenChoice';

export function TokenSheet({
  code,
  isOpen,
  onOpenChange,
  activities,
  partyOrigin,
}: {
  code: AdminCode;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  activities: Activities;
  partyOrigin: string;
}) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<TokenMode>('generate');
  const [input, setInput] = useState('');
  const [tried, setTried] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const pasted = mode === 'own' ? readTokenInput(input, { partyOrigin, activities: activities.byId }) : null;
  const linkTarget = pasted?.target ?? null;
  const newTarget = linkTarget !== null && linkTarget !== code.target ? linkTarget : null;

  const reset = () => {
    setMode('generate');
    setInput('');
    setTried(false);
    setServerError(null);
  };

  const submit = async () => {
    setTried(true);
    if (pasted?.error) return;
    setBusy(true);
    setServerError(null);
    try {
      await setCodeToken(qc, code.id, pasted?.token ?? null);
      if (newTarget !== null) await editCode(qc, code.id, { target: newTarget });
      showToast({ message: `Token von ${code.name} geändert.`, tone: 'success' });
      reset();
      onOpenChange(false);
    } catch (err) {
      const fields = fieldErrors(err);
      if (fields?.token) setServerError(fields.token);
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
      title={`Token ändern: ${code.name}`}
      size="md"
      data-testid="token-sheet"
      footer={
        <Button
          variant="primary"
          block
          isPending={busy}
          onPress={() => void submit()}
          data-testid="token-save"
        >
          Token ändern
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
        <p className="text-md">
          Der bisherige Code (gedruckt oder geteilt) funktioniert danach nicht mehr. Wer darüber schon
          beigetreten ist, bleibt dabei.
        </p>
        <TokenChoice
          mode={mode}
          onModeChange={(value) => {
            setMode(value);
            setServerError(null);
          }}
          input={input}
          onInputChange={(value) => {
            setInput(value);
            setServerError(null);
          }}
          pasted={pasted}
          showError={tried || looksComplete}
          serverError={serverError}
          targetNote={newTarget !== null ? targetFromLinkNote(newTarget, activities.byId) : null}
        />
      </form>
    </Sheet>
  );
}
