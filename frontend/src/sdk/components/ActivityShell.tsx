/**
 * The page frame for camera activities (Beer Cam, Fotobox). OWNER: wave 2 "AC".
 * Black stage, top bar, edge-to-edge 3:4 stage, film edge, one hint line, the control
 * row, and the single toast slot just above the controls (UX audit §5 wireframes,
 * docs/overhaul/design/mockups/02-beer.html, 03-booth.html).
 *
 * Layouts:
 *   portrait phone:   bar / stage (full width) / film edge / hint + controls centred in the rest
 *   short (≤ 700 px): the bar lies over the stage top (a gradient, like a camera app); the
 *                     film edge stays under it: it never covers the photo's bottom (the
 *                     bottle's foot is there)
 *   landscape phone:  stage left at full height; bar, film edge, hint, controls on the right
 *   desktop:          one centred column, the stage limited by the height
 * The stage keeps 3:4 in every layout; it is the photo (WYSIWYG).
 */
import { ChevronLeft } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, type ReactNode } from 'react';
import { Link } from 'react-aria-components';
import { cx } from '@/ui/cx';
import { iconButtonStyles } from '@/ui/IconButton';
import { ToastSlot } from '@/ui/Toast';
import { toastAvoid } from '@/ui/toastPlacement';

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
  /** one short line (or a short result headline) above the controls */
  hint?: ReactNode;
  /** camera: [left] [shutter] [right]; actions: buttons side by side */
  controls: ReactNode;
  controlsLayout?: 'camera' | 'actions';
  /** keep the stage size while true (the result print replaces the strip: no jump);
   * it only shrinks if the result needs more room than the camera did */
  holdLayout?: boolean;
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
 * Stage width = min(full width, (viewport height − everything else) × 3/4). "Everything
 * else" (bar, film edge, strip, hint, controls) is measured (--vb-reserve, set by a
 * ResizeObserver), so a two-line hint or the filter strip never pushes the controls
 * off screen; the fallback covers the first frame. Short screens: the bar lies over the
 * stage and doesn't count. Landscape phones: the stage takes the full height instead.
 */
const STAGE_W = 'w-[min(100%,calc((100dvh-var(--vb-reserve,15.75rem))*0.75))]';

/** Keeps --vb-reserve on the root equal to the height of everything but the stage. */
function useReserve(hold: boolean) {
  const holding = useRef(hold);
  // before the browser lays out the print (and the ResizeObserver reports it)
  useLayoutEffect(() => {
    holding.current = hold;
  }, [hold]);
  const root = useRef<HTMLElement | null>(null);
  const header = useRef<HTMLElement | null>(null);
  const film = useRef<HTMLDivElement | null>(null);
  const lower = useRef<HTMLDivElement | null>(null);
  const lowerInner = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const els = [header.current, film.current, lower.current, lowerInner.current];
    if (!root.current || typeof ResizeObserver === 'undefined') return undefined;
    let current = 0;
    const measure = () => {
      const bar = header.current;
      const overlaid = bar ? getComputedStyle(bar).position === 'absolute' : true;
      let px = overlaid || !bar ? 0 : bar.getBoundingClientRect().height;
      px += film.current?.getBoundingClientRect().height ?? 0;
      if (lower.current && lowerInner.current) {
        const style = getComputedStyle(lower.current);
        px += lowerInner.current.getBoundingClientRect().height;
        px += Number.parseFloat(style.paddingTop) + Number.parseFloat(style.paddingBottom);
      }
      const next = Math.ceil(px);
      // while holding (a print is shown) the stage may shrink to fit more, never grow
      if (holding.current && next <= current) return;
      current = next;
      root.current?.style.setProperty('--vb-reserve', `${next}px`);
    };
    // measure in the next frame, not inside the observer's callback: the new
    // --vb-reserve resizes observed boxes again, which Safari reports as an error
    // ("ResizeObserver loop completed with undelivered notifications")
    let frame = 0;
    const observer = new ResizeObserver(() => {
      frame ||= requestAnimationFrame(() => {
        frame = 0;
        measure();
      });
    });
    for (const el of els) if (el) observer.observe(el);
    observer.observe(root.current);
    measure();
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, []);
  return { root, header, film, lower, lowerInner };
}

