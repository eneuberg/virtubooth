/**
 * "Kategorien": every category with its switch (part of the draft) and the photos that
 * currently lead it (the server sends the top three).
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
            const podium = winners.get(cat.id) ?? [];
            const on = !draft.categories.disabled.includes(cat.id);
            return (
              <li
                key={cat.id}
                data-category={cat.id}
                className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-3 gap-y-2 border-b border-line py-3"
              >
                <div className="grid min-w-0 gap-0.5">
                  <p className="font-semibold">
                    <span aria-hidden="true">{cat.emoji || fallback?.emoji}</span> {title}
                  </p>
                  {cat.line ? <p className="text-sm text-ink-muted">{cat.line}</p> : null}
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
                >
                  Zeigen
                </Switch>
                {podium.length > 0 ? (
                  <ol
                    aria-label={`Vorne bei ${title}`}
                    className="col-span-2 grid grid-cols-[repeat(3,minmax(0,5.5rem))] gap-2"
                    data-testid="wall-category-winners"
                  >
                    {podium.map((w, i) => (
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
                ) : (
                  <p className="col-span-2 text-xs text-ink-muted">Noch kein Foto</p>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
