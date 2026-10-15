/**
 * "Eigenschaften": what the external AI rates per object at every poll (coolness …).
 * Name and prompt are fixed once created (N7): no edit, no delete; archiving stops
 * the polling and keeps the last scores, and can be undone.
 */
import { useQueryClient } from '@tanstack/react-query';
import { Archive, ArchiveRestore, Plus, Tags } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { isApiError } from '@/api/client';
import { formatDateTime, formatNumber, formatRelative } from '@/lib/format';
import { Badge } from '@/ui/Badge';
import { Button } from '@/ui/Button';
import { cx } from '@/ui/cx';
import { Sheet } from '@/ui/Sheet';
import { Spinner } from '@/ui/Spinner';
import { TextField } from '@/ui/TextField';
import { showToast } from '@/ui/Toast';
import { errorText, showError } from '../common/usePhotoActions';
import { Card } from '../wall/fields';
import { wk } from '../wall/keys';
import { archiveProperty, createProperty } from './api';
import { PROPERTY_PROMPT_MAX, validateProperty } from './forms';
import { useProperties } from './hooks';
import type { LlmProperty } from './types';

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

function PropertyRow({ property: p }: { property: LlmProperty }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const archived = p.archived_at !== null;
  const toggle = async () => {
    setBusy(true);
    try {
      await archiveProperty(p.name, !archived);
      await qc.invalidateQueries({ queryKey: wk.properties });
      void qc.invalidateQueries({ queryKey: wk.values });
    } catch (err) {
      showError(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <li data-property={p.name} className="grid gap-1 border-b border-line py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cx('font-mono font-semibold', archived && 'text-ink-muted')}>{p.name}</span>
        {archived ? <Badge tone="neutral">Archiviert</Badge> : null}
        <Button
          size="xs"
          variant="quiet"
          icon={archived ? ArchiveRestore : Archive}
          isPending={busy}
          onPress={() => void toggle()}
          className="ml-auto"
        >
          {archived ? 'Wiederherstellen' : 'Archivieren'}
        </Button>
      </div>
      <p className="text-sm whitespace-pre-line">{p.prompt}</p>
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
    </li>
  );
}

export function PropertiesCard() {
  const list = useProperties();
  const [open, setOpen] = useState(false);
  const props = list.data ?? [];
  const active = props.filter((p) => p.archived_at === null);
  const archived = props.filter((p) => p.archived_at !== null);
  return (
    <Card
      id="eigenschaften"
      title="Eigenschaften"
      icon={Tags}
      intro="Bei jeder Abfrage bewertet die KI alle Objekte neu, z. B. wie cool sie sind. Kategorien können danach sortieren."
    >
      <Button
        size="sm"
        variant="secondary"
        icon={Plus}
        onPress={() => setOpen(true)}
        className="justify-self-start"
        data-testid="ml-property-new"
      >
        Neue Eigenschaft
      </Button>
      {list.isPending ? (
        <Spinner label="Lädt…" />
      ) : list.isError ? (
        <p className="text-sm text-danger">{errorText(list.error)}</p>
      ) : props.length === 0 ? (
        <p className="text-sm text-ink-muted">Noch keine Eigenschaften.</p>
      ) : (
        <ul className="grid border-t border-line" data-testid="ml-properties">
          {[...active, ...archived].map((p) => (
            <PropertyRow key={p.id} property={p} />
          ))}
        </ul>
      )}
      <NewPropertySheet isOpen={open} onOpenChange={setOpen} />
    </Card>
  );
}
