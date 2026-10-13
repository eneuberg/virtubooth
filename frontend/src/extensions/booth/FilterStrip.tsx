/**
 * The filter carousel: swatches of the guest's own picture, the selected one centred
 * with a Safelight frame and its name underneath (only that name: the strip stays
 * calm, nothing covers the face). A listbox: arrows move and select (wrapping), a tap
 * selects. UX audit §5 (Fotobox), mockups/03-booth.html.
 */
import { useEffect, useRef } from 'react';
import { ListBox, ListBoxItem } from 'react-aria-components';
import type { Filter } from '@/sdk/camera/filters';
import { cx } from '@/ui/cx';

export interface FilterStripProps {
  filters: ReadonlyArray<Filter>;
  selectedId: string;
  onSelect: (id: string) => void;
  swatches: ReadonlyMap<string, string>;
  isDisabled?: boolean;
}

function reducedMotion(): boolean {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

export function FilterStrip({ filters, selectedId, onSelect, swatches, isDisabled }: FilterStripProps) {
  const listRef = useRef<HTMLDivElement | null>(null);
  const first = useRef(true);

  // keep the selected swatch in the middle (instantly on the first render)
  useEffect(() => {
    const list = listRef.current;
    const item = list?.querySelector<HTMLElement>(`[data-filter="${CSS.escape(selectedId)}"]`);
    if (!list || !item) return;
    const box = list.getBoundingClientRect();
    const at = item.getBoundingClientRect();
    const left = list.scrollLeft + (at.left - box.left) - (box.width - at.width) / 2;
    list.scrollTo({ left, behavior: first.current || reducedMotion() ? 'auto' : 'smooth' });
    first.current = false;
  }, [selectedId]);

  const selected = filters.find((f) => f.id === selectedId);
  return (
    <div className="grid gap-1">
      <ListBox
        ref={listRef}
        aria-label="Filter"
        data-testid="filter-strip"
        orientation="horizontal"
        selectionMode="single"
        selectionBehavior="replace"
        disallowEmptySelection
        shouldFocusWrap
        selectedKeys={[selectedId]}
        onSelectionChange={(keys) => {
          if (keys === 'all') return;
          const [key] = [...keys];
          if (key !== undefined) onSelect(String(key));
        }}
        {...(isDisabled ? { disabledKeys: filters.map((f) => f.id) } : {})}
        className={cx(
          'flex snap-x snap-mandatory gap-2 overflow-x-auto overscroll-x-contain py-1 outline-none',
          // the first and the last swatch can sit in the middle
          '[scrollbar-width:none] px-[calc(50%-1.625rem)] [&::-webkit-scrollbar]:hidden',
        )}
      >
        {filters.map((filter) => {
          const url = swatches.get(filter.id);
          return (
            <ListBoxItem
              key={filter.id}
              id={filter.id}
              textValue={filter.name}
              data-filter={filter.id}
              data-testid={`filter-${filter.id}`}
              className={cx(
                'relative h-17.5 w-13 shrink-0 cursor-pointer snap-center overflow-hidden bg-rot-950 outline-none',
                // the frame lies over the swatch picture
                "after:pointer-events-none after:absolute after:inset-0 after:ring-1 after:ring-white/25 after:content-[''] after:ring-inset",
                'selected:after:ring-3 selected:after:ring-accent',
                'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
                'disabled:cursor-not-allowed disabled:opacity-60',
              )}
            >
              {url ? (
                <img
                  src={url}
                  alt=""
                  width={52}
                  height={70}
                  className="pointer-events-none size-full object-cover motion-ok:animate-develop"
                />
              ) : (
                <span aria-hidden="true" className="grid size-full place-items-center text-xl">
                  {filter.icon}
                </span>
              )}
              <span className="sr-only">{filter.name}</span>
            </ListBoxItem>
          );
        })}
      </ListBox>
      <p data-testid="filter-name" aria-live="polite" className="text-center text-md font-semibold">
        {selected?.name ?? ''}
      </p>
    </div>
  );
}
