/**
 * The top of „Modelle“: what the server lacks for the ML analyzers and how to get it.
 * Without the ML packages (image built with VB_ML=0) a downloaded model would not
 * help, so it says how to rebuild; with them and models missing, „Modelle
 * herunterladen“ fetches them (the server picks the files, SHA256-checked) into the
 * data volume, with progress and errors from the polled status.
 */
import { useQueryClient } from '@tanstack/react-query';
import { Download } from 'lucide-react';
import { useState } from 'react';
import { formatTime } from '@/lib/format';
import { Button } from '@/ui/Button';
import { errorText } from '../common/usePhotoActions';
import { downloadModels } from '../wall/api';
import { wk } from '../wall/keys';
import type { AnalysisStatus } from '../wall/types';
import { downloadProgressText, sizeText } from './text';

export function ModelsSetup({ status }: { status: AnalysisStatus }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { models } = status;
  const { download } = models;

  if (!models.ml) {
    return (
      <div
        className="rounded-md grid gap-1.5 border border-line-strong p-3 text-sm"
        data-testid="ml-packages-missing"
      >
        <p className="font-semibold">KI-Pakete fehlen in diesem Server-Image</p>
        <p>
          Das Docker-Image wurde ohne die KI-Pakete (MediaPipe, ONNX Runtime, OpenCV) gebaut. Darum laufen nur
          die Bildwerte (Helligkeit, Farbe, Schärfe); Gesichter, Gesten, Objekte und Altersgruppen nicht.
          Modelle herunterladen hilft hier nicht.
        </p>
        <p>
          So geht es: In Coolify bei virtubooth unter „Environment Variables“ <code>VB_ML</code> auf{' '}
          <code>1</code> setzen (oder den Eintrag löschen, 1 ist Standard) und „Redeploy“ drücken. Ohne
          Coolify das Image mit <code>docker build --build-arg VB_ML=1</code> bauen. Danach hier „Modelle
          herunterladen“.
        </p>
      </div>
    );
  }

  if (download.state === 'running') {
    const fill = download.total_bytes > 0 ? Math.min(1, download.done_bytes / download.total_bytes) : 0;
    return (
      <div className="grid gap-1.5 text-sm" data-testid="ml-models-download">
        <p className="flex flex-wrap justify-between gap-2">
          <span className="font-semibold">Modelle werden heruntergeladen…</span>
          <span className="text-ink-muted tabular" data-testid="ml-models-progress">
            {downloadProgressText(download)}
          </span>
        </p>
        <div aria-hidden="true" className="h-2 overflow-hidden rounded-full bg-surface-sunk">
          <div className="h-full rounded-full bg-ink" style={{ width: `${(fill * 100).toFixed(1)}%` }} />
        </div>
        {download.current ? <p className="text-xs text-ink-muted">Gerade: {download.current}</p> : null}
      </div>
    );
  }

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      qc.setQueryData<AnalysisStatus>(wk.analysis, await downloadModels());
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  if (models.missing.length > 0) {
    const failed = download.state === 'failed' ? download.error : null;
    return (
      <div
        className="rounded-md grid gap-2 border border-line-strong p-3 text-sm"
        data-testid="ml-models-missing"
      >
        <p className="font-semibold">
          {models.missing.length === 1 ? 'Ein Modell fehlt' : `${models.missing.length} Modelle fehlen`} (
          {sizeText(models.missing_mb)})
        </p>
        <p>
          Ohne sie laufen nur die Bildwerte. Sie werden einmal vom Server heruntergeladen, geprüft und im
          Daten-Volume gespeichert; ein Redeploy behält sie.
        </p>
        {failed || error ? (
          <p role="alert" className="text-danger" data-testid="ml-models-error">
            {failed ?? error}
          </p>
        ) : null}
        <Button
          variant="primary"
          size="sm"
          icon={Download}
          isPending={busy}
          isDisabled={!models.can_download}
          onPress={() => void start()}
          className="justify-self-start"
          data-testid="ml-models-download-button"
        >
          Modelle herunterladen
        </Button>
      </div>
    );
  }

  if (download.state === 'done') {
    return (
      <p className="text-sm text-ink-muted" data-testid="ml-models-done">
        Modelle heruntergeladen{download.finished_at ? ` (${formatTime(download.finished_at)} Uhr)` : ''}. Die
        Analyse nimmt sie ab dem nächsten Foto.
      </p>
    );
  }
  return null;
}
