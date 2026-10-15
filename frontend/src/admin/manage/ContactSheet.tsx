import type { KeyboardEvent } from 'react';
import { GridList, GridListItem, type Selection } from 'react-aria-components';
import type { AdminPhoto } from '@/api/types';
import { Checkbox } from '@/ui/Checkbox';
import { cx } from '@/ui/cx';
import { GreaseCircle, GreaseX } from '@/ui/GreaseMarks';
import { photoLabel } from '../lib/labels';
import { arrivedLive } from '../store/applyEvent';
import { guestName } from '../hostGuest/marks';

export interface ContactSheetProps {
  photos: ReadonlyArray<AdminPhoto>;
  selected: ReadonlySet<string>;
  onSelectionChange: (ids: Set<string>) => void;
  /** Enter / click: show it in the inspector (desktop) or the viewer (phone) */
  onOpen: (photo: AdminPhoto) => void;
  /** the photo in the inspector */
  currentId: string | null;
  /** X on a focused frame */
  onToggleHidden: (photo: AdminPhoto) => void;
  /** Entf / Backspace: delete the selection, or the focused frame */
  onDelete: (photos: AdminPhoto[]) => void;
}

function toIds(selection: Selection, photos: ReadonlyArray<AdminPhoto>): Set<string> {
  if (selection === 'all') return new Set(photos.map((p) => p.id));
  return new Set([...selection].map(String));
}

/**
 * The dense contact sheet of the manage area: a grid of frames with keyboard navigation
 * (arrows in two dimensions), multiple selection (checkbox, Space, Shift-click for a
 * range, Ctrl+A) and the grease marks: X = hidden, circle = selected.
 * Shortcuts on a focused frame: Enter opens it, X hides/unhides, Entf deletes (asks).
 */
export function ContactSheet({
  photos,
  selected,
  onSelectionChange,
  onOpen,
  currentId,
  onToggleHidden,
  onDelete,
}: ContactSheetProps) {
  const byId = new Map(photos.map((p) => [p.id, p]));
  const selecting = selected.size > 0;

  const onKeyDownCapture = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const target = event.target instanceof HTMLElement ? event.target : null;
    const id = target?.closest<HTMLElement>('[data-photo-id]')?.dataset['photoId'];
    const photo = id ? byId.get(id) : undefined;
    if (!photo) return;
    if (event.key === 'x' || event.key === 'X') {
      event.preventDefault();
      event.stopPropagation();
      onToggleHidden(photo);
    } else if (event.key === 'Delete' || event.key === 'Backspace') {
      event.preventDefault();
      event.stopPropagation();
      const chosen = photos.filter((p) => selected.has(p.id));
      onDelete(chosen.length > 0 ? chosen : [photo]);
    }
  };

  return (
    // the shortcuts sit in front of the grid's own keys (capture), on the frames inside
    // oxlint-disable-next-line jsx-a11y/no-static-element-interactions -- keys of the grid inside, not an own control
    <div onKeyDownCapture={onKeyDownCapture}>
      <GridList
        aria-label="Kontaktbogen"
        layout="grid"
        selectionMode="multiple"
        selectionBehavior="toggle"
        disallowTypeAhead
        selectedKeys={selected}
        onSelectionChange={(selection) => onSelectionChange(toIds(selection, photos))}
        onAction={(key) => {
          const photo = byId.get(String(key));
          if (photo) onOpen(photo);
        }}
        data-testid="grid"
        className="grid grid-cols-3 gap-x-2 gap-y-3 outline-none sm:grid-cols-[repeat(auto-fill,minmax(6.5rem,1fr))]"
      >
        {photos.map((photo) => {
          const label = photoLabel(photo);
          return (
            <GridListItem
              key={photo.id}
              id={photo.id}
              textValue={label}
              data-photo-id={photo.id}
              data-thumb-for={photo.id}
              data-testid="photo-tile"
              data-hidden={photo.hidden || undefined}
              className={({ isFocusVisible }) =>
                cx(
                  'group/frame relative grid min-w-0 cursor-pointer content-start gap-1 outline-none',
                  isFocusVisible && 'outline-2 outline-offset-3 outline-focus',
                )
              }
            >
              {({ isSelected }) => (
                <>
                  <div
                    className={cx(
                      'relative aspect-[3/4] overflow-hidden bg-surface-sunk',
                      currentId === photo.id && 'ring-2 ring-ink ring-offset-2 ring-offset-surface',
                    )}
                  >
                    <img
                      src={photo.thumb_url}
                      alt=""
                      width={300}
                      height={400}
                      loading="lazy"
                      decoding="async"
                      className={cx(
                        'size-full object-cover transition-[opacity,filter] duration-(--duration-quick)',
                        photo.hidden && 'opacity-40 grayscale-[0.6]',
                        arrivedLive.has(photo) && 'animate-develop',
                      )}
                    />
                    {photo.hidden ? (
                      <GreaseX
                        animate
                        className="pointer-events-none absolute inset-[6%] size-[88%] text-mark"
                      />
                    ) : null}
                    <span
                      className={cx(
                        'absolute top-0 left-0 z-(--z-raised) transition-opacity duration-(--duration-quick)',
                        // on a desktop the boxes show on hover and focus, or once a selection exists
                        !isSelected &&
                          !selecting &&
                          'fine:opacity-0 fine:group-hover/frame:opacity-100 fine:group-data-[focus-visible]/frame:opacity-100',
                      )}
                    >
                      <Checkbox slot="selection" variant="tile" aria-label="Auswählen" data-testid="select" />
                    </span>
                  </div>
                  {isSelected ? (
                    <GreaseCircle
                      animate
                      className="pointer-events-none absolute -top-[3%] -left-[5%] z-(--z-raised) aspect-[3/4.2] w-[110%] text-mark"
                    />
                  ) : null}
                  <span className="grid min-w-0 text-xs">
                    <span className="truncate font-semibold tabular">{label}</span>
                    {photo.hidden ? (
                      <span className="truncate font-semibold text-mark">
                        {photo.hidden_reason === 'ban' ? 'Gast gesperrt' : 'Ausgeblendet'}
                      </span>
                    ) : (
                      <span translate="no" className="truncate text-ink-muted">
                        {guestName(photo.user)}
                      </span>
                    )}
                  </span>
                </>
              )}
            </GridListItem>
          );
        })}
      </GridList>
    </div>
  );
}
