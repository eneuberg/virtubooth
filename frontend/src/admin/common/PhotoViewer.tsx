import { ChevronLeft, ChevronRight, UserRound, X } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Dialog, Modal, ModalOverlay } from 'react-aria-components';
import type { AdminExtension, AdminPhoto } from '@/api/types';
import { formatDateTime, formatRelative } from '@/lib/format';
import { hasFilterChoice, useAdminPhotoSrc } from '@/lib/photoFilter';
import { Badge } from '@/ui/Badge';
import { Button, LinkButton } from '@/ui/Button';
import { cx } from '@/ui/cx';
import { GreaseX } from '@/ui/GreaseMarks';
import { IconButton } from '@/ui/IconButton';
import { toastAvoid } from '@/ui/toastPlacement';
import { metaRows, photoLabel, photoName } from '../lib/labels';
import { FilterToggle } from './FilterToggle';
import { FittedPhoto } from './FittedPhoto';
import { guestName } from '../hostGuest/marks';

export interface PhotoViewerProps {
  /** the photo shown; null: closed */
  photo: AdminPhoto | null;
  /** the list it belongs to, for previous / next and "3 / 49" */
  list: ReadonlyArray<AdminPhoto>;
  onNavigate: (id: string) => void;
  onClose: () => void;
  extensions: ReadonlyMap<string, AdminExtension>;
  /** the actions this screen allows (live: hide only) */
  renderActions: (photo: AdminPhoto) => ReactNode;
  /** drawn on the photo, in % of it (the analysis frames) */
  renderOverlay?: (photo: AdminPhoto) => ReactNode;
  /** more of the details panel, under the actions (the analysis) */
  renderDetails?: (photo: AdminPhoto) => ReactNode;
}

function ViewerImage({ photo, overlay }: { photo: AdminPhoto; overlay?: ReactNode }) {
  const [loaded, setLoaded] = useState(false);
  // „Filter zeigen“ off: the unfiltered original (same size, so the overlay still fits)
  const thumb = useAdminPhotoSrc(photo, true);
  const src = useAdminPhotoSrc(photo);
  // a box with the photo's shape, as large as the stage allows; the grease X and the
  // overlay lie on the photo itself
  return (
    <FittedPhoto width={photo.width} height={photo.height} className="inset-x-2">
      <img
        src={thumb}
        alt=""
        width={photo.width}
        height={photo.height}
        className={cx('absolute inset-0 size-full object-contain', loaded && 'invisible')}
      />
      <img
        src={src}
        alt={photoLabel(photo)}
        data-variant={src === photo.url ? 'filtered' : 'raw'}
        width={photo.width}
        height={photo.height}
        onLoad={() => setLoaded(true)}
        data-testid="lightbox-img"
        className={cx(
          'absolute inset-0 size-full object-contain transition-[opacity,filter] duration-(--duration-quick)',
          loaded ? 'opacity-100' : 'opacity-0',
          photo.hidden && 'opacity-45 grayscale-[0.6]',
        )}
      />
      {photo.hidden ? (
        <GreaseX className="pointer-events-none absolute inset-[8%] size-[84%] text-mark" />
      ) : null}
      {overlay}
    </FittedPhoto>
  );
}

/**
 * A photo, big: on phones the whole screen, on desktop with an info panel. Arrow keys
 * and swipes go to the newer / older photo, Esc and the back button close it. Light like
 * the manage area's inspector: the photo lies on the sunk grey, the details on white.
 */
