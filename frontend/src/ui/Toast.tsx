/**
 * The single toast slot. This is the ONLY file that touches React Aria's
 * UNSTABLE_Toast API (stack.md: confine it to one file).
 *
 * Rules (UX audit §5/§7): at most one toast is visible; a new one replaces the old
 * one instead of stacking; it sits just above the controls / bottom bar (the layout
 * positions <ToastSlot>), never over the top bar or a sheet header. It never covers an
 * action area either (`toastAvoid`: a sheet's buttons, the viewer's panel, the
 * selection bar, the camera controls): it moves up above it (toastPlacement.ts). Clear
 * it when the state it talks about changes (`clearToasts()`), so no stale error
 * outlives a success.
 */
import { CircleAlert, CircleCheck, Info, X, type LucideIcon } from 'lucide-react';
import { useLayoutEffect, useState } from 'react';
import {
  Button as AriaButton,
  Text,
  UNSTABLE_Toast as AriaToast,
  UNSTABLE_ToastContent as AriaToastContent,
  UNSTABLE_ToastList as AriaToastList,
  UNSTABLE_ToastQueue as AriaToastQueue,
  UNSTABLE_ToastRegion as AriaToastRegion,
} from 'react-aria-components';
import { cx } from './cx';
import { useSurface } from './Surface';
import { measureToastLift } from './toastPlacement';

export type ToastTone = 'info' | 'success' | 'error';

export interface ToastAction {
  /** "Rückgängig", "Erneut senden" */
  label: string;
  onAction: () => void;
}

export interface ToastContent {
  message: string;
  tone?: ToastTone;
  action?: ToastAction;
}

export interface ShowToastOptions {
  /** ms; default 5 s, 6 s for errors, 7 s with an action */
  timeout?: number;
  onClose?: () => void;
}

const queue = new AriaToastQueue<ToastContent>({ maxVisibleToasts: 1 });

function defaultTimeout(content: ToastContent): number {
  if (content.action) return 7000;
  return content.tone === 'error' ? 6000 : 5000;
}

/** Shows a toast, replacing whatever is showing. Returns its key. */
export function showToast(content: ToastContent, options: ShowToastOptions = {}): string {
  queue.clear();
  return queue.add(content, {
    timeout: options.timeout ?? defaultTimeout(content),
    ...(options.onClose ? { onClose: options.onClose } : {}),
  });
}

export function closeToast(key: string): void {
  queue.close(key);
}

/** Removes any toast, e.g. when the state it reported has changed. */
export function clearToasts(): void {
  queue.clear();
}

const ICONS: Record<ToastTone, LucideIcon> = { info: Info, success: CircleCheck, error: CircleAlert };

export interface ToastSlotProps {
  /**
   * Fixed position of the slot. Default: bottom centre with a 16px gutter. Camera pages
   * pass the offset of their control row, admin pages the bottom bar height.
   */
  className?: string;
}

/**
 * Changes that can move an action area: a sheet opens or closes, a bar appears, a text
 * grows, a layout variable changes (`style`; the camera page sets its own sizes there).
 */
const WATCH: MutationObserverInit = {
  subtree: true,
  childList: true,
  characterData: true,
  attributes: true,
  attributeFilter: ['class', 'style', 'hidden', 'data-entering', 'data-exiting', 'data-toast-avoid'],
};

/**
 * While the toast shows: how far it has to move up to clear the action areas under it.
 * Measured before the first paint (it appears in its place) and again whenever a sheet
 * opens or finishes sliding in, a bar appears, or the window changes size.
 */
