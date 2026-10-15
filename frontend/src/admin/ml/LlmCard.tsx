/**
 * "Claude (KI-Dienst)": the external AI's master switch (off: nothing leaves the
 * server), provider and model, and its two parts, each with its own switch, state,
 * last error and cost: „Objekterkennung mit KI“ (at upload) and „Eigenschaften
 * abfragen“ (the poll with its interval, the verdicts and „Jetzt abfragen“); the local
 * detector's switch; all in one PUT /llm/config. Then the API key (set / replace /
 * delete / test; it is never shown or prefilled, after saving only „gesetzt“).
 */
import { useQueryClient } from '@tanstack/react-query';
import { KeyRound, RefreshCw, Save, ShieldCheck, Sparkles, Trash2 } from 'lucide-react';
import { useState, type FormEvent, type ReactNode } from 'react';
import { formatDateTime, formatRelative, formatTime } from '@/lib/format';
import { Badge } from '@/ui/Badge';
import { Button } from '@/ui/Button';
import { cx } from '@/ui/cx';
import { Checkbox } from '@/ui/Checkbox';
import { ConfirmDialog } from '@/ui/ConfirmDialog';
import { Select } from '@/ui/Select';
import { Switch } from '@/ui/Switch';
import { TextField } from '@/ui/TextField';
import { showToast } from '@/ui/Toast';
import { errorText, showError } from '../common/usePhotoActions';
import { Card } from '../wall/fields';
import { wk } from '../wall/keys';
import { clearLlmKey, pollNow, saveLlmConfig, setLlmKey, testLlmKey } from './api';
import {
  DETECTION_LABELS,
  keyStatusText,
  parseMinutes,
  partOffReason,
  partUsage,
  POLLER_LABELS,
  type LlmPart,
} from './forms';
import { modelText, usdText } from './text';
import type { LlmConfig, LlmKeyState, LlmStatus, PollerState } from './types';

const POLLER_TONE: Record<PollerState, 'neutral' | 'ok' | 'amber' | 'mark'> = {
  off: 'neutral',
  idle: 'ok',
  running: 'amber',
  blocked: 'mark',
};

/** The fields this card edits (the budget is the Budget card's). */
interface Fields {
  enabled: boolean;
  provider: string;
  model: string;
  poll: boolean;
  minutes: string;
  local: boolean;
  external: boolean;
}

function fieldsOf(c: LlmConfig): Fields {
  return {
    enabled: c.enabled,
    provider: c.provider,
    model: c.model,
    poll: c.poll,
    minutes: String(Math.round(c.poll_interval_s / 60)),
    local: c.detect.local,
    external: c.detect.external,
  };
}

const sameFields = (a: Fields, b: Fields) => JSON.stringify(a) === JSON.stringify(b);

