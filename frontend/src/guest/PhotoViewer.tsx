/**
 * One of the guest's own photos, large, with „Herunterladen“ (and „Teilen“ where the
 * browser has a share sheet and it is not iOS, where „Herunterladen“ already is the share
 * sheet: „Bild sichern“). The JPEG is fetched when the viewer opens, so the tap can hand it to the
 * share sheet right away (Web Share needs the user activation).
 * Previous / next: the buttons, or the arrow keys (round the ends). „Foto löschen“
 * (with `onDelete`) asks first, then deletes the photo for good.
 * „Filter zeigen“ (Fotobox photos; on by default, remembered): off shows the unfiltered
 * original, and „Herunterladen“ / „Teilen“ then save that one.
 */
import { useQuery } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight, Download, Share2, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { isApiError } from '@/api/errors';
import type { GuestPhoto } from '@/api/types';
import { formatTime, frameLabel } from '@/lib/format';
import { msg, t } from '@/lib/messages.de';
import { hasOriginal, noOriginalHint, photoSrc, useGuestShowFilter } from '@/lib/photoFilter';
import { isIOS } from '@/sdk/platform';
import { canShareFiles, saveImage, shareImage, type SaveResult } from '@/sdk/share';
import { Button } from '@/ui/Button';
import { ConfirmDialog } from '@/ui/ConfirmDialog';
import { FilmEdge } from '@/ui/FilmEdge';
import { IconButton } from '@/ui/IconButton';
import { Sheet } from '@/ui/Sheet';
import { Switch } from '@/ui/Switch';
import { showToast } from '@/ui/Toast';
import { photoFileName } from './photos';

export interface PhotoViewerProps {
  photos: ReadonlyArray<GuestPhoto>;
  /** index into photos, or null when closed */
  index: number | null;
  onIndexChange: (index: number | null) => void;
  /** deletes the photo for good (after the confirmation); rejects with the ApiError */
  onDelete?: (photo: GuestPhoto) => Promise<void>;
}

async function fetchBlob(url: string): Promise<Blob> {
  const res = await fetch(url, { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.blob();
}

function report(result: SaveResult): void {
  if (result === 'downloaded') showToast({ tone: 'success', message: msg.downloaded });
}

export function PhotoViewer({ photos, index, onIndexChange, onDelete }: PhotoViewerProps) {
  const photo = index === null ? undefined : photos[index];
  const [confirming, setConfirming] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const showFilter = useGuestShowFilter((s) => s.show);
  const setShowFilter = useGuestShowFilter((s) => s.setShow);
  // what the viewer shows is what „Herunterladen“ saves
  const original = photo !== undefined && !showFilter && hasOriginal(photo);
  const src = photo ? photoSrc(photo, showFilter) : '';
  const blob = useQuery({
    queryKey: ['photo-file', photo?.id, src],
    queryFn: () => fetchBlob(src),
    enabled: photo !== undefined,
    staleTime: Infinity,
    gcTime: 60_000,
  });
  const shareable = !isIOS() && canShareFiles();
  const many = photos.length > 1;
  // round the ends (buttons never turn disabled under the focus)
  const step = (by: number) => {
    if (index !== null && many) onIndexChange((index + by + photos.length) % photos.length);
  };

  useEffect(() => {
    if (index === null || photos.length < 2) return undefined;
    const onKey = (event: KeyboardEvent) => {
      const by = event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : 0;
      if (by) onIndexChange((index + by + photos.length) % photos.length);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [index, photos.length, onIndexChange]);

  const save = (share: boolean) => {
    if (!photo || !blob.data) return;
    const name = photoFileName(photo, original);
    // called synchronously in the press handler: the share sheet needs the activation
    const pending = share ? shareImage(blob.data, name) : saveImage(blob.data, name);
    pending.then(report, () => showToast({ tone: 'error', message: msg.generic }));
  };

  return (
    <Sheet
      isOpen={photo !== undefined}
      onOpenChange={(open) => {
        if (!open) onIndexChange(null);
      }}
      title="Dein Bild"
      size="lg"
      data-testid="photo-viewer"
      bodyClassName="pb-3"
      footer={
        <div className="flex gap-2">
          <Button
            variant="primary"
            size="lg"
            icon={Download}
            className="flex-1"
            // pending (not disabled) while the file loads: the button keeps the focus
            isPending={blob.isPending}
            pendingLabel={t.loading}
            isDisabled={blob.isError}
            onPress={() => save(false)}
            data-testid="photo-save"
          >
            {t.download}
          </Button>
          {shareable ? (
            <Button
              variant="secondary"
              size="lg"
              icon={Share2}
              className="flex-1"
              isPending={blob.isPending}
              pendingLabel={t.loading}
              isDisabled={blob.isError}
              onPress={() => save(true)}
              data-testid="photo-send"
            >
              Teilen
            </Button>
          ) : null}
        </div>
      }
    >
      {photo ? (
        <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-1 sm:gap-3">
          {many ? (
            <IconButton label="Vorheriges Bild" icon={ChevronLeft} onPress={() => step(-1)} />
          ) : (
            <span />
          )}
          <figure className="mx-auto grid w-full max-w-[calc(min(60dvh,36rem)*0.75)] landscape-phone:max-w-[calc(38dvh*0.75)]">
            <div className="aspect-[3/4] overflow-hidden bg-surface-sunk">
              <img
                key={`${photo.id}-${src}`}
                src={src}
                data-testid="photo-viewer-img"
                data-variant={original ? 'raw' : 'filtered'}
                alt={`Dein Foto ${frameLabel(photo.extension, photo.seq)}`}
                width={photo.width}
                height={photo.height}
                decoding="async"
                className="size-full animate-develop object-cover"
              />
            </div>
            <FilmEdge
              holes="bottom"
              label={frameLabel(photo.extension, photo.seq).replace(/\u00a0\d+$/, '')}
              frame={photo.seq}
              end={`um ${formatTime(photo.created_at)}`}
            />
          </figure>
          {many ? <IconButton label="Nächstes Bild" icon={ChevronRight} onPress={() => step(1)} /> : <span />}
          {photo.meta && 'filter' in photo.meta ? (
            <Switch
              isSelected={showFilter || !hasOriginal(photo)}
              onChange={setShowFilter}
              isDisabled={!hasOriginal(photo)}
              description={noOriginalHint(photo) || (showFilter ? undefined : 'Du siehst das Original.')}
              className="col-start-2"
              data-testid="photo-filter-switch"
            >
              Filter zeigen
            </Switch>
          ) : null}
          {onDelete ? (
            <Button
              variant="quiet"
              size="sm"
              icon={Trash2}
              className="col-start-2 justify-self-center"
              onPress={() => {
                setDeleteError(null);
                setConfirming(true);
              }}
              data-testid="photo-delete"
            >
              Foto löschen
            </Button>
          ) : null}
        </div>
      ) : null}
      {onDelete && photo ? (
        <ConfirmDialog
          isOpen={confirming}
          onOpenChange={setConfirming}
          title="Dieses Foto löschen?"
          confirmLabel="Foto löschen"
          error={deleteError}
          data-testid="photo-delete-confirm"
          onConfirm={async () => {
            try {
              await onDelete(photo);
              setConfirming(false);
            } catch (err) {
              setDeleteError(isApiError(err) ? err.message : msg.generic);
              throw err;
            }
          }}
        >
          <p>Es verschwindet für alle, auch von der Live-Wall. Das lässt sich nicht rückgängig machen.</p>
        </ConfirmDialog>
      ) : null}
    </Sheet>
  );
}
