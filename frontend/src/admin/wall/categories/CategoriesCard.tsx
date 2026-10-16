/**
 * "Kategorien": the wall's categories in their order (↑/↓ → PUT /categories/order),
 * each with its switch (PUT /categories/{id}), emoji, title and line (or the generated
 * explanation), the badges „Vorlage“ and „KI“ (it reads a property: needs the external
 * AI), why it can't qualify, why the app switched it off („Automatisch aus: …“) or why it
 * can't be switched on now (locked: the switch is off, the reason inline), the AI's
 * comments and the photos leading it. A banner switches the categories back on that the
 * app switched off once the reason is gone (never by itself: §8.1). „Neue Kategorie“ and
 * „Bearbeiten“ open the editor sheet; „Exportieren / Importieren“ move categories with
 * the properties they read between parties. Own requests, not part of the wall-config
 * draft. `?category=<id>` (the Live screen's „Im Editor öffnen“) opens its editor.
 */
import { useQueryClient } from '@tanstack/react-query';
import {
  ArrowDown,
  ArrowUp,
  Download,
  Lock,
  Pencil,
  Plus,
  Power,
  RotateCcw,
  Sparkles,
  Trophy,
  Upload,
} from 'lucide-react';
import { useState } from 'react';
import { FileTrigger, Link } from 'react-aria-components';
import { downloadBlob } from '@/print/names';
import { Badge } from '@/ui/Badge';
import { Button } from '@/ui/Button';
import { ConfirmDialog } from '@/ui/ConfirmDialog';
import { IconButton } from '@/ui/IconButton';
import { SegmentedControl } from '@/ui/SegmentedControl';
import { Spinner } from '@/ui/Spinner';
import { Switch } from '@/ui/Switch';
import { showToast } from '@/ui/Toast';
import { errorText, showError } from '../../common/usePhotoActions';
import { exportCategories, importCategories, orderCategories, restorePresets, saveCategory } from '../api';
import { Card } from '../fields';
import { useValues, useWallCategories } from '../hooks';
import { wk } from '../keys';
import type { CategoryItem, OnConflict } from '../types';
import {
  conflicts,
  exportName,
  importProblems,
  importSummary,
  parseCategoriesFile,
  type ParsedFile,
} from './categoriesJson';
import { CategorySheet } from './CategorySheet';
import { moveId } from './spec';
import { canComeBack, offReasonText } from './state';

const byPosition = (a: CategoryItem, b: CategoryItem) => a.position - b.position;