function useToastLift(region: HTMLElement | null): { lift: number; settled: boolean } {
  const [lift, setLift] = useState(0);
  // later moves glide; the first position is taken without a slide
  const [settled, setSettled] = useState(false);
  useLayoutEffect(() => {
    if (!region) return undefined;
    const doc = region.ownerDocument;
    const win = doc.defaultView ?? window;
    let frame = 0;
    const measure = () => {
      frame = 0;
      setLift(measureToastLift(region));
    };
    const schedule = () => {
      if (!frame) frame = win.requestAnimationFrame(measure);
    };
    measure();
    const settle = win.requestAnimationFrame(() => setSettled(true));
    const mutations = new MutationObserver(schedule);
    mutations.observe(doc.body, WATCH);
    const sizes = new ResizeObserver(schedule);
    sizes.observe(region);
    win.addEventListener('resize', schedule);
    win.visualViewport?.addEventListener('resize', schedule);
    // a sheet sliding in or a bar moving: measure where it ended up
    doc.addEventListener('animationend', schedule, true);
    doc.addEventListener('transitionend', schedule, true);
    return () => {
      win.cancelAnimationFrame(frame);
      win.cancelAnimationFrame(settle);
      mutations.disconnect();
      sizes.disconnect();
      win.removeEventListener('resize', schedule);
      win.visualViewport?.removeEventListener('resize', schedule);
      doc.removeEventListener('animationend', schedule, true);
      doc.removeEventListener('transitionend', schedule, true);
      setLift(0);
      setSettled(false);
    };
  }, [region]);
  return { lift, settled };
}

/** Mount once per app, where the layout wants the toast. */
export function ToastSlot({ className }: ToastSlotProps) {
  const surface = useSurface();
  // the region only exists while a toast shows
  const [region, setRegion] = useState<HTMLDivElement | null>(null);
  const { lift, settled } = useToastLift(region);
  return (
    <AriaToastRegion
      ref={setRegion}
      queue={queue}
      data-surface={surface}
      data-lifted={lift > 0 || undefined}
      data-settled={settled || undefined}
      style={lift > 0 ? { translate: `0 ${-lift}px` } : undefined}
      className={cx(
        'fixed inset-x-0 bottom-[max(1rem,env(safe-area-inset-bottom))] z-(--z-toast) mx-auto flex w-[min(100%-2rem,30rem)] flex-col bg-transparent outline-none',
        // the highest the toast may go when it moves up (read by measureToastLift)
        'scroll-mt-[max(0.5rem,env(safe-area-inset-top))]',
        'data-settled:transition-[translate] data-settled:duration-(--duration-quick) data-settled:ease-out',
        className,
      )}
    >
      <AriaToastList<ToastContent> className="m-0 flex list-none flex-col p-0">
        {({ toast }) => {
          const tone = toast.content.tone ?? 'info';
          const Icon = ICONS[tone];
          const { action } = toast.content;
          return (
            <AriaToast
              toast={toast}
              data-tone={tone}
              className="flex min-h-13 animate-toast-in items-center gap-2 rounded-control bg-toast py-1.5 pr-1.5 pl-4 text-on-toast shadow-float outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
            >
              <Icon aria-hidden="true" className="size-5 shrink-0" strokeWidth={2.25} />
              <AriaToastContent className="min-w-0 flex-1 py-2">
                <Text slot="title" className="block text-sm font-semibold">
                  {toast.content.message}
                </Text>
              </AriaToastContent>
              {action ? (
                <AriaButton
                  onPress={() => {
                    action.onAction();
                    queue.close(toast.key);
                  }}
                  className="h-10 shrink-0 cursor-pointer rounded-small px-3 text-sm font-bold text-toast-action underline underline-offset-3 outline-none hover:bg-black/5 focus-visible:outline-2 focus-visible:outline-focus"
                >
                  {action.label}
                </AriaButton>
              ) : null}
              <AriaButton
                slot="close"
                aria-label="Schließen"
                className="grid size-10 shrink-0 cursor-pointer place-items-center rounded-small opacity-70 outline-none hover:opacity-100 focus-visible:outline-2 focus-visible:outline-focus"
              >
                <X aria-hidden="true" className="size-5" />
              </AriaButton>
            </AriaToast>
          );
        }}
      </AriaToastList>
    </AriaToastRegion>
  );
}
