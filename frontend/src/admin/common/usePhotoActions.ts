/**
 * Ausblenden / Einblenden with the undo toast, shared by live, manage and the user page.
 */
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { isApiError } from '@/api/client';
import type { AdminPhoto } from '@/api/types';
import { hiddenToast, msg, t } from '@/lib/messages.de';
import { showToast } from '@/ui/Toast';
import { photoLabel } from '../lib/labels';
import { setPhotoHidden } from '../store/actions';

export function errorText(err: unknown): string {
  return isApiError(err) ? err.message : msg.generic;
}

export function showError(err: unknown): void {
  showToast({ message: errorText(err), tone: 'error' });
}

function doneText(photo: AdminPhoto, hidden: boolean): string {
  return hidden ? hiddenToast(photoLabel(photo)) : `${photoLabel(photo)} eingeblendet`;
}

/** Toggle one photo; the toast offers "Rückgängig" (undo window instead of a question). */
export function useHideToggle(): {
  toggle: (photo: AdminPhoto, hidden?: boolean) => Promise<void>;
  busyId: string | null;
} {
  const qc = useQueryClient();
  const [busyId, setBusyId] = useState<string | null>(null);

  const toggle = async (photo: AdminPhoto, hidden = !photo.hidden) => {
    setBusyId(photo.id);
    try {
      const after = await setPhotoHidden(qc, photo, hidden);
      showToast({
        message: doneText(photo, hidden),
        tone: 'success',
        action: {
          label: t.undo,
          onAction: () => {
            setPhotoHidden(qc, after, !hidden).then(
              () => showToast({ message: doneText(photo, !hidden), tone: 'info' }),
              showError,
            );
          },
        },
      });
    } catch (err) {
      showError(err);
    } finally {
      setBusyId(null);
    }
  };
  return { toggle, busyId };
}
