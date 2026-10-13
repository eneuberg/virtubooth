import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import type { AdminPhoto } from '@/api/types';
import { quoted } from '@/lib/messages.de';
import { ConfirmDialog } from '@/ui/ConfirmDialog';
import { showToast } from '@/ui/Toast';
import { photoCount, photoLabel } from '../lib/labels';
import { deletePhotos } from '../store/actions';
import { errorText } from './usePhotoActions';

/**
 * "… endgültig löschen?" before any photo is deleted (manage and the user page; the
 * live screen has no delete). Focus starts on "Abbrechen".
 */
export function DeletePhotosDialog({
  photos,
  onClose,
  onDeleted,
}: {
  /** the photos to delete; empty: closed */
  photos: ReadonlyArray<AdminPhoto>;
  onClose: () => void;
  onDeleted: (ids: string[]) => void;
}) {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const one = photos.length === 1 ? photos[0] : undefined;
  const title = one
    ? `${quoted(photoLabel(one))} endgültig löschen?`
    : `${photoCount(photos.length)} endgültig löschen?`;

  return (
    <ConfirmDialog
      isOpen={photos.length > 0}
      onOpenChange={(open) => {
        if (!open) {
          setError(null);
          onClose();
        }
      }}
      title={title}
      confirmLabel={one ? 'Endgültig löschen' : `${photoCount(photos.length)} endgültig löschen`}
      error={error}
      data-testid="confirm"
      onConfirm={async () => {
        setError(null);
        try {
          const gone = await deletePhotos(qc, photos);
          showToast({
            message: gone.length === 1 ? 'Foto gelöscht' : `${photoCount(gone.length)} gelöscht`,
            tone: 'success',
          });
          onDeleted(gone);
        } catch (err) {
          setError(errorText(err));
          throw err;
        }
      }}
    >
      <p>
        Die Bilddateien werden sofort vom Server gelöscht. Das lässt sich nicht rückgängig machen. Zum
        Verbergen reicht „Ausblenden“.
      </p>
    </ConfirmDialog>
  );
}
