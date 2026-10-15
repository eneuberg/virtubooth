/**
 * "Kategorien": the wall's categories in their order (↑/↓ → PUT /categories/order),
 * each with its switch (PUT /categories/{id}), emoji, title and line, „Vorlage“ for
 * presets, why it can't qualify, the AI's last verdict and the photos leading it.
 * „Neue Kategorie“ and „Bearbeiten“ open the editor sheet. Own requests, not part of
 * the wall-config draft.
 */
import { useQueryClient } from '@tanstack/react-query';
import { ArrowDown, ArrowUp, Pencil, Plus, RotateCcw, Sparkles, Trophy } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-aria-components';
import { Badge } from '@/ui/Badge';
import { Button } from '@/ui/Button';
import { IconButton } from '@/ui/IconButton';
import { Spinner } from '@/ui/Spinner';
import { Switch } from '@/ui/Switch';
import { showToast } from '@/ui/Toast';
import { errorText, showError } from '../../common/usePhotoActions';
import { orderCategories, restorePresets, saveCategory } from '../api';
import { Card } from '../fields';
import { useValues, useWallCategories } from '../hooks';
import { wk } from '../keys';
import type { CategoryItem } from '../types';
import { CategorySheet } from './CategorySheet';
import { moveId } from './spec';

const byPosition = (a: CategoryItem, b: CategoryItem) => a.position - b.position;

function Winners({ item }: { item: CategoryItem }) {
  const title = item.spec.title;
  if (item.winners.length === 0)
    return <p className="col-span-full text-xs text-ink-muted">Noch kein Foto</p>;
  return (
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
}: {
  item: CategoryItem;
  index: number;
  count: number;
  busy: boolean;
  onMove: (delta: number) => void;
  onToggle: (on: boolean) => void;
  onEdit: () => void;
}) {
  const { spec } = item;
  return (
    <li
      data-category={item.id}
      data-enabled={item.enabled || undefined}
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
        </p>
        {spec.line ? <p className="text-sm text-ink-muted">{spec.line}</p> : null}
        {item.available ? null : (
          <p className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
            <Badge tone="mark">Braucht Analyse</Badge>
            {item.reason}
          </p>
        )}
        {item.verdict ? (
          <p className="flex items-start gap-1.5 text-sm" data-testid="wall-category-verdict">
            <Sparkles
              aria-hidden="true"
              className="mt-0.5 size-3.5 shrink-0 text-ink-muted"
              strokeWidth={2.25}
            />
            <span>
              {item.verdict.emoji ? `${item.verdict.emoji} ` : ''}
              {item.verdict.text}
            </span>
          </p>
        ) : null}
      </div>
      <div className="grid justify-items-end gap-1">
        <Switch
          isSelected={item.enabled}
          isPending={busy}
          aria-label={`${spec.title} zeigen`}
          onChange={onToggle}
        >
          Zeigen
        </Switch>
        <Button size="xs" variant="quiet" icon={Pencil} onPress={onEdit} data-testid="category-edit">
          Bearbeiten
        </Button>
      </div>
      <div className="col-start-2 col-end-4 grid">
        <Winners item={item} />
      </div>
    </li>
  );
}

export function CategoriesCard() {
  const qc = useQueryClient();
  const list = useWallCategories();
  const values = useValues();
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ item: CategoryItem | null; n: number } | null>(null);
  const items = [...(list.data ?? [])].toSorted(byPosition);
  const ids = items.map((c) => c.id);

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
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
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

  const open = (item: CategoryItem | null) => setEditing((e) => ({ item, n: (e?.n ?? 0) + 1 }));

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
      </div>
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
            />
          ))}
        </ol>
      )}
      {editing && values.data ? (
        <CategorySheet
          // a fresh form per opening
          key={`${editing.item?.id ?? '+'}:${editing.n}`}
          item={editing.item}
          values={values.data}
          taken={ids}
          isOpen
          onOpenChange={(o) => {
            if (!o) setEditing(null);
          }}
        />
      ) : null}
    </Card>
  );
}
