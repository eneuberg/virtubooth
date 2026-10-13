import { ChevronLeft, ChevronRight, UserRound, X } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Dialog, Modal, ModalOverlay } from 'react-aria-components';
import type { AdminExtension, AdminPhoto } from '@/api/types';
import { formatDateTime, formatRelative } from '@/lib/format';
import { Badge } from '@/ui/Badge';
import { Button, LinkButton } from '@/ui/Button';
import { cx } from '@/ui/cx';
import { GreaseX } from '@/ui/GreaseMarks';
import { IconButton } from '@/ui/IconButton';
import { metaRows, photoLabel } from '../lib/labels';

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
}

function ViewerImage({ photo }: { photo: AdminPhoto }) {
  const [loaded, setLoaded] = useState(false);
  return (
    <div className="relative grid size-full place-items-center">
      <img
        src={photo.thumb_url}
        alt=""
        width={photo.width}
        height={photo.height}
        className={cx('absolute max-h-full max-w-full object-contain', loaded && 'invisible')}
      />
      <img
        src={photo.url}
        alt={photoLabel(photo)}
        width={photo.width}
        height={photo.height}
        onLoad={() => setLoaded(true)}
        data-testid="lightbox-img"
        className={cx(
          'relative max-h-full max-w-full object-contain transition-[opacity,filter] duration-(--duration-quick)',
          loaded ? 'opacity-100' : 'opacity-0',
          photo.hidden && 'opacity-45 grayscale-[0.6]',
        )}
      />
    </div>
  );
}

/**
 * A photo, big: on phones the whole screen, on desktop with an info panel. Arrow keys
 * and swipes go to the newer / older photo, Esc and the back button close it.
 */
export function PhotoViewer({
  photo,
  list,
  onNavigate,
  onClose,
  extensions,
  renderActions,
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
      if (document.querySelector('[role=alertdialog]')) return;
      if (e.key === 'ArrowLeft' && newer) onNavigate(newer.id);
      else if (e.key === 'ArrowRight' && older) onNavigate(older.id);
      else return;
      e.preventDefault();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [photo, newer, older, onNavigate]);

  const label = photo ? photoLabel(photo) : '';
  const ext = photo ? extensions.get(photo.extension) : undefined;

  return (
    <ModalOverlay
      isOpen={photo !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      isDismissable
      data-surface="dark"
      className={({ isEntering, isExiting }) =>
        cx(
          'vb-scrim fixed top-0 left-0 z-(--z-sheet) h-(--visual-viewport-height) w-full bg-kamera',
          isEntering && 'animate-fade-in',
          isExiting && 'animate-fade-out',
        )
      }
    >
      <Modal className="size-full outline-none">
        <Dialog
          aria-label={`Foto ${label}`}
          data-testid="lightbox"
          className={cx(
            'grid size-full grid-rows-[auto_minmax(0,1fr)_auto] text-papier outline-none',
            'lg:grid-cols-[minmax(0,1fr)_22rem] lg:grid-rows-[auto_minmax(0,1fr)]',
          )}
        >
          {photo ? (
            <>
              <div className="flex items-center gap-2 px-2 pt-[max(0.5rem,env(safe-area-inset-top))] pb-2 lg:col-span-2">
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
                <span className="ml-auto text-sm text-papier-muted tabular" aria-live="polite">
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
                className="relative min-h-0 touch-pan-y px-2"
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
                <ViewerImage key={photo.id} photo={photo} />
                {photo.hidden ? (
                  <GreaseX className="pointer-events-none absolute inset-[10%] size-[80%] text-fettstift-hell" />
                ) : null}
              </div>
              <section
                aria-label="Details"
                className="grid max-h-[42dvh] content-start gap-3 overflow-y-auto overscroll-contain border-t border-white/10 px-4 pt-3 pb-[max(1rem,env(safe-area-inset-bottom))] lg:max-h-none lg:border-t-0 lg:border-l lg:pt-1"
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
                  <dt className="text-papier-muted">Gast</dt>
                  <dd translate="no" className="truncate">
                    {photo.user.name}
                    {photo.user.instagram ? (
                      <span className="text-papier-muted"> @{photo.user.instagram}</span>
                    ) : null}
                  </dd>
                  <dt className="text-papier-muted">Aufgenommen</dt>
                  <dd>
                    <time dateTime={photo.created_at} title={formatDateTime(photo.created_at)}>
                      {formatRelative(photo.created_at)}
                    </time>
                  </dd>
                  {metaRows(photo, ext).map(([k, v]) => (
                    <div key={k} className="contents">
                      <dt className="text-papier-muted">{k}</dt>
                      <dd>{v}</dd>
                    </div>
                  ))}
                </dl>
                <div className="grid gap-2">
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
              </section>
            </>
          ) : null}
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
}
