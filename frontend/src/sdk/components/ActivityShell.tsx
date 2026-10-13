/**
 * The page frame for camera activities (Beer Cam, Fotobox). OWNER: wave 2 "AC".
 * Black stage, top bar, edge-to-edge 3:4 stage, film edge, one hint line, the control
 * row, and the single toast slot just above the controls (UX audit §5 wireframes,
 * docs/overhaul/design/mockups/02-beer.html, 03-booth.html).
 *
 * Layouts:
 *   portrait phone:   bar / stage (full width) / film edge / hint + controls centred in the rest
 *   short (≤ 700 px): the bar and the film edge lie over the stage (360×640 keeps a big stage)
 *   landscape phone:  stage left at full height; bar, film edge, hint, controls on the right
 *   desktop:          one centred column, the stage limited by the height
 * The stage keeps 3:4 in every layout; it is the photo (WYSIWYG).
 */
import { ChevronLeft } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-aria-components';
import { cx } from '@/ui/cx';
import { iconButtonStyles } from '@/ui/IconButton';
import { ToastSlot } from '@/ui/Toast';

export interface ActivityShellProps {
  /** the title area, normally <ActivityMenu currentId title /> */
  title: ReactNode;
  /** the page's h1 for screen readers ("Beer Cam") */
  heading: string;
  /** top right: the compact guest pass */
  topRight?: ReactNode;
  /** the 3:4 camera preview or the result print (fills the stage box) */
  stage: ReactNode;
  /** <FilmEdge> under the stage */
  filmEdge?: ReactNode;
  /** a row between film edge and hint (the Fotobox filter strip) */
  strip?: ReactNode;
  /**
   * the height kept free under the stage: 'strip' for pages with a filter strip, also
   * while the strip is hidden (the result), so the stage never jumps
   */
  reserve?: 'camera' | 'strip';
  /** one short line (or a short result headline) above the controls */
  hint?: ReactNode;
  /** camera: [left] [shutter] [right]; actions: buttons side by side */
  controls: ReactNode;
  controlsLayout?: 'camera' | 'actions';
  /** extra content outside the grid (dialogs) */
  children?: ReactNode;
  backHref?: string;
  backLabel?: string;
  stageTestId?: string;
  /** data-* attributes for the root (state for tests and styling) */
  rootProps?: Record<`data-${string}`, string | undefined>;
  className?: string;
}

/*
 * Stage width = min(full width, the height left for it × 3/4). Reserved height:
 *   camera: 56 bar + 46 film edge + 150 hint/controls        = 252 px (15.75rem)
 *   strip:  56 + 46 + 110 strip and name + 12 + 80 shutter + 12 = 316 px (19.75rem)
 * Short screens: bar and film edge overlay the stage, so only hint/controls (+ strip).
 * Desktop leaves a little more room under the controls for the key hint.
 */
const STAGE_W = {
  camera:
    'w-[min(100%,calc((100dvh-15.75rem)*0.75))] short:w-[min(100%,calc((100dvh-10rem)*0.75))] fine:w-[min(100%,calc((100dvh-17rem)*0.75))]',
  strip:
    'w-[min(100%,calc((100dvh-19.75rem)*0.75))] short:w-[min(100%,calc((100dvh-14rem)*0.75))] fine:w-[min(100%,calc((100dvh-22rem)*0.75))]',
} as const;

