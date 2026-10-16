/**
 * The three object views as tabs: „Lokales Modell“, „KI (Claude)“ with provider and
 * model, „Zusammengeführt (für Eigenschaften)“. Each lists its objects with the
 * thing's colour (labelColors.ts, as on the Live tiles); the frames of the chosen view
 * lie on the photo (the caller draws them, objectViews.ts), outlined by who found it.
 * Used by the photo inspector's analysis and the ML-Pipeline's test image.
 */
import { Sparkles } from 'lucide-react';
import { TabPanel, type Key } from 'react-aria-components';
import { Badge } from '@/ui/Badge';
import { cx } from '@/ui/cx';
import { TabList, Tabs } from '@/ui/Tabs';
import { scoreText, sourceText } from '../ml/text';
import { labelColor } from './labelColors';
import {
  fromBoth,
  OBJECT_VIEWS,
  rowOutline,
  type ObjectRow,
  type ObjectView,
  type ObjectViews,
  sourcesText,
} from './objectViews';

export interface ObjectViewTabsProps {
  views: ObjectViews;
  value: ObjectView;
  onChange: (view: ObjectView) => void;
  /** a row's key while the pointer is on it (its frame lights up), null when it leaves */
  onHover?: (view: ObjectView, key: number | null) => void;
  /** the property scores under each merged row (index = idx) */
  properties?: ReadonlyArray<PropertyScores>;
  /** why a view is empty or missing */
  empty: Record<ObjectView, string>;
  /** the merged list's data-testid (the panel's own tests and e2e look for it) */
  listTestId?: string;
}

export interface PropertyScores {
  name: string;
  inactive: boolean;
  scores: ReadonlyArray<number | null>;
}

const isView = (key: Key): key is ObjectView => OBJECT_VIEWS.some((v) => v === key);

/** „coolness 0,90  tanzbar –“ under a merged row */
function ScoreLine({ idx, properties }: { idx: number; properties: ReadonlyArray<PropertyScores> }) {
  return (
    <p className="pl-8 text-xs text-ink-muted tabular">
      {properties.map((p) => {
        const score = p.scores[idx];
        return (
          <span
            key={p.name}
            className={cx('mr-3', p.inactive && 'opacity-60')}
            title={p.inactive ? 'inaktiv: wird nicht mehr abgefragt' : undefined}
          >
            <span className="font-mono">{p.name}</span>{' '}
            {score === null || score === undefined ? '–' : score.toFixed(2).replace('.', ',')}
          </span>
        );
      })}
    </p>
  );
}

/** The thing's frame colour with its outline (who found it), before its row. */
const Swatch = ({ row }: { row: ObjectRow }) => {
  const outline = rowOutline(row);
  return (
    <span
      aria-hidden="true"
      data-testid="analysis-object-swatch"
      className={cx(
        'inline-block size-3 shrink-0 rounded-[2px]',
        outline === 'double' ? 'border-[3px] border-double' : 'border-2',
        outline === 'dashed' && 'border-dashed',
      )}
      style={{ borderColor: labelColor(row.label).color }}
    />
  );
};

/** The outline a view's frames have, as words. */
const OUTLINE_TEXT: Record<ObjectView, string> = {
  local: 'Rahmen durchgezogen.',
  ai: 'Rahmen gestrichelt.',
  merged: 'Rahmen: lokal durchgezogen, KI gestrichelt, beide doppelt.',
};

