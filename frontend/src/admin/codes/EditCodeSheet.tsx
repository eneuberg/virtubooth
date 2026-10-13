/** „Bearbeiten“: a code's Ziel and Notiz (number, name and token stay). */
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Button } from '@/ui/Button';
import { Sheet } from '@/ui/Sheet';
import { showToast } from '@/ui/Toast';
import { showError } from '../common/usePhotoActions';
import { editCode, fieldErrors, type Activities, type AdminCode } from './api';
import { NoteField, TargetSelect } from './fields';

export function EditCodeSheet({
  code,
  isOpen,
  onOpenChange,
  activities,
}: {
  code: AdminCode;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  activities: Activities;
}) {
  const qc = useQueryClient();
  const [target, setTarget] = useState(code.target);
  const [note, setNote] = useState(code.note);
  const [noteError, setNoteError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // a fresh form each time it opens, from the code as it is now
  const [openedFor, setOpenedFor] = useState<boolean>(false);
  if (isOpen !== openedFor) {
    setOpenedFor(isOpen);
    if (isOpen) {
      setTarget(code.target);
      setNote(code.note);
      setNoteError(null);
    }
  }

  const submit = async () => {
    setBusy(true);
    setNoteError(null);
    try {
      await editCode(qc, code.id, { target, note: note.trim() });
      showToast({ message: `${code.name} gespeichert.`, tone: 'success' });
      onOpenChange(false);
    } catch (err) {
      const fields = fieldErrors(err);
      if (fields?.note) setNoteError(fields.note);
      else showError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet
      isOpen={isOpen}
      onOpenChange={(open) => !busy && onOpenChange(open)}
      title={`${code.name} bearbeiten`}
      size="md"
      data-testid="edit-code-sheet"
      footer={
        <Button
          variant="primary"
          block
          isPending={busy}
          onPress={() => void submit()}
          data-testid="code-save"
        >
          Speichern
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
        <TargetSelect value={target} onChange={setTarget} activities={activities} />
        <NoteField
          value={note}
          onChange={(value) => {
            setNote(value);
            setNoteError(null);
          }}
          errorMessage={noteError}
        />
      </form>
    </Sheet>
  );
}
