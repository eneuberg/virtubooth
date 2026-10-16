/**
 * "Eigenschaften": „Eigenschaften abfragen“ (the poll: its switch, interval, state, cost,
 * last error and „Jetzt abfragen“) and what the external AI rates per object at every
 * poll (coolness …). Name and prompt are fixed once created (N7): no edit. Each one has
 * the switch „aktiv“ (off: not polled any more, the scores stay on the photos and in the
 * categories) and „Löschen“: into the „Papierkorb“ below the list (not polled, hidden from
 * the category value pickers, scores kept) with „Wiederherstellen“ and „Endgültig löschen“
 * (after a confirmation: the property and its scores go, the name is free again).
 */
import { useQueryClient } from '@tanstack/react-query';
import { ArchiveRestore, Download, Plus, RefreshCw, Save, Tags, Trash2, Upload } from 'lucide-react';
import { useState, type FormEvent, type ReactNode } from 'react';
import { FileTrigger } from 'react-aria-components';
import { isApiError } from '@/api/client';
import { downloadBlob } from '@/print/names';
import { formatDateTime, formatNumber, formatRelative, formatTime } from '@/lib/format';
import { Badge } from '@/ui/Badge';
import { Button } from '@/ui/Button';
import { ConfirmDialog } from '@/ui/ConfirmDialog';
import { cx } from '@/ui/cx';
import { HelpDisclosure } from '@/ui/HelpDisclosure';
import { Sheet } from '@/ui/Sheet';
import { Spinner } from '@/ui/Spinner';
import { Switch } from '@/ui/Switch';
import { TextField } from '@/ui/TextField';
import { showToast } from '@/ui/Toast';
import { errorText, showError } from '../common/usePhotoActions';
import { Card } from '../wall/fields';
import { wk } from '../wall/keys';
import {
  createProperty,
  deleteProperty,
  pollNow,
  saveLlmConfig,
  setPropertyActive,
  trashProperty,
} from './api';
import { ExternalAiHint } from './ExternalAiHint';
import { parseMinutes, PROPERTY_PROMPT_MAX, validateProperty } from './forms';
import { useProperties } from './hooks';
import { CostText, PartState } from './PartState';
import {
  exportPayload,
  importProperties,
  importSummary,
  parseImport,
  PROPERTIES_FILE,
  type InvalidEntry,
} from './propertiesJson';
import type { LlmProperty, LlmStatus } from './types';