function KeyBlock({ status }: { status: LlmStatus }) {
  const qc = useQueryClient();
  const key = status.key;
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'save' | 'test' | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [clearError, setClearError] = useState<string | null>(null);
  const open = !key.set || editing;

  const store = (state: LlmKeyState) =>
    qc.setQueryData<LlmStatus>(wk.llm, (old) => (old ? { ...old, key: state } : old));

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const k = value.trim();
    if (!k || /\s/.test(k) || k.length > 400) {
      setError('Bitte den Schlüssel ohne Leerzeichen einfügen (höchstens 400 Zeichen).');
      return;
    }
    setBusy('save');
    setError(null);
    try {
      store(await setLlmKey(status.config.provider, k));
      setValue('');
      setEditing(false);
      showToast({ message: 'API-Schlüssel gespeichert.', tone: 'success' });
      void qc.invalidateQueries({ queryKey: wk.llm });
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  };

  const test = async () => {
    setBusy('test');
    try {
      const out = await testLlmKey();
      showToast({
        message: out.message || (out.ok ? 'Der Schlüssel funktioniert.' : 'Fehlgeschlagen.'),
        tone: out.ok ? 'success' : 'error',
      });
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="grid gap-2 border-t border-line pt-3" data-testid="ml-key">
      <p className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-semibold">API-Schlüssel</span>
        <Badge tone={key.set && key.valid ? 'ok' : 'mark'} icon={key.set ? ShieldCheck : undefined}>
          <span data-testid="ml-key-state">{keyStatusText(key)}</span>
        </Badge>
        {key.set && key.set_at ? (
          <span className="text-ink-muted">
            seit <time dateTime={key.set_at}>{formatDateTime(key.set_at)}</time>
          </span>
        ) : null}
      </p>
      {open ? (
        <form
          noValidate
          onSubmit={(e) => void submit(e)}
          className="grid gap-2 @md:grid-cols-[minmax(0,1fr)_auto] @md:items-start"
          autoComplete="off"
        >
          <TextField
            label={key.set ? 'Neuer API-Schlüssel' : 'API-Schlüssel'}
            // the status line above already says „API-Schlüssel“
            hideLabel={!key.set}
            type="password"
            autoComplete="new-password"
            spellCheck="false"
            size="sm"
            value={value}
            onChange={(v) => {
              setValue(v);
              setError(null);
            }}
            errorMessage={error}
            description="Wird verschlüsselt gespeichert und nie wieder angezeigt."
            data-testid="ml-key-input"
          />
          {/* level with the input: below the label when it is shown */}
          <div className={cx('flex flex-wrap gap-2', key.set && '@md:mt-6.5')}>
            <Button
              type="submit"
              size="sm"
              variant="secondary"
              isPending={busy === 'save'}
              data-testid="ml-key-save"
            >
              Speichern
            </Button>
            {key.set ? (
              <Button
                size="sm"
                variant="quiet"
                onPress={() => {
                  setEditing(false);
                  setValue('');
                  setError(null);
                }}
              >
                Abbrechen
              </Button>
            ) : null}
          </div>
        </form>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button
            size="xs"
            variant="secondary"
            icon={KeyRound}
            onPress={() => setEditing(true)}
            data-testid="ml-key-replace"
          >
            Schlüssel ersetzen
          </Button>
          <Button
            size="xs"
            variant="secondary"
            icon={ShieldCheck}
            isPending={busy === 'test'}
            onPress={() => void test()}
            data-testid="ml-key-test"
          >
            Testen
          </Button>
          <Button
            size="xs"
            variant="danger-outline"
            icon={Trash2}
            onPress={() => {
              setClearError(null);
              setConfirm(true);
            }}
            data-testid="ml-key-clear"
          >
            Schlüssel löschen…
          </Button>
        </div>
      )}
      <ConfirmDialog
        isOpen={confirm}
        onOpenChange={setConfirm}
        title="API-Schlüssel löschen?"
        confirmLabel="Schlüssel löschen"
        error={clearError}
        onConfirm={async () => {
          try {
            store(await clearLlmKey());
            showToast({ message: 'API-Schlüssel gelöscht. Die externe KI ist aus.', tone: 'success' });
          } catch (err) {
            setClearError(errorText(err));
            throw err;
          }
        }}
        data-testid="confirm"
      >
        <p>Ohne Schlüssel schickt der Server nichts mehr an den KI-Dienst.</p>
      </ConfirmDialog>
    </div>
  );
}

/** „Kosten bisher: 0,40 $ · 4 Aufrufe“ */
function CostText({ status, part }: { status: LlmStatus; part: LlmPart }) {
  const { calls, usd } = partUsage(status, part);
  return (
    <span className="text-ink-muted tabular" data-testid={`ml-${part}-cost`}>
      bisher {usdText(usd)} · {calls} {calls === 1 ? 'Aufruf' : 'Aufrufe'}
    </span>
  );
}

/** A part's state badge: off (and why) or what it does now. */
function PartState({
  status,
  part,
  state,
  partOn,
}: {
  status: LlmStatus;
  part: LlmPart;
  state: PollerState;
  partOn: boolean;
}) {
  const why = state === 'off' ? partOffReason(status, partOn) : null;
  const labels = part === 'poll' ? POLLER_LABELS : DETECTION_LABELS;
  return (
    <span
      className="inline-flex flex-wrap items-center gap-2"
      data-testid={`ml-${part}-state`}
      data-state={state}
    >
      <Badge tone={POLLER_TONE[state]}>{labels[state]}</Badge>
      {why && why !== 'ausgeschaltet' ? <span className="text-ink-muted">{why}</span> : null}
    </span>
  );
}

function DetectionLine({ status }: { status: LlmStatus }) {
  const { detection } = status;
  return (
    <div className="grid gap-1">
      <dl
        className="grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-5 gap-y-1 text-sm"
        data-testid="ml-detection"
      >
        <dt className="text-ink-muted">Stand</dt>
        <dd className="flex flex-wrap items-center gap-2">
          <PartState
            status={status}
            part="detection"
            state={detection.state}
            partOn={status.config.detect.external}
          />
          {detection.last_run_at ? (
            <span className="text-ink-muted">zuletzt {formatRelative(detection.last_run_at)}</span>
          ) : null}
        </dd>
        <dt className="text-ink-muted">Fotos</dt>
        <dd className="tabular">
          {detection.done} fertig · {detection.pending} warten · {detection.failed} fehlgeschlagen
        </dd>
        <dt className="text-ink-muted">Kosten</dt>
        <dd>
          <CostText status={status} part="detection" />
        </dd>
      </dl>
      {detection.last_error ? (
        <p className="text-sm text-danger" data-testid="ml-detection-error">
          {detection.last_error}
        </p>
      ) : null}
    </div>
  );
}

function PollerLine({ status }: { status: LlmStatus }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const { poller } = status;
  const now = async () => {
    setBusy(true);
    try {
      const out = await pollNow();
      showToast({
        message: out.started ? 'Die Abfrage läuft.' : (out.reason ?? 'Gerade nicht möglich.'),
        tone: out.started ? 'success' : 'error',
      });
      void qc.invalidateQueries({ queryKey: wk.llm });
    } catch (err) {
      showError(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="grid gap-2">
      <dl
        className="grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-5 gap-y-1 text-sm"
        data-testid="ml-poller"
      >
        <dt className="text-ink-muted">Stand</dt>
        <dd className="flex flex-wrap items-center gap-2">
          <PartState status={status} part="poll" state={poller.state} partOn={status.config.poll} />
          {poller.last_poll_at ? (
            <span className="text-ink-muted">zuletzt {formatRelative(poller.last_poll_at)}</span>
          ) : null}
          {poller.next_poll_at ? (
            <span className="text-ink-muted">nächste um {formatTime(poller.next_poll_at)}</span>
          ) : null}
        </dd>
        <dt className="text-ink-muted">Kosten</dt>
        <dd>
          <CostText status={status} part="poll" />
        </dd>
      </dl>
      {poller.last_error ? (
        <p className="text-sm text-danger" data-testid="ml-poller-error">
          {poller.last_error}
        </p>
      ) : null}
      <Button
        size="xs"
        variant="secondary"
        icon={RefreshCw}
        isPending={busy}
        isDisabled={!status.config.enabled || !status.config.poll || !status.key.set}
        onPress={() => void now()}
        className="justify-self-start"
        data-testid="ml-poll-now"
      >
        Jetzt abfragen
      </Button>
    </div>
  );
}

/** One part of the external AI: its switch, settings and state, set off by a rule. */
function Part({ children, testId }: { children: ReactNode; testId: string }) {
  return (
    <section className="grid gap-2 border-t border-line pt-3" data-testid={testId}>
      {children}
    </section>
  );
}

export function LlmCard({ status }: { status: LlmStatus }) {
  const qc = useQueryClient();
  const base = fieldsOf(status.config);
  const [edits, setEdits] = useState<Fields | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const f = edits ?? base;
  const dirty = edits !== null && !sameFields(edits, base);
  const minutes = parseMinutes(f.minutes);
  const set = (change: Partial<Fields>) => {
    setError(null);
    setEdits({ ...f, ...change });
  };

  const save = async () => {
    if (minutes === null) return;
    setBusy(true);
    try {
      const out = await saveLlmConfig({
        ...status.config,
        enabled: f.enabled,
        provider: f.provider,
        model: f.model,
        poll: f.poll,
        poll_interval_s: minutes * 60,
        detect: { local: f.local, external: f.external },
      });
      qc.setQueryData(wk.llm, out);
      setEdits(null);
      showToast({ message: 'KI-Einstellungen gespeichert.', tone: 'success' });
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const provider = status.providers.find((p) => p.id === f.provider);
  // each provider has its own models (the server refuses a model of another one)
  const models = status.models.filter((m) => m.provider === f.provider);
  const pickProvider = (id: string) => {
    const keep = status.models.some((m) => m.provider === id && m.id === f.model);
    set({
      provider: id,
      model: keep ? f.model : (status.models.find((m) => m.provider === id)?.id ?? f.model),
    });
  };
  return (
    <Card
      id="claude"
      title="Claude (KI-Dienst)"
      icon={Sparkles}
      intro="Optional: ein externer KI-Dienst erkennt zusätzlich Dinge und bewertet Eigenschaften für die Live-Wall. Fotos von Gästen mit „Keine Weitergabe an externe KI“ gehen nie hinaus."
    >
      <Switch isSelected={f.enabled} onChange={(on) => set({ enabled: on })} data-testid="ml-llm-enabled">
        Externe KI verwenden
      </Switch>
      <p className="-mt-2 text-xs text-ink-muted">
        Aus: der Server schickt nichts an den KI-Dienst, egal was unten eingeschaltet ist.
      </p>
      <div className="grid gap-3 @md:grid-cols-2">
        <Select
          label="Anbieter"
          size="sm"
          options={status.providers.map((p) => ({ id: p.id, label: p.eu ? `${p.title} (EU)` : p.title }))}
          value={f.provider}
          onChange={pickProvider}
          data-testid="ml-llm-provider"
        />
        <Select
          label="Modell"
          size="sm"
          options={models.map((m) => ({ id: m.id, label: modelText(m) }))}
          value={f.model}
          onChange={(model) => set({ model })}
          data-testid="ml-llm-model"
        />
      </div>
      {provider && !provider.available && provider.reason ? (
        <p className="text-sm text-danger">{provider.reason}</p>
      ) : null}
      <Part testId="ml-part-detection">
        <Switch
          isSelected={f.external}
          onChange={(external) => set({ external })}
          data-testid="ml-detect-external"
        >
          Objekterkennung mit KI (beim Hochladen)
        </Switch>
        <p className="text-xs text-ink-muted">
          Jedes neue Foto geht verkleinert an die KI, sie listet die Objekte mit Rahmen. Ihre Liste bleibt für
          sich sichtbar und wird mit der des lokalen Modells zusammengeführt (Doppelte nur einmal).
        </p>
        <DetectionLine status={status} />
      </Part>
      <Part testId="ml-part-poll">
        <Switch isSelected={f.poll} onChange={(poll) => set({ poll })} data-testid="ml-llm-poll">
          Eigenschaften abfragen
        </Switch>
        <TextField
          label="Abfrage alle … Minuten"
          size="sm"
          inputMode="numeric"
          value={f.minutes}
          onChange={(text) => set({ minutes: text })}
          errorMessage={minutes === null ? 'Bitte eine ganze Zahl von 1 bis 60.' : null}
          description="So oft bewertet die KI die Eigenschaften (nur Text: die zusammengeführte Objektliste) neu und schreibt die Urteile."
          className="max-w-xs"
          data-testid="ml-llm-minutes"
        />
        <PollerLine status={status} />
      </Part>
      <fieldset className="grid gap-0 border-t border-line pt-3">
        <legend className="sr-only">Lokale Erkennung</legend>
        <Checkbox isSelected={f.local} onChange={(local) => set({ local })} data-testid="ml-detect-local">
          Lokale Objekterkennung beim Hochladen
        </Checkbox>
        <p className="text-xs text-ink-muted">Läuft auf dem Server, kostet nichts, schickt nichts hinaus.</p>
      </fieldset>
      {dirty ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="primary"
            icon={Save}
            isPending={busy}
            isDisabled={minutes === null}
            onPress={() => void save()}
            data-testid="ml-llm-save"
          >
            Speichern
          </Button>
          <Button size="sm" variant="quiet" onPress={() => setEdits(null)}>
            Verwerfen
          </Button>
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
      <KeyBlock status={status} />
    </Card>
  );
}
