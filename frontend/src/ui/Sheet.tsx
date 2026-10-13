import { X } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Dialog, Heading, Modal, ModalOverlay } from 'react-aria-components';
import { cx } from './cx';
import { IconButton } from './IconButton';
import { useSurface } from './Surface';
import { toastAvoid } from './toastPlacement';

export interface SheetProps {
  isOpen?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (isOpen: boolean) => void;
  title: ReactNode;
  /** one line under the title */
  description?: ReactNode;
  children: ReactNode;
  /** sticky footer, usually the primary action */
  footer?: ReactNode;
  /** false for decisions that must be made (join): no close button, Esc and scrim do nothing */
  isDismissable?: boolean;
  /** desktop width; phones always get a full-width bottom sheet */
  size?: 'sm' | 'md' | 'lg';
  role?: 'dialog' | 'alertdialog';
  /** lg (21px) for tools, xl (27px) for a welcome like the join sheet */
  titleSize?: 'lg' | 'xl';
  closeLabel?: string;
  /** on the overlay root (stable hook for tests, e.g. "join") */
  'data-testid'?: string;
  className?: string;
  bodyClassName?: string;
}

const WIDTH = { sm: 'sm:max-w-[26rem]', md: 'sm:max-w-[32rem]', lg: 'sm:max-w-[40rem]' } as const;

/** Marks the body as "has more below" so the footer shows its edge (no scroll-driven CSS on iOS 16). */
function useMoreBelow() {
  const ref = useRef<HTMLDivElement>(null);
  const [more, setMore] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const check = () => setMore(el.scrollTop + el.clientHeight < el.scrollHeight - 2);
    check();
    el.addEventListener('scroll', check, { passive: true });
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => {
      el.removeEventListener('scroll', check);
      ro.disconnect();
    };
  }, []);
  return [ref, more] as const;
}

/**
 * Bottom sheet on phones, centred dialog from 640px. Focus is trapped and starts on the
 * dialog itself (so a phone keyboard does not pop up over the text); the footer stays
 * visible while the body scrolls. Built on React Aria Modal/Dialog with our own classes.
 * A toast never covers it: it moves above the sheet, or above the footer when the sheet
 * is as tall as the screen.
 */
export function Sheet({
  isOpen,
  defaultOpen,
  onOpenChange,
  title,
  description,
  children,
  footer,
  isDismissable = true,
  size = 'md',
  role = 'dialog',
  titleSize = 'lg',
  closeLabel = 'Schließen',
  className,
  bodyClassName,
  ...rest
}: SheetProps) {
  const surface = useSurface();
  const [bodyRef, more] = useMoreBelow();
  return (
    <ModalOverlay
      {...(isOpen === undefined ? {} : { isOpen })}
      {...(defaultOpen === undefined ? {} : { defaultOpen })}
      {...(onOpenChange ? { onOpenChange } : {})}
      isDismissable={isDismissable}
      isKeyboardDismissDisabled={!isDismissable}
      data-surface={surface}
      data-testid={rest['data-testid']}
      className={({ isEntering, isExiting }) =>
        cx(
          'vb-scrim fixed top-0 left-0 z-(--z-sheet) flex h-(--visual-viewport-height) w-full items-end justify-center bg-scrim sm:items-center sm:p-6',
          isEntering && 'animate-fade-in',
          isExiting && 'animate-fade-out',
        )
      }
    >
      <Modal
        className={({ isEntering, isExiting }) =>
          cx(
            'flex max-h-[calc(var(--visual-viewport-height)-1rem)] w-full outline-none sm:max-h-[calc(var(--visual-viewport-height)-3rem)]',
            WIDTH[size],
            isEntering && 'animate-sheet-in sm:animate-dialog-in',
            isExiting && 'animate-sheet-out sm:animate-fade-out',
          )
        }
      >
        <Dialog
          role={role}
          {...toastAvoid}
          className={cx(
            'vb-sheet flex max-h-full w-full flex-col rounded-t-control border-t border-line bg-surface-raised text-ink outline-none sm:rounded-control sm:border',
            className,
          )}
        >
          {({ close }) => (
            <>
              <span
                aria-hidden="true"
                className="mx-auto mt-2 h-1 w-9 shrink-0 rounded-full bg-line-strong sm:hidden"
              />
              <header className="flex shrink-0 items-start gap-2 pt-2 pr-2 pl-5 sm:pt-3">
                <div className="min-w-0 flex-1 py-2.5">
                  <Heading
                    slot="title"
                    className={cx(titleSize === 'xl' ? 'text-xl' : 'text-lg', 'font-bold')}
                  >
                    {title}
                  </Heading>
                  {description ? <p className="mt-1 text-sm text-ink-muted">{description}</p> : null}
                </div>
                {isDismissable ? <IconButton label={closeLabel} icon={X} onPress={close} /> : null}
              </header>
              <div
                ref={bodyRef}
                className={cx(
                  'min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pt-2 pb-5',
                  bodyClassName,
                )}
              >
                {children}
              </div>
              {footer ? (
                <div
                  {...toastAvoid}
                  data-more={more || undefined}
                  className="shrink-0 border-t border-transparent px-5 pt-3 pb-[max(1rem,env(safe-area-inset-bottom))] data-more:border-line"
                >
                  {footer}
                </div>
              ) : null}
            </>
          )}
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
}