/** „Eigenschaften abfragen“: switch and interval (one PUT /llm/config), then the poller's state. */
function PollControls({ status }: { status: LlmStatus }) {
  const qc = useQueryClient();
  const base = { poll: status.config.poll, minutes: String(Math.round(status.config.poll_interval_s / 60)) };
  const [edits, setEdits] = useState<typeof base | null>(null);
  const [busy, setBusy] = useState<'save' | 'now' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const f = edits ?? base;
  const dirty = edits !== null && (edits.poll !== base.poll || edits.minutes !== base.minutes);
  const minutes = parseMinutes(f.minutes);
  const { poller } = status;
  const set = (change: Partial<typeof base>) => {
    setError(null);
    setEdits({ ...f, ...change });
  };

  const save = async () => {
    if (minutes === null) return;
    setBusy('save');
    try {
      qc.setQueryData(wk.llm, await saveLlmConfig({ poll: f.poll, poll_interval_s: minutes * 60 }));
      setEdits(null);
      showToast({ message: 'Abfrage gespeichert.', tone: 'success' });
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  };

  const now = async () => {
    setBusy('now');
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
      setBusy(null);
    }
  };

  return (
    <section className="grid gap-2 border-b border-line pb-4" data-testid="ml-part-poll">
      <Switch isSelected={f.poll} onChange={(poll) => set({ poll })} data-testid="ml-llm-poll">
        Eigenschaften abfragen
      </Switch>
      <ExternalAiHint status={status} />
      <TextField
        label="Abfrage alle … Minuten"
        size="sm"
        inputMode="numeric"
        value={f.minutes}
        onChange={(text) => set({ minutes: text })}
        errorMessage={minutes === null ? 'Bitte eine ganze Zahl von 1 bis 60.' : null}
        description="So oft bewertet die KI die Eigenschaften (nur Text: die Objektlisten der Fotos) neu und schreibt die Urteile."
        className="max-w-xs"
        data-testid="ml-llm-minutes"
      />
      {dirty ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="primary"
            icon={Save}
            isPending={busy === 'save'}
            isDisabled={minutes === null}
            onPress={() => void save()}
            data-testid="ml-poll-save"
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
        isPending={busy === 'now'}
        isDisabled={!status.config.enabled || !status.config.poll || !status.key.set}
        onPress={() => void now()}
        className="justify-self-start"
        data-testid="ml-poll-now"
      >
        Jetzt abfragen
      </Button>
    </section>
  );
}

function NewPropertySheet({
  isOpen,
  onOpenChange,
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');
  const [errors, setErrors] = useState<{ name?: string; prompt?: string; form?: string }>({});
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const errs = validateProperty(name, prompt);
    setErrors(errs);
    if (errs.name || errs.prompt) return;
    setBusy(true);
    try {
      await createProperty(name, prompt.trim());
      await qc.invalidateQueries({ queryKey: wk.properties });
      void qc.invalidateQueries({ queryKey: wk.values });
      showToast({ message: `Eigenschaft „${name}“ angelegt.`, tone: 'success' });
      setName('');
      setPrompt('');
      onOpenChange(false);
    } catch (err) {
      if (isApiError(err) && err.code === 'property_exists') setErrors({ name: err.message });
      else setErrors({ form: errorText(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title="Neue Eigenschaft"
      description="Die KI gibt jedem Objekt auf jedem Foto einen Wert von 0 bis 1."
      data-testid="ml-property-sheet"
    >
      <form noValidate onSubmit={(e) => void submit(e)} className="grid gap-4">
        <p
          className="rounded-control bg-surface-sunk px-3 py-2 text-sm font-semibold"
          data-testid="ml-property-warning"
        >
          Name und Prompt lassen sich später nicht ändern. Für eine Änderung legst du eine neue Eigenschaft
          an.
        </p>
        <TextField
          label="Name"
          size="sm"
          value={name}
          spellCheck="false"
          onChange={(v) => {
            setName(v.toLowerCase());
            setErrors((x) => ({ ...x, name: undefined }));
          }}
          placeholder="z. B. coolness…"
          description="Für Kategorien: prop.<name>.max usw."
          errorMessage={errors.name ?? null}
          className="font-mono"
        />
        <label className="grid gap-1.5">
          <span className="text-sm font-semibold">Prompt</span>
          <textarea
            value={prompt}
            onChange={(e) => {
              setPrompt(e.target.value);
              setErrors((x) => ({ ...x, prompt: undefined }));
            }}
            rows={5}
            maxLength={PROPERTY_PROMPT_MAX}
            aria-invalid={errors.prompt ? true : undefined}
            className={cx(
              'min-h-24 rounded-control border bg-field-bg px-3 py-2 text-md text-ink outline-none focus-visible:outline-2 focus-visible:outline-focus sm:text-sm',
              errors.prompt ? 'border-danger' : 'border-field',
            )}
            placeholder="Bewerte, wie cool jedes Objekt in dieser Liste ist."
            data-testid="ml-property-prompt"
          />
          {errors.prompt ? <span className="text-sm text-danger">{errors.prompt}</span> : null}
        </label>
        {errors.form ? (
          <p role="alert" className="text-sm text-danger">
            {errors.form}
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="quiet" onPress={() => onOpenChange(false)}>
            Abbrechen
          </Button>
          <Button type="submit" size="sm" variant="primary" isPending={busy} data-testid="ml-property-create">
            Anlegen
          </Button>
        </div>
      </form>
    </Sheet>
  );
}

/** „Exportieren“ (all, inactive ones and the Papierkorb included) and „Importieren“ (only new names, never overwrites). */
function PropertiesJson({
  props,
  ready,
  children,
}: {
  props: readonly LlmProperty[];
  ready: boolean;
  children: ReactNode;
}) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [problems, setProblems] = useState<InvalidEntry[]>([]);

  const exportJson = () => {
    const text = `${JSON.stringify(exportPayload(props), null, 2)}\n`;
    downloadBlob(new Blob([text], { type: 'application/json' }), PROPERTIES_FILE);
  };

  const importJson = async (files: FileList | null) => {
    const file = files?.[0];
    if (!file) return;
    setBusy(true);
    setProblems([]);
    try {
      const parsed = parseImport(await file.text(), file.size);
      if (!parsed.ok) {
        showToast({ message: parsed.error, tone: 'error' });
        return;
      }
      const done = await importProperties(
        parsed.entries,
        props.map((p) => p.name),
        { create: createProperty, setActive: setPropertyActive, trash: trashProperty },
        errorText,
      );
      const result = { ...done, invalid: parsed.invalid };
      // one line per distinct problem (a repeated bad entry shows once)
      const lines = new Map([...result.invalid, ...result.failed].map((x) => [`${x.label}: ${x.reason}`, x]));
      setProblems([...lines.values()]);
      showToast({
        message: importSummary(result),
        tone: result.failed.length || result.invalid.length ? 'error' : 'success',
      });
      if (done.imported.length) {
        await qc.invalidateQueries({ queryKey: wk.properties });
        void qc.invalidateQueries({ queryKey: wk.values });
      }
    } catch (err) {
      showError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {children}
        <Button
          size="sm"
          variant="quiet"
          icon={Download}
          isDisabled={!ready || props.length === 0}
          onPress={exportJson}
          data-testid="ml-properties-export"
        >
          Exportieren
        </Button>
        <FileTrigger acceptedFileTypes={['application/json', '.json']} onSelect={(f) => void importJson(f)}>
          <Button
            size="sm"
            variant="quiet"
            icon={Upload}
            isPending={busy}
            isDisabled={!ready}
            data-testid="ml-properties-import"
          >
            Importieren
          </Button>
        </FileTrigger>
      </div>
      {problems.length ? (
        <div className="text-sm" data-testid="ml-properties-import-problems">
          <p className="font-semibold">Nicht importiert:</p>
          <ul className="grid gap-0.5">
            {problems.slice(0, 10).map((x) => (
              <li key={`${x.label}: ${x.reason}`}>
                <span className="font-mono">{x.label}</span>: {x.reason}
              </li>
            ))}
            {problems.length > 10 ? (
              <li className="text-ink-muted">… und {problems.length - 10} weitere</li>
            ) : null}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/** „12 Fotos bewertet · zuletzt bewertet vor 3 Min.“ */
function ScoredLine({ property: p }: { property: LlmProperty }) {
  return (
    <p className="text-xs text-ink-muted tabular">
      {formatNumber(p.scored_photos)} {p.scored_photos === 1 ? 'Foto' : 'Fotos'} bewertet · zuletzt bewertet{' '}
      {p.last_scored_at ? (
        <time dateTime={p.last_scored_at} title={formatDateTime(p.last_scored_at)}>
          {formatRelative(p.last_scored_at)}
        </time>
      ) : (
        'noch nie'
      )}
    </p>
  );
}

/** After a change: the list and the category value pickers (the Papierkorb hides values). */
function useRefresh() {
  const qc = useQueryClient();
  return async () => {
    await qc.invalidateQueries({ queryKey: wk.properties });
    void qc.invalidateQueries({ queryKey: wk.values });
  };
}

function PropertyRow({ property: p }: { property: LlmProperty }) {
  const refresh = useRefresh();
  const [busy, setBusy] = useState<'active' | 'trash' | null>(null);
  const run = async (what: 'active' | 'trash', action: () => Promise<unknown>, done?: string) => {
    setBusy(what);
    try {
      await action();
      await refresh();
      if (done) showToast({ message: done, tone: 'success' });
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
  };
  return (
    <li data-property={p.name} className="grid gap-1 border-b border-line py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className={cx('font-mono font-semibold', !p.active && 'text-ink-muted')}>{p.name}</span>
        {p.active ? null : <Badge tone="neutral">Inaktiv</Badge>}
        <div className="ml-auto flex items-center gap-2">
          <Switch
            isSelected={p.active}
            isPending={busy === 'active'}
            onChange={(on) => void run('active', () => setPropertyActive(p.name, on))}
            aria-label={`${p.name} aktiv`}
            data-testid="ml-property-active"
          >
            aktiv
          </Switch>
          <Button
            size="xs"
            variant="quiet"
            icon={Trash2}
            isPending={busy === 'trash'}
            onPress={() =>
              void run('trash', () => trashProperty(p.name, true), `„${p.name}“ liegt jetzt im Papierkorb.`)
            }
            data-testid="ml-property-trash"
          >
            Löschen
          </Button>
        </div>
      </div>
      <p className="text-sm whitespace-pre-line">{p.prompt}</p>
      <ScoredLine property={p} />
    </li>
  );
}

function TrashRow({ property: p }: { property: LlmProperty }) {
  const refresh = useRefresh();
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const restore = async () => {
    setBusy(true);
    try {
      await trashProperty(p.name, false);
      await refresh();
      showToast({ message: `„${p.name}“ wiederhergestellt.`, tone: 'success' });
    } catch (err) {
      showError(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <li data-property={p.name} className="grid gap-1 border-b border-line py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono font-semibold text-ink-muted">{p.name}</span>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Button
            size="xs"
            variant="quiet"
            icon={ArchiveRestore}
            isPending={busy}
            onPress={() => void restore()}
            data-testid="ml-property-restore"
          >
            Wiederherstellen
          </Button>
          <Button
            size="xs"
            variant="quiet"
            icon={Trash2}
            onPress={() => {
              setError(null);
              setConfirm(true);
            }}
            className="text-danger"
            data-testid="ml-property-purge"
          >
            Endgültig löschen
          </Button>
        </div>
      </div>
      <p className="text-sm whitespace-pre-line text-ink-muted">{p.prompt}</p>
      <ScoredLine property={p} />
      <ConfirmDialog
        isOpen={confirm}
        onOpenChange={setConfirm}
        title={`„${p.name}“ endgültig löschen?`}
        confirmLabel="Endgültig löschen"
        error={error}
        onConfirm={async () => {
          try {
            await deleteProperty(p.name);
          } catch (err) {
            setError(errorText(err));
            throw err;
          }
          await refresh();
          showToast({ message: `„${p.name}“ endgültig gelöscht.`, tone: 'success' });
        }}
        data-testid="ml-property-purge-confirm"
      >
        <p>
          Die Eigenschaft und ihre Werte auf {formatNumber(p.scored_photos)}{' '}
          {p.scored_photos === 1 ? 'Foto' : 'Fotos'} werden gelöscht. Das lässt sich nicht rückgängig machen;
          danach ist der Name wieder frei.
        </p>
      </ConfirmDialog>
    </li>
  );
}

export function PropertiesCard({ status }: { status: LlmStatus }) {
  const list = useProperties();
  const [open, setOpen] = useState(false);
  const props = list.data ?? [];
  const listed = props.filter((p) => p.deleted_at === null);
  const trash = props.filter((p) => p.deleted_at !== null);
  return (
    <Card
      id="eigenschaften"
      title="Eigenschaften"
      icon={Tags}
      intro="Bei jeder Abfrage bewertet die KI alle Objekte neu, z. B. wie cool sie sind. Kategorien können danach sortieren."
    >
      <PollControls status={status} />
      <PropertiesJson props={props} ready={list.isSuccess}>
        <Button
          size="sm"
          variant="secondary"
          icon={Plus}
          onPress={() => setOpen(true)}
          className="mr-auto"
          data-testid="ml-property-new"
        >
          Neue Eigenschaft
        </Button>
      </PropertiesJson>
      {list.isPending ? (
        <Spinner label="Lädt…" />
      ) : list.isError ? (
        <p className="text-sm text-danger">{errorText(list.error)}</p>
      ) : listed.length === 0 ? (
        <p className="text-sm text-ink-muted">
          {trash.length ? 'Keine Eigenschaften außerhalb des Papierkorbs.' : 'Noch keine Eigenschaften.'}
        </p>
      ) : (
        <ul className="grid border-t border-line" data-testid="ml-properties">
          {listed.map((p) => (
            <PropertyRow key={p.id} property={p} />
          ))}
        </ul>
      )}
      {trash.length ? (
        <div data-testid="ml-properties-trash">
          <HelpDisclosure variant="section" headingLevel={3} summary={`Papierkorb (${trash.length})`}>
            <p className="text-ink-muted">
              Wird nicht abgefragt und fehlt in der Werteauswahl der Kategorien; die Werte bleiben. Der Name
              bleibt belegt, bis du die Eigenschaft endgültig löschst.
            </p>
            <ul className="grid border-t border-line">
              {trash.map((p) => (
                <TrashRow key={p.id} property={p} />
              ))}
            </ul>
          </HelpDisclosure>
        </div>
      ) : null}
      <NewPropertySheet isOpen={open} onOpenChange={setOpen} />
    </Card>
  );
}