function Rows({
  view,
  rows,
  onHover,
  properties,
  testId,
}: {
  view: ObjectView;
  rows: ObjectRow[];
  onHover: ObjectViewTabsProps['onHover'];
  properties: ObjectViewTabsProps['properties'];
  testId: string | undefined;
}) {
  return (
    <ol className="grid border-t border-line text-sm" aria-label="Erkannte Objekte" data-testid={testId}>
      {rows.map((o) => {
        const both = view === 'merged' && fromBoth(o);
        return (
          <li
            key={o.key}
            data-testid="analysis-object"
            data-view={view}
            data-idx={o.key}
            data-sources={o.sources.join(',')}
            className={cx('grid gap-0.5 border-b border-line py-1.5', o.box && 'hover:bg-surface-hover')}
            onPointerEnter={o.box && onHover ? () => onHover(view, o.key) : undefined}
            onPointerLeave={o.box && onHover ? () => onHover(view, null) : undefined}
          >
            <div className="flex min-w-0 items-center gap-2">
              <span className="w-6 shrink-0 text-ink-muted tabular">{o.key}</span>
              <Swatch row={o} />
              <span className="min-w-0 flex-1 truncate font-semibold" title={o.label}>
                {o.label_de}
              </span>
              <span className="tabular">{scoreText(o.score)}</span>
              {view === 'merged' ? (
                <Badge
                  tone={both ? 'ok' : o.sources.includes('local') ? 'neutral' : 'new'}
                  icon={o.sources.includes('local') ? undefined : Sparkles}
                >
                  {both ? 'beide' : sourcesText(o.sources)}
                </Badge>
              ) : o.mergedIdx !== null ? (
                <span
                  className="text-xs text-ink-muted tabular"
                  title="Eintrag in der zusammengeführten Liste"
                >
                  → {o.mergedIdx}
                </span>
              ) : null}
            </div>
            {both && o.parts.length > 1 ? (
              <p className="pl-8 text-xs text-ink-muted tabular" data-testid="analysis-object-parts">
                {o.parts
                  .map((p) => `${sourceText(p.source)}: ${p.label_de} ${scoreText(p.score)}`)
                  .join(' · ')}
              </p>
            ) : null}
            {view === 'merged' && properties && properties.length > 0 ? (
              <ScoreLine idx={o.key} properties={properties} />
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

export function ObjectViewTabs({
  views,
  value,
  onChange,
  onHover,
  properties,
  empty,
  listTestId,
}: ObjectViewTabsProps) {
  const lists: Record<ObjectView, ObjectRow[] | null> = {
    local: views.local,
    ai: views.ai,
    merged: views.merged,
  };
  const items = [
    { id: 'local' as const, label: 'Lokales Modell', count: views.local?.length },
    { id: 'ai' as const, label: `KI (${views.aiTitle})`, count: views.ai?.length },
    { id: 'merged' as const, label: 'Zusammengeführt (für Eigenschaften)', count: views.merged.length },
  ].map((t) => (t.count === undefined ? { id: t.id, label: t.label } : t));
  return (
    <Tabs
      selectedKey={value}
      onSelectionChange={(key) => {
        if (isView(key)) onChange(key);
      }}
      className="gap-2"
      data-testid="object-views"
    >
      <TabList label="Objektlisten" items={items} />
      {(['local', 'ai', 'merged'] as const).map((view) => {
        const rows = lists[view];
        return (
          <TabPanel
            key={view}
            id={view}
            className="grid gap-1.5 outline-none"
            data-testid={`object-view-${view}`}
          >
            <p className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
              {view === 'local'
                ? 'Was das Modell auf dem Server erkannt hat.'
                : view === 'ai'
                  ? `Was ${views.aiTitle} erkannt hat${views.aiModel ? '' : '.'}`
                  : 'Das bewertet die Abfrage der Eigenschaften (neue Fotos: nur eine Quelle; ältere mit beiden ohne Doppelte).'}
              {view === 'ai' && views.aiModel ? (
                <span>
                  (<span className="font-mono">{views.aiModel}</span>).
                </span>
              ) : null}
              <span>{OUTLINE_TEXT[view]}</span>
            </p>
            {rows === null || rows.length === 0 ? (
              <p className="text-sm text-ink-muted" data-testid={`object-view-${view}-empty`}>
                {rows === null ? empty[view] : 'Keine Objekte erkannt.'}
              </p>
            ) : (
              <Rows
                view={view}
                rows={rows}
                onHover={onHover}
                properties={properties}
                testId={view === 'merged' ? listTestId : undefined}
              />
            )}
          </TabPanel>
        );
      })}
    </Tabs>
  );
}