export function ActivityShell({
  title,
  heading,
  topRight,
  stage,
  filmEdge,
  strip,
  reserve,
  hint,
  controls,
  controlsLayout = 'camera',
  children,
  backHref = '/',
  backLabel = 'Zurück zum Start',
  stageTestId,
  rootProps,
  className,
}: ActivityShellProps) {
  const stageWidth = STAGE_W[reserve ?? (strip ? 'strip' : 'camera')];
  return (
    <div
      data-surface="dark"
      {...rootProps}
      className={cx(
        'vb-activity relative grid h-dvh grid-cols-[minmax(0,1fr)] grid-rows-[auto_auto_auto_minmax(0,1fr)] overflow-hidden bg-kamera text-papier',
        'short:grid-rows-[auto_auto_minmax(0,1fr)]',
        'landscape-phone:grid-cols-[auto_minmax(0,1fr)] landscape-phone:grid-rows-[auto_auto_minmax(0,1fr)]',
        className,
      )}
    >
      <h1 className="sr-only" translate="no">
        {heading}
      </h1>
      <header
        className={cx(
          'z-(--z-sticky) box-content flex h-14 min-w-0 items-center gap-1 px-2 pt-[env(safe-area-inset-top)]',
          'short:absolute short:inset-x-0 short:top-0 short:bg-linear-to-b short:from-black/70 short:to-transparent',
          'landscape-phone:static landscape-phone:col-start-2 landscape-phone:bg-none landscape-phone:pr-[max(0.5rem,env(safe-area-inset-right))]',
          'fine:px-4',
        )}
      >
        <Link
          href={backHref}
          aria-label={backLabel}
          data-testid="back"
          className={iconButtonStyles({ variant: 'plain' })}
        >
          <ChevronLeft aria-hidden="true" className="size-7" strokeWidth={2} />
        </Link>
        <div className="min-w-0 flex-1">{title}</div>
        {topRight ? <div className="flex min-w-0 shrink justify-end">{topRight}</div> : null}
      </header>

      <div
        data-testid={stageTestId}
        className={cx(
          'relative mx-auto aspect-[3/4] overflow-hidden bg-black select-none',
          stageWidth,
          'short:row-start-1',
          'landscape-phone:col-start-1 landscape-phone:row-span-full landscape-phone:row-start-1 landscape-phone:h-dvh landscape-phone:w-auto landscape-phone:max-w-[60vw] landscape-phone:pl-[env(safe-area-inset-left)]',
        )}
      >
        {stage}
        {filmEdge ? (
          <div className="absolute inset-x-0 bottom-0 z-(--z-raised) hidden bg-black/70 short:block landscape-phone:hidden">
            {filmEdge}
          </div>
        ) : null}
      </div>

      {filmEdge ? (
        <div
          className={cx(
            'mx-auto w-full short:hidden',
            stageWidth,
            'landscape-phone:col-start-2 landscape-phone:row-start-2 landscape-phone:block landscape-phone:w-full',
          )}
        >
          {filmEdge}
        </div>
      ) : null}

      <div
        className={cx(
          'mx-auto grid w-full max-w-[32rem] min-w-0 content-center gap-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]',
          'short:gap-2 short:pt-2',
          'landscape-phone:col-start-2 landscape-phone:row-start-3 landscape-phone:max-w-none landscape-phone:content-end landscape-phone:pr-[max(1rem,env(safe-area-inset-right))]',
          'fine:pb-6',
        )}
      >
        {strip ? <div className="min-w-0">{strip}</div> : null}
        {hint ? (
          <div
            className="px-4 text-center text-md empty:hidden landscape-phone:text-left"
            data-testid="hint-row"
          >
            {hint}
          </div>
        ) : null}
        <div
          className={cx(
            'px-4',
            controlsLayout === 'camera'
              ? 'grid grid-cols-[1fr_auto_1fr] items-center gap-3 [&>:first-child]:justify-self-start [&>:last-child]:justify-self-end'
              : 'grid grid-cols-2 gap-3',
          )}
        >
          {controls}
        </div>
      </div>

      <ToastSlot className="bottom-[calc(7.25rem+env(safe-area-inset-bottom))] landscape-phone:right-4 landscape-phone:left-auto landscape-phone:mx-0 landscape-phone:w-[min(100%-2rem,26rem)] fine:bottom-[calc(8.5rem+env(safe-area-inset-bottom))]" />
      {children}
    </div>
  );
}
