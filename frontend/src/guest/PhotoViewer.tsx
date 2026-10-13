/**
 * One of the guest's own photos, large, with "Speichern" (and "Teilen" where the
 * browser has a share sheet and it is not iOS, where Speichern already is the share
 * sheet). The JPEG is fetched when the viewer opens, so the tap can hand it to the
 * share sheet right away (Web Share needs the user activation).
 * Previous / next: the buttons, or the arrow keys (round the ends).
 */
import { useQuery } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight, Download, Share2 } from 'lucide-react';
import { useEffect } from 'react';
import type { GuestPhoto } from '@/api/types';
import { formatTime, frameLabel } from '@/lib/format';
import { msg, t } from '@/lib/messages.de';
import { isIOS } from '@/sdk/platform';
import { canShareFiles, saveImage, shareImage, type SaveResult } from '@/sdk/share';
import { Button } from '@/ui/Button';
import { FilmEdge } from '@/ui/FilmEdge';
import { IconButton } from '@/ui/IconButton';
import { Sheet } from '@/ui/Sheet';
import { showToast } from '@/ui/Toast';
import { photoFileName } from './photos';

export interface PhotoViewerProps {
  photos: ReadonlyArray<GuestPhoto>;
  /** index into photos, or null when closed */
  index: number | null;
  onIndexChange: (index: number | null) => void;
}

async function fetchBlob(url: string): Promise<Blob> {
  const res = await fetch(url, { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.blob();
}

function report(result: SaveResult): void {
  if (result === 'downloaded') showToast({ tone: 'success', message: msg.saved });
}

export function PhotoViewer({ photos, index, onIndexChange }: PhotoViewerProps) {
  const photo = index === null ? undefined : photos[index];
  const blob = useQuery({
    queryKey: ['photo-file', photo?.id],
    queryFn: () => fetchBlob(photo?.url ?? ''),
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
    const name = photoFileName(photo);
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
            {t.save}
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
          <figure className="mx-auto grid w-full max-w-[calc(min(60dvh,36rem)*0.75)]">
            <div className="aspect-[3/4] overflow-hidden bg-surface-sunk">
              <img
                key={photo.id}
                src={photo.url}
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
        </div>
      ) : null}
    </Sheet>
  );
}
