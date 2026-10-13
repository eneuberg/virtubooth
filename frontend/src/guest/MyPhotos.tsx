/**
 * "Deine Bilder": the guest's own photos that are up (GET /api/me/photos: not hidden,
 * not deleted, newest first, at most 60) as a small contact sheet. Two rows show,
 * the rest behind "Alle … zeigen". A tap opens the viewer (Speichern / Teilen).
 * Empty: blank frames and an invitation.
 */
import { ImagePlus } from 'lucide-react';
import { useId, useState } from 'react';
import type { GuestPhoto } from '@/api/types';
import { formatNumber, formatTime, frameLabel } from '@/lib/format';
import { Button } from '@/ui/Button';
import { cx } from '@/ui/cx';
import { PhotoTile } from '@/ui/PhotoTile';
import { Skeleton } from '@/ui/Skeleton';
import { useMyPhotos } from './photos';
import { PhotoViewer } from './PhotoViewer';

/** two rows of four (five from sm) */
const COLLAPSED = 8;

const GRID = 'grid grid-cols-4 gap-x-2 gap-y-3 sm:grid-cols-5 lg:grid-cols-4 xl:grid-cols-5';

function EmptyFrames({ activities }: { activities: string }) {
  return (
    <div className="grid gap-3" data-testid="my-photos-empty">
      <div aria-hidden="true" className={GRID}>
        {Array.from({ length: 4 }, (_, i) => (
          <span
            key={i}
            className="grid aspect-[3/4] place-items-center border border-dashed border-line-strong text-accent-ink"
          >
            {i === 0 ? <ImagePlus className="size-6" strokeWidth={1.75} /> : null}
          </span>
        ))}
      </div>
      <p className="text-ink-muted">
        Noch keine Bilder von dir. Mach dein erstes mit {activities}: Es landet dann hier, und du kannst es
        speichern.
      </p>
    </div>
  );
}

export function MyPhotos({ activityNames, className }: { activityNames: string; className?: string }) {
  const titleId = useId();
  const { data: photos, isPending, isError, refetch } = useMyPhotos();
  const [expanded, setExpanded] = useState(false);
  const [index, setIndex] = useState<number | null>(null);
  const list: ReadonlyArray<GuestPhoto> = photos ?? [];
  const shown = expanded ? list : list.slice(0, COLLAPSED);

  return (
    <section
      aria-labelledby={titleId}
      data-testid="my-photos"
      data-state={isPending ? 'loading' : isError ? 'error' : 'ready'}
      className={cx('grid content-start gap-3', className)}
    >
      <h2 id={titleId} className="flex items-baseline gap-2 text-lg font-bold">
        Deine Bilder
        {list.length ? (
          <span className="font-semibold text-ink-muted tabular">{formatNumber(list.length)}</span>
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
        <EmptyFrames activities={activityNames} />
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
      <PhotoViewer photos={list} index={index} onIndexChange={setIndex} />
    </section>
  );
}
