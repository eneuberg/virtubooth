/**
 * The analysis on the Live screen: the frames of the objects, faces and hands on each
 * photo tile (mapped onto the tile's 3:4 crop, tileFrames.ts; one colour per kind of
 * thing, labelColors.ts, so no legend), compact chips under it
 * („3 Personen · 2 lächeln · Flasche, Becher“), and the switch „Analyse zeigen“
 * (remembered in this browser) that turns frames, chips and
 * the viewer's analysis block on and off. The
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
import { labelColor } from './labelColors';
import { useAnalysisSummary, useLiveAnalysis, useShowAnalysis } from './liveAnalysisState';
import { analysisChips, chipsLabel, type ChipTone } from './summaryText';
import { frameStyle, tileFrames } from './tileFrames';

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

/**
 * The frames on one tile's thumbnail (inside PhotoTile's photo frame); `aspect` is the
 * photo's width / height. Nothing while the analysis is hidden or off.
 */
export function AnalysisTileFrames({ photoId, aspect }: { photoId: string; aspect: number }) {
  const show = useLiveAnalysis();
  const { data } = useAnalysisSummary(photoId, show);
  if (!show || !data) return null;
  const frames = tileFrames(data, aspect);
  if (frames.length === 0) return null;
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0" data-testid="tile-frames">
      {frames.map((f, i) => {
        const { color, text } = labelColor(f.key);
        return (
          <div
            // frames have no id; their order is stable for one summary
            // oxlint-disable-next-line react/no-array-index-key
            key={i}
            data-testid="tile-frame"
            data-kind={f.kind}
            data-key={f.key}
            className="absolute rounded-[2px] border-2 shadow-[0_0_0_1px_rgb(0_0_0/0.35)]"
            style={{ ...frameStyle(f), borderColor: color }}
          >
            {f.label ? (
              <span
                className="absolute -top-px -left-px max-w-[calc(100%+2px)] truncate px-0.5 text-[0.625rem] leading-3.5 font-semibold"
                style={{ backgroundColor: color, color: text }}
              >
                {f.label}
              </span>
            ) : null}
          </div>
        );
      })}
    </div>
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
          {chip.id === 'objects' && data.objects.some((o) => o.sources.some((s) => s !== 'local')) ? (
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
