/**
 * The analysis on the Live screen: the frames of the objects, faces and hands on each
 * photo tile (mapped onto the tile's 3:4 crop, tileFrames.ts; one colour per kind of
 * thing, labelColors.ts, so no legend), compact chips under it
 * („3 Personen · 2 lächeln · Flasche, Becher“) in a fixed two-row area (no layout shift,
 * „+N“ for the rest), and the switch „Analyse zeigen“
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
import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { formatNumber } from '@/lib/format';
import { cx } from '@/ui/cx';
import { Switch } from '@/ui/Switch';
import { WinChipButton, WinDisclosure } from './CategoryWinDetails';
import { useWallEnabled } from './hooks';
import { labelColor } from './labelColors';
import { useAnalysisSummary, useLiveAnalysis, useShowAnalysis } from './liveAnalysisState';
import { fitChips } from './chipFit';
import { analysisChips, type Chip, chipsLabel, type ChipTone } from './summaryText';
import { frameStyle, tileFrames } from './tileFrames';
import type { PhotoAnalysisSummary } from './types';

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

/** Rows of chips the area under a Live tile holds (its height, see CHIP_AREA). */
export const CHIP_ROWS = 2;
/** CHIP_ROWS chips of h-5.5 with gap-1 between: 2 × 1.375rem + 0.25rem */
const CHIP_AREA = 'h-12';
const CHIP_BASE =
  'inline-flex h-5.5 max-w-full shrink-0 items-center gap-1 rounded-small px-1.5 text-xs leading-none font-semibold whitespace-nowrap';

function ChipItem({ chip, data }: { chip: Chip; data: PhotoAnalysisSummary }) {
  return (
    <>
      {chip.id === 'objects' && data.objects.some((o) => o.sources.some((s) => s !== 'local')) ? (
        <Sparkles aria-hidden="true" className="size-3 shrink-0" strokeWidth={2.25} />
      ) : null}
      <span className="truncate">{chip.text}</span>
    </>
  );
}

/**
 * The chips under one tile, in a fixed area of {@link CHIP_ROWS} rows that is there
 * whenever the wall extension is loaded, also while „Analyse zeigen“ is off or the
 * analysis has not arrived (then empty): switching or a photo getting analysed never
 * moves the grid. Chips that do not fit end in „+N“ (chipFit.ts).
 */
export function AnalysisChips({ photoId, className }: { photoId: string; className?: string }) {
  const enabled = useWallEnabled();
  const show = useLiveAnalysis();
  const { data } = useAnalysisSummary(photoId, show);
  if (enabled !== true) return null;
  return (
    <div className={cx('relative min-w-0 overflow-hidden', CHIP_AREA, className)} data-testid="chip-area">
      {show && data ? <ChipRows data={data} /> : null}
    </div>
  );
}

function ChipRows({ data }: { data: PhotoAnalysisSummary }) {
  const chips = useMemo(() => analysisChips(data), [data]);
  const list = useRef<HTMLUListElement>(null);
  const ruler = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(chips.length);

  useLayoutEffect(() => {
    const area = list.current;
    const sizes = ruler.current;
    if (!area || !sizes) return undefined;
    const fit = () => {
      // the ruler: each chip, then the widest „+N“
      const widths = [...sizes.children].map((el) => Math.ceil(el.getBoundingClientRect().width));
      const more = widths[chips.length] ?? 0;
      const gap = Number.parseFloat(getComputedStyle(area).columnGap) || 0;
      setShown(fitChips(widths.slice(0, chips.length), area.clientWidth, gap, CHIP_ROWS, more));
    };
    fit();
    if (typeof ResizeObserver !== 'function') return undefined;
    let frame = 0;
    // next frame: layout changes inside the callback make WebKit report a ResizeObserver loop
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(fit);
    });
    observer.observe(area);
    observer.observe(sizes); // web font arriving
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [chips]);

  const count = Math.min(shown, chips.length);
  const rest = chips.length - count;
  return (
    <>
      {/* the chips at their natural width, for fitChips; never seen */}
      <div
        ref={ruler}
        aria-hidden="true"
        className="pointer-events-none invisible absolute top-0 left-0 flex w-max gap-1"
      >
        {chips.map((chip) => (
          <span key={chip.id} className={cx(CHIP_BASE, CHIP[chip.tone])}>
            <ChipItem chip={chip} data={data} />
            {chip.win ? <span className="size-3 shrink-0" /> : null}
          </span>
        ))}
        <span className={cx(CHIP_BASE, CHIP.muted)}>+{formatNumber(chips.length)}</span>
      </div>
      <ul
        ref={list}
        className="flex h-full flex-wrap content-start gap-1"
        aria-label={`Analyse: ${chipsLabel(chips)}`}
        data-testid="analysis-chips"
        data-state={data.state}
      >
        {chips.slice(0, count).map((chip) =>
          chip.win ? (
            <li key={chip.id} data-chip={chip.id} className="flex max-w-full min-w-0">
              <WinChipButton win={chip.win} className={cx(CHIP_BASE, CHIP[chip.tone])}>
                <ChipItem chip={chip} data={data} />
              </WinChipButton>
            </li>
          ) : (
            <li key={chip.id} data-chip={chip.id} className={cx(CHIP_BASE, CHIP[chip.tone])}>
              <ChipItem chip={chip} data={data} />
            </li>
          ),
        )}
        {rest > 0 ? (
          <li data-chip="more" className={cx(CHIP_BASE, CHIP.muted)} title={chipsLabel(chips.slice(count))}>
            +{formatNumber(rest)}
          </li>
        ) : null}
      </ul>
    </>
  );
}

/** The categories the open photo wins right now (the viewer, above the full analysis); each opens. */
export function AnalysisWins({ photoId }: { photoId: string }) {
  const show = useLiveAnalysis();
  const { data } = useAnalysisSummary(photoId, show);
  if (!show || !data || data.wins.length === 0) return null;
  return (
    <section
      aria-labelledby="analysis-wins-title"
      className="grid gap-1 border-t border-line pt-3"
      data-testid="analysis-wins"
    >
      <h3 id="analysis-wins-title" className="text-md font-bold">
        Kategorien
      </h3>
      <div className="grid">
        {data.wins.map((win) => (
          <WinDisclosure key={win.id} win={win} />
        ))}
      </div>
    </section>
  );
}
