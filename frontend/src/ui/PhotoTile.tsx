import type { ReactNode } from 'react';
import { Button as AriaButton } from 'react-aria-components';
import { Checkbox } from './Checkbox';
import { cx } from './cx';
import { GreaseCircle, GreaseX } from './GreaseMarks';
import { Spinner } from './Spinner';

export interface PhotoTileProps {
  src: string;
  alt: string;
  /** intrinsic size for layout stability; photos are 3:4 */
  width?: number;
  height?: number;
  /** frame label, e.g. "Bier 0032" (frameLabel() in lib/format) */
  label: ReactNode;
  /** second caption line, e.g. the guest's name */
  sublabel?: ReactNode;
  /** grease-pencil X, photo dimmed */
  isHidden?: boolean;
  /** grease-pencil circle */
  isSelected?: boolean;
  /** a fresh frame: plays the develop animation once */
  isNew?: boolean;
  /** a request on this photo is running */
  isBusy?: boolean;
  /** makes the photo a button (open viewer / inspector) */
  onOpen?: () => void;
  openLabel?: string;
  /** bottom-right corner over the photo, e.g. the hide toggle <IconButton variant="overlay"> */
  overlay?: ReactNode;
  /** a checkbox over the top-left corner (manage selection) */
  selection?: { isSelected: boolean; onChange: (isSelected: boolean) => void; label: string };
  hiddenLabel?: string;
  loading?: 'lazy' | 'eager';
  className?: string;
  'data-testid'?: string;
}

/**
 * A frame on the contact sheet: square-cornered 3:4 photo plus a two-line caption.
 * Hidden = grease-pencil X (reversible mark); selected = grease circle.
 * Interactive parts (open, overlay toggle, checkbox) are siblings, never nested.
 */
export function PhotoTile({
  src,
  alt,
  width = 300,
  height = 400,
  label,
  sublabel,
  isHidden = false,
  isSelected = false,
  isNew = false,
  isBusy = false,
  onOpen,
  openLabel,
  overlay,
  selection,
  hiddenLabel = 'Ausgeblendet',
  loading = 'lazy',
  className,
  ...rest
}: PhotoTileProps) {
  const img = (
    <img
      src={src}
      alt={onOpen ? '' : alt}
      width={width}
      height={height}
      loading={loading}
      decoding="async"
      className={cx(
        'size-full object-cover transition-[opacity,filter] duration-(--duration-quick)',
        isHidden && 'opacity-40 grayscale-[0.6]',
        isNew && 'animate-develop',
      )}
    />
  );
  return (
    <figure
      data-testid={rest['data-testid']}
      data-hidden={isHidden || undefined}
      data-selected={isSelected || undefined}
      aria-busy={isBusy || undefined}
      className={cx('relative grid min-w-0 content-start gap-1.5', className)}
    >
      <div className="relative aspect-[3/4] overflow-hidden bg-surface-sunk">
        {onOpen ? (
          <AriaButton
            onPress={onOpen}
            aria-label={openLabel ?? alt}
            className="block size-full cursor-pointer outline-none focus-visible:outline-3 focus-visible:-outline-offset-3 focus-visible:outline-focus"
          >
            {img}
          </AriaButton>
        ) : (
          img
        )}
        {isHidden ? (
          <GreaseX key="x" animate className="pointer-events-none absolute inset-[6%] size-[88%] text-mark" />
        ) : null}
        {isBusy ? (
          <span className="absolute inset-0 grid place-items-center bg-black/40 text-white">
            <Spinner />
          </span>
        ) : null}
        {selection ? (
          <span className="absolute top-0 left-0 z-(--z-raised)">
            <Checkbox
              variant="tile"
              aria-label={selection.label}
              isSelected={selection.isSelected}
              onChange={selection.onChange}
            />
          </span>
        ) : null}
        {overlay ? <span className="absolute right-1 bottom-1 z-(--z-raised)">{overlay}</span> : null}
      </div>
      {isSelected ? (
        <GreaseCircle
          animate
          className="pointer-events-none absolute -top-[3%] -left-[5%] z-(--z-raised) aspect-[3/4.2] w-[110%] text-mark"
        />
      ) : null}
      <figcaption className="grid min-w-0 text-xs">
        <span className="truncate font-semibold tabular">{label}</span>
        {isHidden ? (
          <span className="truncate font-semibold text-mark">{hiddenLabel}</span>
        ) : sublabel ? (
          <span translate="no" className="truncate text-ink-muted">
            {sublabel}
          </span>
        ) : null}
      </figcaption>
    </figure>
  );
}
