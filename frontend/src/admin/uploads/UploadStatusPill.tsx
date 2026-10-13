import { useUploadPause, useUploadStop } from '../store/hooks';
import { StatusPill } from '@/ui/StatusPill';
import { openUploadSheet } from './sheetStore';
import { pillLabel, pillState, uploadSummary } from './uploadState';

/**
 * The upload state at a glance (an / neue pausiert / gestoppt), in every admin header.
 * Opens the upload controls sheet.
 */
export function UploadStatusPill({ long = false, className }: { long?: boolean; className?: string }) {
  const { data: stop } = useUploadStop();
  const { data: pause } = useUploadPause();
  const state = pillState(stop, pause);
  return (
    <StatusPill
      state={state ?? 'on'}
      label={pillLabel(state, long)}
      aria-label={`Hochladen steuern. ${uploadSummary(stop, pause)}`}
      aria-haspopup="dialog"
      data-testid="uploads-chip"
      data-upload-state={state ?? 'loading'}
      onPress={openUploadSheet}
      className={className}
    />
  );
}
