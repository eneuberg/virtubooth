/**
 * "Analyse": the analysis worker, its counters, the analyzers (own requests, not the
 * draft) and re-running failed or all photos. Polls every 5 s while on screen.
 */
import { useQueryClient } from '@tanstack/react-query';
import { RefreshCw, ScanFace } from 'lucide-react';
import { useState } from 'react';
import { Badge } from '@/ui/Badge';
import { Button } from '@/ui/Button';
import { ConfirmDialog } from '@/ui/ConfirmDialog';
import { Spinner } from '@/ui/Spinner';
import { Switch } from '@/ui/Switch';
import { showToast } from '@/ui/Toast';
import { errorText, showError } from '../common/usePhotoActions';
import { rerunAnalysis, setDisabledAnalyzers } from './api';
import { toggleIn } from './draft';
import { Card } from './fields';
import { useAnalysisStatus } from './hooks';
import { wk } from './keys';
import { ANALYZER_KIND_LABELS, WORKER_LABELS } from './labels';
import { countsText } from './text';
import type { AnalysisStatus, WorkerState } from './types';

const WORKER_TONE: Record<WorkerState, 'ok' | 'amber' | 'neutral' | 'mark'> = {
  running: 'ok',
  starting: 'amber',
  off: 'neutral',
  stopped: 'neutral',
  crashed: 'mark',
};

function queuedText(n: number): string {
  return n === 1 ? '1 Foto wird neu analysiert.' : `${n} Fotos werden neu analysiert.`;
}

export function AnalysisCard() {
  const qc = useQueryClient();
  const status = useAnalysisStatus();
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmAll, setConfirmAll] = useState(false);
  const [allError, setAllError] = useState<string | null>(null);

  const toggleAnalyzer = async (name: string, enabled: boolean) => {
    const current = status.data;
    if (!current) return;
    const disabled = toggleIn(
      current.analyzers.filter((a) => !a.enabled).map((a) => a.name),
      name,
      !enabled,
    );
    setBusy(name);
    try {
      qc.setQueryData<AnalysisStatus>(wk.analysis, await setDisabledAnalyzers(disabled));
      void qc.invalidateQueries({ queryKey: wk.config });
      void qc.invalidateQueries({ queryKey: wk.categories });
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
  };

  const rerun = async (scope: 'failed' | 'all') => {
    const { queued } = await rerunAnalysis(scope);
    showToast({ message: queuedText(queued), tone: 'success' });
    void qc.invalidateQueries({ queryKey: wk.analysis });
  };

  const rerunFailed = async () => {
    setBusy('rerun-failed');
    try {
      await rerun('failed');
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
  };

  const data = status.data;
  return (
    <Card
      id="analyse"
      title="Analyse"
      icon={ScanFace}
      intro="Die Analyse läuft auf diesem Server. Keine Daten verlassen ihn."
    >
      {status.isPending ? (
        <Spinner label="Lädt…" />
      ) : !data ? (
        <p className="text-sm text-danger">{errorText(status.error)}</p>
      ) : (
        <>
          <div className="grid gap-1" data-testid="wall-worker">
            <p className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-semibold">Analyse</span>
              <Badge tone={WORKER_TONE[data.worker.state]}>{WORKER_LABELS[data.worker.state]}</Badge>
              {data.worker.ml ? null : <span className="text-ink-muted">nur Basis</span>}
            </p>
            {data.worker.message ? <p className="text-sm text-ink-muted">{data.worker.message}</p> : null}
            <p className="text-sm tabular" data-testid="wall-counts">
              {countsText(data.counts)}
            </p>
          </div>
          <ul className="grid border-t border-line" aria-label="Auswertungen">
            {data.analyzers.map((a) => (
              <li key={a.name} data-analyzer={a.name} className="grid gap-1 border-b border-line py-2">
                <Switch
                  isSelected={a.enabled}
                  isPending={busy === a.name}
                  // the image values always run (the server never switches them off)
                  isDisabled={a.kind === 'basic' || (!a.available && !a.enabled)}
                  onChange={(on) => void toggleAnalyzer(a.name, on)}
                  description={a.reason ?? (a.kind === 'basic' ? 'Läuft immer.' : undefined)}
                >
                  <span className="inline-flex flex-wrap items-center gap-2">
                    {a.title}
                    <Badge tone={a.kind === 'ml' ? 'new' : 'neutral'}>{ANALYZER_KIND_LABELS[a.kind]}</Badge>
                  </span>
                </Switch>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-2">
            <Button
              size="xs"
              variant="secondary"
              icon={RefreshCw}
              isPending={busy === 'rerun-failed'}
              isDisabled={data.counts.failed === 0}
              onPress={() => void rerunFailed()}
              data-testid="wall-rerun-failed"
            >
              Fehlgeschlagene neu analysieren
            </Button>
            <Button
              size="xs"
              variant="secondary"
              onPress={() => {
                setAllError(null);
                setConfirmAll(true);
              }}
              data-testid="wall-rerun-all"
            >
              Alle neu analysieren…
            </Button>
          </div>
        </>
      )}
      <ConfirmDialog
        isOpen={confirmAll}
        onOpenChange={setConfirmAll}
        title="Alle Fotos neu analysieren?"
        confirmLabel="Alle neu analysieren"
        tone="neutral"
        error={allError}
        onConfirm={async () => {
          try {
            await rerun('all');
          } catch (err) {
            setAllError(errorText(err));
            throw err;
          }
        }}
        data-testid="confirm"
      >
        <p>Jedes Foto kommt noch einmal dran. Das dauert eine Weile und lastet den Server aus.</p>
      </ConfirmDialog>
    </Card>
  );
}
