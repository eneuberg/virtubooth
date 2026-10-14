/**
 * "Kategorien": every category with its switch (part of the draft) and the photo that
 * currently wins it.
 */
import { Trophy } from 'lucide-react';
import { Badge } from '@/ui/Badge';
import { Switch } from '@/ui/Switch';
import type { DraftProps } from './ConfigCards';
import { toggleIn } from './draft';
import { Card } from './fields';
import { useWallCategories } from './hooks';
import { CATEGORY_LABELS } from './labels';
import type { CategoryInfo, CategoryOverview } from './types';

export function CategoriesCard({ draft, update, categories }: DraftProps & { categories: CategoryInfo[] }) {
  const overview = useWallCategories();
  const winners = new Map<string, CategoryOverview['winners']>(
    (overview.data ?? []).map((c) => [c.id, c.winners]),
  );
  const list: CategoryInfo[] = overview.data ?? categories;
  return (
    <Card
      id="kategorien"
      title="Kategorien"
      icon={Trophy}
      intro="Lustige Bestenlisten aus der Analyse. Eine Kategorie erscheint erst, wenn ein Foto sie erfüllt."
    >
      {list.length === 0 ? (
        <p className="text-sm text-ink-muted">Noch keine Kategorien.</p>
      ) : (
        <ul className="grid border-t border-line" data-testid="wall-categories">
          {list.map((cat) => {
            const fallback = CATEGORY_LABELS[cat.id];
            const title = cat.title || fallback?.title || cat.id;
            const top = winners.get(cat.id)?.[0];
            const on = !draft.categories.disabled.includes(cat.id);
            return (
              <li
                key={cat.id}
                data-category={cat.id}
                className="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-x-3 gap-y-2 border-b border-line py-3 sm:grid-cols-[3.5rem_minmax(0,1fr)_auto] sm:items-center"
              >
                {top ? (
                  <img
                    src={top.thumb_url}
                    alt={`Gewinnerfoto ${title}`}
                    className="row-span-2 size-14 rounded-small object-cover sm:row-span-1"
                  />
                ) : (
                  <span
                    aria-hidden="true"
                    className="row-span-2 grid size-14 place-items-center rounded-small bg-surface-sunk text-2xl sm:row-span-1"
                  >
                    {cat.emoji || fallback?.emoji}
                  </span>
                )}
                <div className="grid min-w-0 gap-0.5">
                  <p className="font-semibold">
                    <span aria-hidden="true">{cat.emoji || fallback?.emoji}</span> {title}
                  </p>
                  {cat.line ? <p className="text-sm text-ink-muted">{cat.line}</p> : null}
                  <p className="text-xs text-ink-muted tabular">{top ? top.label : 'Noch kein Foto'}</p>
                  {cat.available ? null : (
                    <p className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
                      <Badge tone="mark">Braucht Analyse</Badge>
                      {cat.reason}
                    </p>
                  )}
                </div>
                <Switch
                  isSelected={on}
                  aria-label={`${title} zeigen`}
                  onChange={(show) =>
                    update((c) => ({
                      ...c,
                      categories: {
                        ...c.categories,
                        disabled: toggleIn(c.categories.disabled, cat.id, !show),
                      },
                    }))
                  }
                  className="col-start-2 sm:col-start-3"
                >
                  Zeigen
                </Switch>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