function Winners({ item }: { item: CategoryItem }) {
  const title = item.spec.title;
  if (item.winners.length === 0)
    return <p className="col-span-full text-xs text-ink-muted">Noch kein Foto</p>;
  const comments = item.winners.filter((w) => w.comment !== null);
  return (
    <>
      <ol
        aria-label={`Vorne bei ${title}`}
        className="col-span-full grid grid-cols-[repeat(auto-fill,minmax(3.75rem,1fr))] gap-1.5"
        data-testid="wall-category-winners"
      >
        {item.winners.map((w, i) => (
          <li key={w.photo_id} className="grid min-w-0 gap-1">
            <img
              src={w.thumb_url}
              alt={`Platz ${i + 1}: ${w.label}`}
              loading="lazy"
              className="aspect-square w-full rounded-small bg-surface-sunk object-cover"
            />
            <span aria-hidden="true" className="truncate text-xs text-ink-muted tabular">
              <span className="font-semibold text-ink">{i + 1}.</span> {w.label}
            </span>
          </li>
        ))}
      </ol>
      {comments.length > 0 ? (
        <ul className="col-span-full grid gap-1" data-testid="wall-category-comments">
          {comments.map((w) => (
            <li
              key={w.photo_id}
              className="flex items-start gap-1.5 text-sm"
              data-testid="wall-category-verdict"
            >
              <Sparkles
                aria-hidden="true"
                className="mt-0.5 size-3.5 shrink-0 text-ink-muted"
                strokeWidth={2.25}
              />
              <span>
                <span className="font-semibold tabular">{item.winners.indexOf(w) + 1}.</span>{' '}
                {w.comment?.emoji ? `${w.comment.emoji} ` : ''}
                {w.comment?.text}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </>
  );
}

function Row({
  item,
  index,
  count,
  busy,
  onMove,
  onToggle,
  onEdit,
  onExport,
}: {
  item: CategoryItem;
  index: number;
  count: number;
  busy: boolean;
  onMove: (delta: number) => void;
  onToggle: (on: boolean) => void;
  onEdit: () => void;
  onExport: () => void;
}) {
  const { spec } = item;
  const locked = item.locked !== null && !item.enabled;
  return (
    <li
      data-category={item.id}
      data-enabled={item.enabled || undefined}
      data-locked={locked || undefined}
      className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-x-2 gap-y-2 border-b border-line py-3"
    >
      <div className="-ml-2 grid">
        <IconButton
          label={`${spec.title} nach oben`}
          icon={ArrowUp}
          isDisabled={index === 0 || busy}
          onPress={() => onMove(-1)}
        />
        <IconButton
          label={`${spec.title} nach unten`}
          icon={ArrowDown}
          isDisabled={index === count - 1 || busy}
          onPress={() => onMove(1)}
        />
      </div>
      <div className="grid min-w-0 gap-0.5">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 font-semibold">
          <span>
            <span aria-hidden="true">{spec.emoji}</span> {spec.title}
          </span>
          {item.preset ? <Badge tone="neutral">Vorlage</Badge> : null}
          {item.needs_ai ? (
            <span data-testid="category-ai-badge" title="Braucht die externe KI (liest eine Eigenschaft)">
              <Badge tone="mark" icon={Sparkles}>
                KI
              </Badge>
            </span>
          ) : null}
        </p>
        <p className="text-sm text-ink-muted">{spec.line || item.explanation}</p>
        {locked && item.locked ? (
          <p className="flex flex-wrap items-center gap-1.5 text-xs text-mark" data-testid="category-lock">
            <Lock aria-hidden="true" className="size-3.5" strokeWidth={2.25} />
            {item.locked.message}{' '}
            <Link href="/manage?tab=ml" className="font-semibold text-ink underline underline-offset-2">
              {item.locked.reason === 'ai_off' ? 'Zur Externen KI' : 'Zum Papierkorb'}
            </Link>
          </p>
        ) : !item.enabled && item.off_reason ? (
          <p className="text-xs text-mark" data-testid="category-auto-off">
            Automatisch aus: {offReasonText(item.off_reason, item.off_detail)}
          </p>
        ) : null}
        {item.available ? null : (
          <p className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
            <Badge tone="mark">Braucht Analyse</Badge>
            {item.reason}
          </p>
        )}
        {item.verdict_paused && spec.verdict ? (
          <p className="text-xs text-ink-muted">KI-Kommentare pausiert, solange die externe KI aus ist.</p>
        ) : null}
      </div>
      <div className="grid justify-items-end gap-1">
        <Switch
          isSelected={item.enabled}
          isPending={busy}
          isDisabled={locked}
          aria-label={`${spec.title} zeigen`}
          onChange={onToggle}
        >
          Zeigen
        </Switch>
        <div className="flex items-center">
          <IconButton label={`${spec.title} exportieren`} icon={Download} onPress={onExport} />
          <Button size="xs" variant="quiet" icon={Pencil} onPress={onEdit} data-testid="category-edit">
            Bearbeiten
          </Button>
        </div>
      </div>
      <div className="col-start-2 col-end-4 grid gap-1.5">
        <Winners item={item} />
      </div>
    </li>
  );
}

/** „N Kategorien wieder einschalten“ (§8.1: nothing comes back on by itself). */
function ComeBackBanner({
  items,
  busy,
  onPress,
}: {
  items: CategoryItem[];
  busy: boolean;
  onPress: () => void;
}) {
  if (items.length === 0) return null;
  const n = items.length;
  return (
    <output
      className="flex flex-wrap items-center gap-3 rounded-control bg-accent-tint p-3 text-sm"
      data-testid="category-comeback"
    >
      <p className="min-w-0 flex-1">
        {n === 1 ? `„${items[0]?.spec.title}“ wurde` : `${n} Kategorien wurden`} automatisch ausgeschaltet und{' '}
        {n === 1 ? 'kann' : 'können'} wieder an: {items.map((c) => c.spec.title).join(', ')}.
      </p>
      <Button
        size="xs"
        variant="primary"
        icon={Power}
        isPending={busy}
        onPress={onPress}
        data-testid="category-comeback-on"
      >
        {n === 1 ? 'Wieder einschalten' : `${n} Kategorien wieder einschalten`}
      </Button>
    </output>
  );
}

export function CategoriesCard() {
  const qc = useQueryClient();
  const list = useWallCategories();
  const values = useValues();
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ item: CategoryItem | null; n: number } | null>(null);
  const [pending, setPending] = useState<ParsedFile | null>(null);
  const [onConflict, setOnConflict] = useState<OnConflict>('copy');
  const [importError, setImportError] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const items = [...(list.data ?? [])].toSorted(byPosition);
  const ids = items.map((c) => c.id);
  const comeBack = items.filter(canComeBack);

  // the Live screen's „Im Editor öffnen“ (?category=<id>) opens its editor once
  const [linked, setLinked] = useState(() => new URLSearchParams(window.location.search).get('category'));
  const linkedItem = linked ? items.find((c) => c.id === linked) : undefined;
  const sheet = editing ?? (linkedItem ? { item: linkedItem, n: 0 } : null);
  const closeSheet = () => {
    setEditing(null);
    if (!linked) return;
    setLinked(null);
    const url = new URL(window.location.href);
    url.searchParams.delete('category');
    window.history.replaceState(window.history.state, '', url);
  };

  const move = async (id: string, delta: number) => {
    const next = moveId(ids, id, delta);
    // at once on screen, then what the server says
    qc.setQueryData<CategoryItem[]>(wk.categories, (old) =>
      old?.map((c) => ({ ...c, position: next.indexOf(c.id) })),
    );
    setBusy(id);
    try {
      qc.setQueryData(wk.categories, await orderCategories(next));
    } catch (err) {
      showError(err);
      void qc.invalidateQueries({ queryKey: wk.categories });
    } finally {
      setBusy(null);
    }
  };

  const toggle = async (item: CategoryItem, enabled: boolean) => {
    setBusy(item.id);
    try {
      const out = await saveCategory(item.id, item.spec, enabled);
      qc.setQueryData<CategoryItem[]>(wk.categories, (old) => old?.map((c) => (c.id === item.id ? out : c)));
      // switching on may create a preset's property
      if (enabled && item.needs_ai) void qc.invalidateQueries({ queryKey: wk.properties });
    } catch (err) {
      showError(err);
      void qc.invalidateQueries({ queryKey: wk.categories });
    } finally {
      setBusy(null);
    }
  };

  const switchBackOn = async () => {
    setBusy('comeback');
    let failed = 0;
    for (const item of comeBack) {
      try {
        // oxlint-disable-next-line no-await-in-loop -- one after the other, in the wall's order
        await saveCategory(item.id, item.spec, true);
      } catch {
        failed += 1;
      }
    }
    await qc.invalidateQueries({ queryKey: wk.categories });
    void qc.invalidateQueries({ queryKey: wk.properties });
    setBusy(null);
    showToast({
      message: failed ? `${failed} ließen sich nicht einschalten.` : 'Wieder eingeschaltet.',
      tone: failed ? 'error' : 'success',
    });
  };

  const restore = async () => {
    setBusy('restore');
    try {
      const { added } = await restorePresets();
      showToast({
        message:
          added.length === 0
            ? 'Alle Vorlagen sind schon da.'
            : added.length === 1
              ? '1 Vorlage wiederhergestellt.'
              : `${added.length} Vorlagen wiederhergestellt.`,
        tone: 'success',
      });
      void qc.invalidateQueries({ queryKey: wk.categories });
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
  };

  const exportJson = async (only: string[] = []) => {
    setBusy('export');
    try {
      const file = await exportCategories(only);
      const text = `${JSON.stringify(file, null, 2)}\n`;
      downloadBlob(new Blob([text], { type: 'application/json' }), exportName(only));
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
  };

  const runImport = async (parsed: ParsedFile, mode: OnConflict) => {
    const result = await importCategories(parsed.file, mode);
    setProblems(importProblems(result));
    showToast({
      message: importSummary(result),
      tone: result.skipped.length || result.switched_off.length ? 'info' : 'success',
    });
    await qc.invalidateQueries({ queryKey: wk.categories });
    if (result.properties_created.length) {
      void qc.invalidateQueries({ queryKey: wk.properties });
      void qc.invalidateQueries({ queryKey: wk.values });
    }
  };

  const pickFile = async (files: FileList | null) => {
    const file = files?.[0];
    if (!file) return;
    setProblems([]);
    const parsed = parseCategoriesFile(await file.text(), file.size);
    if (!parsed.ok) {
      showToast({ message: parsed.error, tone: 'error' });
      return;
    }
    if (conflicts(parsed.ids, ids).length > 0) {
      // the dialog asks: as a copy, or replace
      setOnConflict('copy');
      setImportError(null);
      setPending(parsed);
      return;
    }
    setBusy('import');
    try {
      await runImport(parsed, 'copy');
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
  };

  const open = (item: CategoryItem | null) => {
    setLinked(null);
    setEditing((e) => ({ item, n: (e?.n ?? 0) + 1 }));
  };
  const clash = pending ? conflicts(pending.ids, ids) : [];

  return (
    <Card
      id="kategorien"
      title="Kategorien"
      icon={Trophy}
      intro={
        <>
          Lustige Bestenlisten aus der Analyse, in dieser Reihenfolge auf der Wall. Eine Kategorie erscheint
          erst, wenn ein Foto sie erfüllt. Modelle und KI:{' '}
          <Link href="/manage?tab=ml" className="font-semibold text-ink underline underline-offset-3">
            ML-Pipeline
          </Link>
          .
        </>
      }
    >
      <div className="flex flex-wrap gap-2">
        <Button
          size="xs"
          variant="secondary"
          icon={Plus}
          isDisabled={!values.data}
          onPress={() => open(null)}
          data-testid="category-new"
        >
          Neue Kategorie
        </Button>
        <Button
          size="xs"
          variant="quiet"
          icon={RotateCcw}
          isPending={busy === 'restore'}
          onPress={() => void restore()}
          data-testid="category-restore"
        >
          Vorlagen wiederherstellen
        </Button>
        <Button
          size="xs"
          variant="quiet"
          icon={Download}
          isPending={busy === 'export'}
          isDisabled={items.length === 0}
          onPress={() => void exportJson()}
          data-testid="category-export"
        >
          Exportieren
        </Button>
        <FileTrigger acceptedFileTypes={['application/json', '.json']} onSelect={(f) => void pickFile(f)}>
          <Button
            size="xs"
            variant="quiet"
            icon={Upload}
            isPending={busy === 'import'}
            data-testid="category-import"
          >
            Importieren
          </Button>
        </FileTrigger>
      </div>
      {problems.length ? (
        <ul className="grid gap-0.5 text-sm" data-testid="category-import-problems">
          {problems.slice(0, 10).map((p) => (
            <li key={p}>{p}</li>
          ))}
          {problems.length > 10 ? (
            <li className="text-ink-muted">… und {problems.length - 10} weitere</li>
          ) : null}
        </ul>
      ) : null}
      <ComeBackBanner items={comeBack} busy={busy === 'comeback'} onPress={() => void switchBackOn()} />
      {list.isPending ? (
        <Spinner label="Lädt…" />
      ) : list.isError ? (
        <p className="text-sm text-danger">{errorText(list.error)}</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-ink-muted">Noch keine Kategorien.</p>
      ) : (
        <ol className="grid border-t border-line" data-testid="wall-categories">
          {items.map((item, i) => (
            <Row
              key={item.id}
              item={item}
              index={i}
              count={items.length}
              busy={busy === item.id}
              onMove={(d) => void move(item.id, d)}
              onToggle={(on) => void toggle(item, on)}
              onEdit={() => open(item)}
              onExport={() => void exportJson([item.id])}
            />
          ))}
        </ol>
      )}
      <ConfirmDialog
        isOpen={pending !== null}
        onOpenChange={(o) => {
          if (!o) setPending(null);
        }}
        title="Kategorien importieren?"
        confirmLabel="Importieren"
        tone="neutral"
        error={importError}
        onConfirm={async () => {
          if (!pending) return;
          try {
            await runImport(pending, onConflict);
          } catch (err) {
            setImportError(errorText(err));
            throw err;
          }
        }}
        data-testid="category-import-confirm"
      >
        <p>
          {clash.length === 1
            ? `„${clash[0]}“ gibt es schon.`
            : `${clash.length} Kennungen gibt es schon: ${clash.join(', ')}.`}
        </p>
        <SegmentedControl<OnConflict>
          label="Bei gleicher Kennung"
          size="sm"
          options={[
            { id: 'copy', label: 'Als Kopie (_2)' },
            { id: 'replace', label: 'Vorhandene ersetzen' },
          ]}
          value={onConflict}
          onChange={setOnConflict}
          className="mt-2"
          data-testid="category-import-mode"
        />
      </ConfirmDialog>
      {sheet && values.data ? (
        <CategorySheet
          // a fresh form per opening
          key={`${sheet.item?.id ?? '+'}:${sheet.n}`}
          item={sheet.item}
          values={values.data}
          taken={ids}
          isOpen
          onOpenChange={(o) => {
            if (!o) closeSheet();
          }}
        />
      ) : null}
    </Card>
  );
}
