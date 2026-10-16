/**
 * A category a photo wins, opened up on the Live screen (host decision §8.6): emoji,
 * title, the explanation, the rule in plain German (pool, ranking with its threshold,
 * tie-breakers, how many), this photo's place and value, its focus object, the AI's
 * comment, the category's state (on / off / locked, with the reason) and „Im Editor
 * öffnen“. The tile's win chip opens it in a popover, the photo viewer's list inline.
 *
 * The photo's part comes with the tile's summary (`wins[]`); the rule and the state
 * from GET /categories (cached, asked for only once something is opened).
 */
import { ChevronDown, Lock, Pencil, Sparkles } from 'lucide-react';
import type { ReactNode } from 'react';
import {
  Button as AriaButton,
  Dialog,
  DialogTrigger,
  Disclosure,
  DisclosurePanel,
  Heading,
  Popover,
} from 'react-aria-components';
import { NBSP } from '@/lib/format';
import { LinkButton } from '@/ui/Button';
import { cx } from '@/ui/cx';
import { Spinner } from '@/ui/Spinner';
import { useSurface } from '@/ui/Surface';
import { ruleText } from './categories/spec';
import { categoryState, editorHref } from './categories/state';
import { useValues, useWallCategories } from './hooks';
import type { CategoryWin } from './types';

function Row({ label, children, testid }: { label: string; children: ReactNode; testid?: string }) {
  return (
    <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-2" data-testid={testid}>
      <dt className="text-ink-muted">{label}</dt>
      <dd className="m-0 min-w-0">{children}</dd>
    </div>
  );
}

/** The opened category (both places). */
export function CategoryWinDetails({ win }: { win: CategoryWin }) {
  const cats = useWallCategories();
  const values = useValues();
  const item = cats.data?.find((c) => c.id === win.id);
  const value = [win.headline, win.detail].filter(Boolean).join(' · ');
  const rule = item && values.data ? ruleText(item.spec, values.data) : null;
  const state = item ? categoryState(item) : null;
  return (
    <div className="grid gap-2 text-sm" data-testid="category-win-details" data-category={win.id}>
      <p className="flex items-center gap-2 text-md font-bold">
        <span aria-hidden="true">{win.emoji}</span>
        {win.title}
      </p>
      {item ? <p className="text-ink-muted">{item.spec.line || item.explanation}</p> : null}
      {cats.isPending || values.isPending ? <Spinner label="Lädt…" className="size-4" /> : null}
      <dl className="grid gap-1">
        <Row label="Dieses Foto" testid="category-win-place">
          Platz {win.rank}
          {value ? ` · ${value}` : ''}
        </Row>
        {win.object_label ? (
          <Row label="Objekt" testid="category-win-object">
            {win.object_label}
          </Row>
        ) : null}
        {win.comment ? (
          <Row label="KI-Kommentar" testid="category-win-comment">
            <span className="inline-flex items-start gap-1">
              <Sparkles
                aria-hidden="true"
                className="mt-0.5 size-3.5 shrink-0 text-ink-muted"
                strokeWidth={2.25}
              />
              <span>
                {win.comment.emoji ? `${win.comment.emoji}${NBSP}` : ''}
                {win.comment.text}
              </span>
            </span>
          </Row>
        ) : null}
        {rule ? (
          <>
            <Row label="Fotos" testid="category-win-pool">
              {rule.pool}
            </Row>
            <Row label="Gewinner" testid="category-win-rank">
              {rule.rank}
              {rule.ties.length ? (
                <span className="text-ink-muted">; bei Gleichstand: {rule.ties.join(', dann ')}</span>
              ) : null}
            </Row>
            <Row label="Anzahl" testid="category-win-select">
              {rule.select}
            </Row>
          </>
        ) : null}
        {state ? (
          <Row label="Status" testid="category-win-state">
            <span
              className={cx(state.tone === 'locked' && 'text-mark', state.tone === 'on' && 'text-ok')}
              data-tone={state.tone}
            >
              {state.tone === 'locked' ? (
                <Lock aria-hidden="true" className="mr-1 inline size-3.5" strokeWidth={2.25} />
              ) : null}
              {state.text}
            </span>
          </Row>
        ) : null}
      </dl>
      <LinkButton
        href={editorHref(win.id)}
        size="xs"
        variant="secondary"
        icon={Pencil}
        className="justify-self-start"
        data-testid="category-win-edit"
      >
        Im Editor öffnen
      </LinkButton>
    </div>
  );
}

/** The tile's win chip: a button that opens the category in a popover. */
export function WinChipButton({
  win,
  className,
  children,
}: {
  win: CategoryWin;
  className: string;
  children: ReactNode;
}) {
  const surface = useSurface();
  return (
    <DialogTrigger>
      <AriaButton
        className={cx(
          className,
          'cursor-pointer outline-none hover:brightness-95 focus-visible:outline-2 focus-visible:outline-focus',
        )}
        aria-label={`${win.title}: Platz ${win.rank}, aufklappen`}
        data-testid="win-chip"
      >
        {children}
        <ChevronDown aria-hidden="true" className="size-3 shrink-0" strokeWidth={2.5} />
      </AriaButton>
      <Popover
        data-surface={surface}
        placement="bottom start"
        offset={6}
        className="w-[min(22rem,calc(100vw-2rem))] rounded-control border border-line bg-surface-raised p-3 text-ink shadow-float outline-none"
      >
        <Dialog aria-label={win.title} className="outline-none">
          <CategoryWinDetails win={win} />
        </Dialog>
      </Popover>
    </DialogTrigger>
  );
}

/** One category in the viewer's list, opened in place. */
export function WinDisclosure({ win }: { win: CategoryWin }) {
  return (
    <Disclosure className="group" data-testid="analysis-win" data-category={win.id}>
      <Heading level={4} className="m-0">
        <AriaButton
          slot="trigger"
          className="flex min-h-10 w-full cursor-pointer items-center gap-2 rounded-small text-left text-sm outline-none focus-visible:outline-2 focus-visible:outline-focus"
        >
          <span aria-hidden="true">{win.emoji}</span>
          <span className="min-w-0 flex-1 truncate font-semibold">{win.title}</span>
          <span className="text-xs text-ink-muted tabular">
            Platz {win.rank}
            {win.verdict ? ' · KI-Kommentar' : ''}
          </span>
          <ChevronDown
            aria-hidden="true"
            className="size-4 shrink-0 -rotate-90 transition-transform group-expanded:rotate-0"
            strokeWidth={2.25}
          />
        </AriaButton>
      </Heading>
      <DisclosurePanel className="pb-2 pl-6">
        <CategoryWinDetails win={win} />
      </DisclosurePanel>
    </Disclosure>
  );
}