export function ActivityShell({
  title,
  heading,
  topRight,
  stage,
  filmEdge,
  strip,
  hint,
  controls,
  controlsLayout = 'camera',
  holdLayout = false,
  children,
  backHref = '/',
  backLabel = 'Zurück zum Start',
  stageTestId,
  rootProps,
  className,
}: ActivityShellProps) {
  const { root, header, film, lower, lowerInner } = useReserve(holdLayout);
  return (
    // the page's main landmark: an activity is the whole page
    <main
      ref={root}
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
        ref={header}
        {...toastAvoid}
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
        {/* the title (the activity switcher) keeps its width; the guest pass takes
            what is left and shortens a long pseudonym ("Schickes Erdmännchen") */}
        <div className="min-w-0 flex-[0_1_auto]">{title}</div>
        {topRight ? <div className="flex min-w-11 flex-1 justify-end">{topRight}</div> : null}
      </header>

      <div
        data-testid={stageTestId}
        className={cx(
          'relative mx-auto aspect-[3/4] overflow-hidden bg-black select-none',
          STAGE_W,
          'short:row-start-1',
          'landscape-phone:col-start-1 landscape-phone:row-span-full landscape-phone:row-start-1 landscape-phone:h-dvh landscape-phone:w-auto landscape-phone:max-w-[60vw] landscape-phone:pl-[env(safe-area-inset-left)]',
        )}
      >
        {stage}
      </div>

      {filmEdge ? (
        <div
          ref={film}
          className={cx(
            'mx-auto w-full',
            STAGE_W,
            'short:row-start-2',
            'landscape-phone:col-start-2 landscape-phone:row-start-2 landscape-phone:w-full',
          )}
        >
          {filmEdge}
        </div>
      ) : null}

      <div
        ref={lower}
        className={cx(
          'mx-auto grid w-full max-w-[32rem] min-w-0 [align-content:safe_center] pt-1 pb-[max(0.75rem,env(safe-area-inset-bottom))]',
          'short:row-start-3 short:pt-1',
          'landscape-phone:col-start-2 landscape-phone:row-start-3 landscape-phone:max-w-none landscape-phone:content-end landscape-phone:pr-[max(1rem,env(safe-area-inset-right))]',
          'fine:pb-6',
        )}
      >
        <div ref={lowerInner} className="grid min-w-0 gap-3 short:gap-2">
          {/* strip, hint and controls are action areas: a toast moves above them (and
              stays under the header) */}
          {strip ? (
            <div className="min-w-0" {...toastAvoid}>
              {strip}
            </div>
          ) : null}
          {hint ? (
            <div
              {...toastAvoid}
              className="px-4 text-center text-md empty:hidden landscape-phone:text-left"
              data-testid="hint-row"
            >
              {hint}
            </div>
          ) : null}
          <div
            {...toastAvoid}
            className={cx(
              'px-4',
              controlsLayout === 'camera'
                ? 'grid grid-cols-[1fr_auto_1fr] items-center gap-3 [&>:first-child]:justify-self-start [&>:last-child]:justify-self-end'
                : 'flex w-full max-w-[32rem] gap-3 landscape-phone:max-w-[30rem]',
            )}
          >
            {controls}
          </div>
        </div>
      </div>

      <ToastSlot className="bottom-[calc(7.25rem+env(safe-area-inset-bottom))] landscape-phone:right-4 landscape-phone:left-auto landscape-phone:mx-0 landscape-phone:w-[min(100%-2rem,26rem)] fine:bottom-[calc(8.5rem+env(safe-area-inset-bottom))]" />
      {children}
    </main>
  );
}