export function PhotoViewer({
  photo,
  list,
  onNavigate,
  onClose,
  extensions,
  renderActions,
  renderOverlay,
  renderDetails,
}: PhotoViewerProps) {
  const index = photo ? list.findIndex((p) => p.id === photo.id) : -1;
  const newer = index > 0 ? list[index - 1] : undefined;
  const older = index >= 0 && index < list.length - 1 ? list[index + 1] : undefined;
  const swipe = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    if (!photo) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return;
      const target = e.target instanceof HTMLElement ? e.target : null;
      if (target?.closest('input, textarea, select, [role=slider]')) return;
      // a dialog on top of the viewer (delete question) owns the keys
      if (document.querySelector('.vb-sheet[role=alertdialog]')) return;
      if (e.key === 'ArrowLeft' && newer) onNavigate(newer.id);
      else if (e.key === 'ArrowRight' && older) onNavigate(older.id);
      else return;
      e.preventDefault();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [photo, newer, older, onNavigate]);

  const label = photo ? photoLabel(photo) : '';
  const name = photo ? photoName(photo) : 'Foto';
  const ext = photo ? extensions.get(photo.extension) : undefined;

  return (
    <ModalOverlay
      isOpen={photo !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      isDismissable
      className={({ isEntering, isExiting }) =>
        cx(
          'vb-scrim fixed top-0 left-0 z-(--z-sheet) h-(--visual-viewport-height) w-full bg-surface',
          isEntering && 'animate-fade-in',
          isExiting && 'animate-fade-out',
        )
      }
    >
      <Modal className="size-full outline-none">
        <Dialog
          aria-label={name}
          data-testid="lightbox"
          className={cx(
            'grid size-full grid-rows-[auto_minmax(0,1fr)_auto] text-ink outline-none',
            'lg:grid-cols-[minmax(0,1fr)_22rem] lg:grid-rows-[auto_minmax(0,1fr)]',
          )}
        >
          {photo ? (
            <>
              <div
                {...toastAvoid}
                className="flex items-center gap-2 border-b border-line bg-surface-raised px-2 pt-[max(0.5rem,env(safe-area-inset-top))] pb-2 lg:col-span-2"
              >
                <Button
                  variant="quiet"
                  size="sm"
                  icon={X}
                  autoFocus
                  onPress={onClose}
                  data-testid="lightbox-close"
                >
                  Schließen
                </Button>
                <span className="ml-auto text-sm text-ink-muted tabular" aria-live="polite">
                  {index >= 0 ? `${index + 1} / ${list.length}` : ''}
                </span>
                <IconButton
                  label="Neueres Foto"
                  icon={ChevronLeft}
                  isDisabled={!newer}
                  onPress={() => newer && onNavigate(newer.id)}
                />
                <IconButton
                  label="Älteres Foto"
                  icon={ChevronRight}
                  isDisabled={!older}
                  onPress={() => older && onNavigate(older.id)}
                />
              </div>
              <div
                className="relative min-h-0 touch-pan-y bg-surface-sunk"
                onPointerDown={(e) => {
                  swipe.current = { x: e.clientX, y: e.clientY };
                }}
                onPointerUp={(e) => {
                  const start = swipe.current;
                  swipe.current = null;
                  if (!start) return;
                  const dx = e.clientX - start.x;
                  const dy = e.clientY - start.y;
                  if (Math.abs(dx) < 60 || Math.abs(dy) > Math.abs(dx)) return;
                  if (dx > 0 && newer) onNavigate(newer.id);
                  if (dx < 0 && older) onNavigate(older.id);
                }}
              >
                <ViewerImage key={photo.id} photo={photo} overlay={renderOverlay?.(photo)} />
              </div>
              {/* a toast (Rückgängig) moves above this panel on phones, never over a button */}
              <section
                aria-label="Details"
                {...toastAvoid}
                className="grid max-h-[42dvh] content-start gap-3 overflow-y-auto overscroll-contain border-t border-line bg-surface-raised px-4 pt-3 pb-[max(1rem,env(safe-area-inset-bottom))] lg:max-h-none lg:border-t-0 lg:border-l lg:px-5 lg:pt-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-lg font-bold tabular">{label}</h2>
                  {photo.hidden ? (
                    <Badge tone="mark">
                      {photo.hidden_reason === 'ban' ? 'Ausgeblendet, Gast gesperrt' : 'Ausgeblendet'}
                    </Badge>
                  ) : null}
                </div>
                <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
                  <dt className="text-ink-muted">Gast</dt>
                  <dd translate="no" className="truncate">
                    {guestName(photo.user)}
                    {photo.user.instagram ? (
                      <span className="text-ink-muted"> @{photo.user.instagram}</span>
                    ) : null}
                  </dd>
                  <dt className="text-ink-muted">Aufgenommen</dt>
                  <dd>
                    <time dateTime={photo.created_at} title={formatDateTime(photo.created_at)}>
                      {formatRelative(photo.created_at)}
                    </time>
                  </dd>
                  {metaRows(photo, ext).map(([k, v]) => (
                    <div key={k} className="contents">
                      <dt className="text-ink-muted">{k}</dt>
                      <dd>{v}</dd>
                    </div>
                  ))}
                </dl>
                {hasFilterChoice(photo) ? <FilterToggle photo={photo} /> : null}
                <div className="grid gap-2" {...toastAvoid}>
                  {renderActions(photo)}
                  <LinkButton
                    href={`/user?id=${photo.user.id}`}
                    variant="secondary"
                    size="sm"
                    icon={UserRound}
                    data-testid="user-link"
                  >
                    Gast öffnen
                  </LinkButton>
                </div>
                {renderDetails?.(photo)}
              </section>
            </>
          ) : null}
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
}
