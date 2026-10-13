/**
 * The single toast slot. This is the ONLY file that touches React Aria's
 * UNSTABLE_Toast API (stack.md: confine it to one file).
 *
 * Rules (UX audit §5/§7): at most one toast is visible; a new one replaces the old
 * one instead of stacking; it sits just above the controls / bottom bar (the layout
 * positions <ToastSlot>), never over the top bar or a sheet header. Clear it when the
 * state it talks about changes (`clearToasts()`), so no stale error outlives a success.
 */
import { CircleAlert, CircleCheck, Info, X, type LucideIcon } from 'lucide-react';
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

/** Mount once per app, where the layout wants the toast. */
export function ToastSlot({ className }: ToastSlotProps) {
  const surface = useSurface();
  return (
    <AriaToastRegion
      queue={queue}
      data-surface={surface}
      className={cx(
        'fixed inset-x-0 bottom-[max(1rem,env(safe-area-inset-bottom))] z-(--z-toast) mx-auto flex w-[min(100%-2rem,30rem)] flex-col bg-transparent outline-none',
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
