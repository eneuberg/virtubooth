/**
 * "Analyse": the analysis worker, its counters, the analyzers (own requests, not the
 * draft) and re-running failed or all photos. Polls every 5 s while on screen.
 */
import { useQueryClient } from '@tanstack/react-query';
import { RefreshCw, ScanFace } from 'lucide-react';
import { useState } from 'react';
import { formatDateTime } from '@/lib/format';
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
import { countsText, lastBeatText, memoryText, processedText } from './text';
import type { AnalysisStatus, WorkerState } from './types';

const WORKER_TONE: Record<WorkerState, 'ok' | 'amber' | 'neutral' | 'mark'> = {
  running: 'ok',
  starting: 'amber',
  off: 'neutral',
  stopped: 'neutral',
  crashed: 'mark',
};

/**
 * The worker's heartbeat: state, when it last reported, and (once the API passes them
 * on) how many photos it did, its memory and the analyzers that failed to load.
 */
function WorkerStatus({
  worker,
  analyzers,
}: {
  worker: AnalysisStatus['worker'];
  analyzers: AnalysisStatus['analyzers'];
}) {
  const titles = new Map(analyzers.map((a) => [a.name, a.title]));
  const loadErrors = Object.entries(worker.load_errors ?? {});
  return (
    <div className="grid gap-2" data-testid="wall-worker">
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-5 gap-y-1.5 text-sm">
        <dt className="text-ink-muted">Status</dt>
        <dd className="flex flex-wrap items-center gap-2">
          <Badge tone={WORKER_TONE[worker.state]}>{WORKER_LABELS[worker.state]}</Badge>
          {worker.ml ? null : <span className="text-ink-muted">nur Basis</span>}
        </dd>
        <dt className="text-ink-muted">Zuletzt gemeldet</dt>
        <dd data-testid="wall-worker-beat">
          {worker.last_beat_at ? (
            <time dateTime={worker.last_beat_at} title={formatDateTime(worker.last_beat_at)}>
              {lastBeatText(worker.last_beat_at)}
            </time>
          ) : (
            lastBeatText(null)
          )}
        </dd>
        {typeof worker.processed === 'number' ? (
          <>
            <dt className="text-ink-muted">Verarbeitet</dt>
            <dd className="tabular" data-testid="wall-worker-processed">
              {processedText(worker.processed)}
            </dd>
          </>
        ) : null}
        {typeof worker.rss_mb === 'number' ? (
          <>
            <dt className="text-ink-muted">Speicher</dt>
            <dd className="tabular" data-testid="wall-worker-rss">
              {memoryText(worker.rss_mb)}
            </dd>
          </>
        ) : null}
      </dl>
      {worker.message ? <p className="text-sm text-ink-muted">{worker.message}</p> : null}
      {loadErrors.length > 0 ? (
        <div className="grid gap-1 text-sm" data-testid="wall-worker-load-errors">
          <p className="font-semibold text-danger">Nicht geladen:</p>
          <ul className="grid gap-0.5">
            {loadErrors.map(([name, error]) => (
              <li key={name} className="min-w-0 break-words">
                <span className="font-semibold">{titles.get(name) ?? name}</span>{' '}
                <span className="text-ink-muted">{error}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

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
          <WorkerStatus worker={data.worker} analyzers={data.analyzers} />
          <p className="text-sm tabular" data-testid="wall-counts">
            {countsText(data.counts)}
          </p>
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
