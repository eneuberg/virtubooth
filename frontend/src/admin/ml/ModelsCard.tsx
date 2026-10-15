/**
 * "Modelle": the analysis worker (state, heartbeat, queue) and every analyzer with
 * what it does, its size, on/off, its settings and its numbers. Own requests; polls
 * every 5 s while on screen. Analyses are made once (N3): changes apply to new photos.
 */
import { useQueryClient } from '@tanstack/react-query';
import { Boxes, Save } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { formatDateTime } from '@/lib/format';
import { Badge } from '@/ui/Badge';
import { Button } from '@/ui/Button';
import { Spinner } from '@/ui/Spinner';
import { Switch } from '@/ui/Switch';
import { TextField } from '@/ui/TextField';
import { showToast } from '@/ui/Toast';
import { errorText, showError } from '../common/usePhotoActions';
import { setAnalyzer } from '../wall/api';
import { Card } from '../wall/fields';
import { useAnalysisStatus } from '../wall/hooks';
import { wk } from '../wall/keys';
import { ANALYZER_KIND_LABELS, WORKER_LABELS } from '../wall/labels';
import { countsText, lastBeatText, memoryText, processedText } from '../wall/text';
import type { Analyzer, AnalysisStatus, WorkerState } from '../wall/types';
import { parseDecimal, numberText } from '../wall/categories/spec';
import { ModelsSetup } from './ModelsSetup';
import { queueText, sizeText, statsText } from './text';

const WORKER_TONE: Record<WorkerState, 'ok' | 'amber' | 'neutral' | 'mark'> = {
  running: 'ok',
  starting: 'amber',
  off: 'neutral',
  stopped: 'neutral',
  crashed: 'mark',
};

/**
 * The worker's heartbeat: state, when it last reported, and (while it beats) how many
 * photos it did, its memory and the analyzers that failed to load.
 */
function WorkerStatus({ status }: { status: AnalysisStatus }) {
  const { worker, analyzers } = status;
  const titles = new Map(analyzers.map((a) => [a.name, a.title]));
  const loadErrors = Object.entries(worker.load_errors);
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
            <dt className="text-ink-muted">Seit Serverstart verarbeitet</dt>
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
        <dt className="text-ink-muted">Fotos</dt>
        <dd className="tabular" data-testid="wall-counts">
          {countsText(status.counts)}
        </dd>
      </dl>
      <p className="text-sm font-semibold tabular" data-testid="ml-queue">
        {queueText(status.queue)}
      </p>
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

function stepDigits(step: number): number {
  const text = String(step);
  return text.includes('.') ? (text.split('.')[1]?.length ?? 0) : 0;
}

/** The analyzer's number settings with „Speichern“ (own request). */
function AnalyzerSettings({ analyzer }: { analyzer: Analyzer }) {
  const qc = useQueryClient();
  const current = analyzer.settings ?? {};
  const [texts, setTexts] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      analyzer.settings_schema.map((f) => [
        f.key,
        current[f.key] === undefined ? '' : numberText(current[f.key] ?? 0),
      ]),
    ),
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const next: Record<string, number> = {};
    const errs: Record<string, string> = {};
    for (const f of analyzer.settings_schema) {
      const n = parseDecimal(texts[f.key] ?? '');
      if (!Number.isFinite(n) || n < f.min || n > f.max) {
        errs[f.key] = `Bitte eine Zahl von ${numberText(f.min)} bis ${numberText(f.max)}.`;
      } else next[f.key] = Number(n.toFixed(stepDigits(f.step)));
    }
    setErrors(errs);
    setFormError(null);
    if (Object.keys(errs).length > 0) return;
    setBusy(true);
    try {
      qc.setQueryData(
        wk.analysis,
        await setAnalyzer(analyzer.name, { enabled: analyzer.enabled, settings: next }),
      );
      showToast({ message: `${analyzer.title}: gespeichert. Gilt für neue Fotos.`, tone: 'success' });
    } catch (err) {
      setFormError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      noValidate
      onSubmit={(e) => void submit(e)}
      className="grid gap-2 sm:grid-cols-[repeat(auto-fill,minmax(9rem,1fr))] sm:items-start"
      data-testid="ml-analyzer-settings"
    >
      {analyzer.settings_schema.map((f) => (
        <TextField
          key={f.key}
          label={f.title}
          size="sm"
          inputMode="decimal"
          value={texts[f.key] ?? ''}
          onChange={(v) => {
            setTexts((t) => ({ ...t, [f.key]: v }));
            setErrors((x) => ({ ...x, [f.key]: '' }));
          }}
          description={`${numberText(f.min)} bis ${numberText(f.max)}`}
          errorMessage={errors[f.key] || null}
        />
      ))}
      <Button
        type="submit"
        size="sm"
        variant="secondary"
        icon={Save}
        isPending={busy}
        className="self-start sm:mt-6.5"
      >
        Speichern
      </Button>
      {formError ? (
        <p role="alert" className="text-sm text-danger sm:col-span-full">
          {formError}
        </p>
      ) : null}
    </form>
  );
}

