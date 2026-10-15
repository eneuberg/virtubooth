/**
 * "Deine Bilder": the guest's own photos that are up (GET /api/me/photos: not hidden,
 * not deleted, newest first, at most 60) as a small contact sheet. Two rows show,
 * the rest behind "Alle … zeigen". A tap opens the viewer (Herunterladen / Teilen, Foto
 * löschen).
 * Empty: blank frames and an invitation.
 */
import { useQueryClient } from '@tanstack/react-query';
import { ImagePlus } from 'lucide-react';
import { useEffect, useId, useState } from 'react';
import type { GuestPhoto } from '@/api/types';
import { formatNumber, formatTime, frameLabel } from '@/lib/format';
import { Button } from '@/ui/Button';
import { cx } from '@/ui/cx';
import { PhotoTile } from '@/ui/PhotoTile';
import { Skeleton } from '@/ui/Skeleton';
import { showToast } from '@/ui/Toast';
import { firstPhotoText } from './copy';
import { deleteMyPhoto, useMyPhotos } from './photos';
import { PhotoViewer } from './PhotoViewer';

/** two rows of four (five from sm) */
const COLLAPSED = 8;

const GRID = 'grid grid-cols-4 gap-x-2 gap-y-3 sm:grid-cols-5 lg:grid-cols-4 xl:grid-cols-5';

function EmptyFrames({ activityTitles }: { activityTitles: ReadonlyArray<string> }) {
  return (
    <div className="grid gap-3" data-testid="my-photos-empty">
      <div aria-hidden="true" className={GRID}>
        {Array.from({ length: 4 }, (_, i) => (
          <span
            key={i}
            className="grid aspect-[3/4] place-items-center rounded-photo bg-surface-raised text-accent-ink first:bg-accent-tint"
          >
            {i === 0 ? <ImagePlus className="size-6" strokeWidth={1.75} /> : null}
          </span>
        ))}
      </div>
      <p className="text-ink-muted">{firstPhotoText(activityTitles)}</p>
    </div>
  );
}

export interface MyPhotosProps {
  /** the activities that take photos, for the invitation while there are none */
  activityTitles: ReadonlyArray<string>;
  className?: string;
}

export function MyPhotos({ activityTitles, className }: MyPhotosProps) {
  const titleId = useId();
  const client = useQueryClient();
  const { data: photos, isPending, isError, refetch } = useMyPhotos();
  const [expanded, setExpanded] = useState(false);
  // the open photo by id: when the list changes under the viewer, it stays on that photo
  const [openId, setOpenId] = useState<string | null>(null);
  const list: ReadonlyArray<GuestPhoto> = photos ?? [];
  const shown = expanded ? list : list.slice(0, COLLAPSED);
  const found = openId === null ? -1 : list.findIndex((p) => p.id === openId);
  const index = found === -1 ? null : found;
  const setIndex = (i: number | null) => setOpenId(i === null ? null : (list[i]?.id ?? null));

  // the host hid (or deleted) the open photo: close the viewer and say why, instead of
  // jumping to whatever photo now sits at that place
  const [vanished, setVanished] = useState(0);
  if (openId !== null && photos !== undefined && found === -1) {
    setOpenId(null);
    setVanished((n) => n + 1);
  }
  useEffect(() => {
    if (vanished > 0) showToast({ message: 'Dieses Bild ist nicht mehr zu sehen.', tone: 'info' });
  }, [vanished]);

  return (
    <section
      aria-labelledby={titleId}
      data-testid="my-photos"
      data-state={isPending ? 'loading' : isError ? 'error' : 'ready'}
      className={cx('grid content-start gap-3', className)}
    >
      <h2 id={titleId} className="flex items-baseline gap-2 text-xl font-semibold">
        Deine Bilder
        {list.length ? (
          <span className="font-normal text-ink-muted tabular">{formatNumber(list.length)}</span>
        ) : null}
      </h2>
      {isPending ? (
        <div aria-hidden="true" className={GRID}>
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} shape="photo" />
          ))}
        </div>
      ) : isError ? (
        <div className="grid justify-items-start gap-2">
          <p className="text-ink-muted">Deine Bilder laden gerade nicht.</p>
          <Button variant="secondary" size="sm" onPress={() => void refetch()}>
            Erneut laden
          </Button>
        </div>
      ) : list.length === 0 ? (
        <EmptyFrames activityTitles={activityTitles} />
      ) : (
        <>
          <ul className={cx(GRID, 'm-0 list-none p-0')}>
            {shown.map((photo, i) => (
              <li key={photo.id} className="min-w-0">
                <PhotoTile
                  src={photo.thumb_url}
                  alt={`Dein Foto ${frameLabel(photo.extension, photo.seq)}`}
                  width={photo.width}
                  height={photo.height}
                  label={frameLabel(photo.extension, photo.seq)}
                  sublabel={formatTime(photo.created_at)}
                  onOpen={() => setIndex(i)}
                  openLabel={`${frameLabel(photo.extension, photo.seq)} ansehen`}
                  loading={i < 4 ? 'eager' : 'lazy'}
                  data-testid={`photo-${photo.id}`}
                />
              </li>
            ))}
          </ul>
          {list.length > COLLAPSED ? (
            <Button
              variant="quiet"
              size="sm"
              className="justify-self-start"
              onPress={() => setExpanded(!expanded)}
            >
              {expanded ? 'Weniger zeigen' : `Alle ${formatNumber(list.length)} zeigen`}
            </Button>
          ) : null}
        </>
      )}
      <PhotoViewer
        photos={list}
        index={index}
        onIndexChange={setIndex}
        onDelete={async (photo) => {
          await deleteMyPhoto(client, photo.id);
          // closed on purpose: not the "this photo vanished" note
          setOpenId(null);
          showToast({ message: 'Foto gelöscht.', tone: 'success' });
        }}
      />
    </section>
  );
}
