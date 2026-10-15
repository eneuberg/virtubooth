/**
 * The analysis on the Live screen: compact chips under each photo tile („3 Personen ·
 * 2 lächeln · Flasche, Becher“), and the switch „Analyse zeigen“ (remembered in this
 * browser) that turns chips, frames and the viewer's analysis block on and off. The
 * full analysis (frames on the photo, objects with score and source, details, property
 * scores) is the manage area's {@link AnalysisPanel}, shown in the photo viewer.
 *
 * Summaries come in batches (summaryBatch.ts); the admin event `photo.analyzed`
 * refreshes exactly the photos it names (store/applyEvent.ts), so nothing polls.
 * Everything renders nothing while the wall extension is off on this server.
 */
import { Sparkles } from 'lucide-react';
import { cx } from '@/ui/cx';
import { Switch } from '@/ui/Switch';
import { useWallEnabled } from './hooks';
import { useAnalysisSummary, useLiveAnalysis, useShowAnalysis } from './liveAnalysisState';
import { analysisChips, chipsLabel, type ChipTone } from './summaryText';

/** The header switch; nothing while the wall extension is off. */
export function AnalysisToggle({ className }: { className?: string }) {
  const enabled = useWallEnabled();
  const show = useShowAnalysis((s) => s.show);
  const setShow = useShowAnalysis((s) => s.setShow);
  if (enabled !== true) return null;
  return (
    <Switch isSelected={show} onChange={setShow} className={className} data-testid="analysis-toggle">
      Analyse zeigen
    </Switch>
  );
}

const CHIP: Record<ChipTone, string> = {
  plain: 'bg-surface-sunk text-ink',
  muted: 'text-ink-muted ring-1 ring-line ring-inset',
  mark: 'text-mark ring-1 ring-current ring-inset',
  win: 'bg-accent-tint text-ink',
};

/** The chips under one tile (nothing while the analysis is hidden or off). */
export function AnalysisChips({ photoId, className }: { photoId: string; className?: string }) {
  const show = useLiveAnalysis();
  const { data } = useAnalysisSummary(photoId, show);
  if (!show || !data) return null;
  const chips = analysisChips(data);
  return (
    <ul
      className={cx('flex flex-wrap gap-1', className)}
      aria-label={`Analyse: ${chipsLabel(chips)}`}
      data-testid="analysis-chips"
      data-state={data.state}
    >
      {chips.map((chip) => (
        <li
          key={chip.id}
          data-chip={chip.id}
          className={cx(
            'inline-flex h-5.5 max-w-full items-center gap-1 rounded-small px-1.5 text-xs leading-none font-semibold',
            CHIP[chip.tone],
          )}
        >
          {chip.id === 'objects' && data.objects.some((o) => o.source !== 'local') ? (
            <Sparkles aria-hidden="true" className="size-3 shrink-0" strokeWidth={2.25} />
          ) : null}
          <span className="truncate">{chip.text}</span>
        </li>
      ))}
    </ul>
  );
}

/** The categories the open photo wins right now (the viewer, above the full analysis). */
export function AnalysisWins({ photoId }: { photoId: string }) {
  const show = useLiveAnalysis();
  const { data } = useAnalysisSummary(photoId, show);
  if (!show || !data || data.wins.length === 0) return null;
  return (
    <section
      aria-labelledby="analysis-wins-title"
      className="grid gap-2 border-t border-line pt-3"
      data-testid="analysis-wins"
    >
      <h3 id="analysis-wins-title" className="text-md font-bold">
        Kategorien
      </h3>
      <ul className="grid gap-1 text-sm">
        {data.wins.map((win) => (
          <li key={win.id} className="flex items-center gap-2">
            <span aria-hidden="true">{win.emoji}</span>
            <span className="min-w-0 flex-1 truncate font-semibold">{win.title}</span>
            <span className="text-xs text-ink-muted">{win.verdict ? 'Urteil der KI' : 'gewinnt gerade'}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