function AnalyzerRow({
  analyzer: a,
  busy,
  onToggle,
}: {
  analyzer: Analyzer;
  busy: boolean;
  onToggle: (on: boolean) => void;
}) {
  return (
    <li data-analyzer={a.name} className="grid gap-1.5 border-b border-line py-3">
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <div className="grid min-w-0 flex-1 gap-0.5">
          <p className="flex flex-wrap items-center gap-2 font-semibold">
            {a.title}
            <Badge tone={a.kind === 'ml' ? 'new' : 'neutral'}>{ANALYZER_KIND_LABELS[a.kind]}</Badge>
            {a.enabled && !a.available ? <Badge tone="amber">läuft nicht</Badge> : null}
            {a.size_mb !== null ? (
              <span className="text-sm font-normal text-ink-muted tabular" data-testid="ml-analyzer-size">
                {sizeText(a.size_mb)}
              </span>
            ) : null}
          </p>
          {a.description ? <p className="text-sm text-ink-muted">{a.description}</p> : null}
        </div>
        <Switch
          isSelected={a.enabled}
          isPending={busy}
          // the image values always run (the server never switches them off). Every other
          // switch works both ways, also while the analyzer can't run (models missing): it
          // is the stored wish, the reason below says why it does not run yet
          isDisabled={a.kind === 'basic'}
          onChange={onToggle}
          aria-label={`${a.title} an`}
        >
          {a.enabled ? 'an' : 'aus'}
        </Switch>
      </div>
      {a.reason || a.kind === 'basic' ? (
        <p className="text-xs text-ink-muted" data-testid="ml-analyzer-reason">
          {a.reason ?? 'Läuft immer.'}
        </p>
      ) : null}
      <p
        className="text-xs text-ink-muted tabular"
        data-testid="ml-analyzer-stats"
        title="Seit dem Start des Servers"
      >
        {statsText(a.stats)}
      </p>
      {a.settings_schema.length > 0 && a.settings ? <AnalyzerSettings analyzer={a} /> : null}
    </li>
  );
}

export function ModelsCard() {
  const qc = useQueryClient();
  const status = useAnalysisStatus();
  const [busy, setBusy] = useState<string | null>(null);

  const toggle = async (a: Analyzer, enabled: boolean) => {
    setBusy(a.name);
    try {
      qc.setQueryData<AnalysisStatus>(wk.analysis, await setAnalyzer(a.name, { enabled }));
      void qc.invalidateQueries({ queryKey: wk.categories });
      void qc.invalidateQueries({ queryKey: wk.values });
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
  };

  const data = status.data;
  return (
    <Card
      id="modelle"
      title="Modelle"
      icon={Boxes}
      intro="Die Analyse läuft auf diesem Server, ein Foto nach dem anderen und nur, wenn gerade Luft ist."
    >
      {status.isPending ? (
        <Spinner label="Lädt…" />
      ) : !data ? (
        <p className="text-sm text-danger">{errorText(status.error)}</p>
      ) : (
        <>
          <ModelsSetup status={data} />
          <WorkerStatus status={data} />
          <ul className="grid border-t border-line" aria-label="Modelle">
            {data.analyzers.map((a) => (
              <AnalyzerRow
                key={a.name}
                analyzer={a}
                busy={busy === a.name}
                onToggle={(on) => void toggle(a, on)}
              />
            ))}
          </ul>
          <p className="text-sm text-ink-muted" data-testid="ml-freeze-note">
            Analysen werden einmal gemacht und danach nicht mehr verändert. Änderungen gelten für neue Fotos.
          </p>
        </>
      )}
    </Card>
  );
}
