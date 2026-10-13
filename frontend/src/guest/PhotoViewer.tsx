/**
 * One of the guest's own photos, large, with "Speichern" (and "Teilen" where the
 * browser has a share sheet and it is not iOS, where Speichern already is the share
 * sheet). The JPEG is fetched when the viewer opens, so the tap can hand it to the
 * share sheet right away (Web Share needs the user activation).
 * Previous / next: the buttons, or the arrow keys.
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
  const hasPrev = index !== null && index > 0;
  const hasNext = index !== null && index < photos.length - 1;

  useEffect(() => {
    if (index === null) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'ArrowLeft' && index > 0) onIndexChange(index - 1);
      if (event.key === 'ArrowRight' && index < photos.length - 1) onIndexChange(index + 1);
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
      title={photo ? <span className="tabular">{frameLabel(photo.extension, photo.seq)}</span> : ''}
      description={photo ? `Um ${formatTime(photo.created_at)}` : undefined}
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
            isPending={blob.isPending}
            pendingLabel={t.loading}
            isDisabled={!blob.data}
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
              isDisabled={!blob.data}
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
          <IconButton
            label="Vorheriges Bild"
            icon={ChevronLeft}
            isDisabled={!hasPrev}
            onPress={() => index !== null && onIndexChange(index - 1)}
          />
          <div className="mx-auto aspect-[3/4] w-full max-w-[calc(min(60dvh,36rem)*0.75)] overflow-hidden bg-surface-sunk">
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
          <IconButton
            label="Nächstes Bild"
            icon={ChevronRight}
            isDisabled={!hasNext}
            onPress={() => index !== null && onIndexChange(index + 1)}
          />
        </div>
      ) : null}
    </Sheet>
  );
}
