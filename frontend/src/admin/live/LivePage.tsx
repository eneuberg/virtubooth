/**
 * /admin/live: the party screen on the host's phone (dark Rotlicht). The newest photos
 * in a dense grid, arriving live; one tap hides one. This screen can only hide and
 * unhide: deleting, bans and everything else live in the manage area on purpose
 * (BRIEF invariant; live.test.ts checks this folder for any delete path).
 */
import { ArrowUp, Eye, EyeOff, Images, LayoutGrid, RotateCw, Upload } from 'lucide-react';
import type { AdminPhoto } from '@/api/types';
import { formatNumber, NBSP } from '@/lib/format';
import { t } from '@/lib/messages.de';
import { BottomBar, bottomBarInset } from '@/ui/BottomBar';
import { Button } from '@/ui/Button';
import { cx } from '@/ui/cx';
import { EmptyState } from '@/ui/EmptyState';
import { PhotoTile } from '@/ui/PhotoTile';
import { SkeletonGrid } from '@/ui/Skeleton';
import { AdminFrame } from '../common/AdminFrame';
import { ConnectionBadge } from '../common/ConnectionBadge';
import { AT_TOP, tileButton, useAtTop, useGridKeys, useLoadMore } from '../common/grid';
import { HideToggle } from '../common/HideToggle';
import { PhotoViewer } from '../common/PhotoViewer';
import { usePhotoParam } from '../common/usePhotoParam';
import { useHideToggle } from '../common/usePhotoActions';
import { focusLater } from '../lib/browser';
import { photoLabel } from '../lib/labels';
import { arrivedLive } from '../store/applyEvent';
import { incomingPhotos, listedPhotos } from '../store/cache';
import {
  useAutoMerge,
  useExtensionMap,
  useMergeIncoming,
  usePhoto,
  usePhotoList,
  useStats,
} from '../store/hooks';
import { ALL_PHOTOS } from '../store/types';
import { useDocumentSurface } from '../surface';
import { openUploadSheet } from '../uploads/sheetStore';
import { UploadStatusPill } from '../uploads/UploadStatusPill';

const isAtTop = () => window.scrollY < AT_TOP;

const TOAST_ABOVE_BAR =
  'bottom-[calc(4.75rem+env(safe-area-inset-bottom))] landscape-phone:bottom-3 landscape-phone:pl-19';

export function LivePage() {
  useDocumentSurface('dark');
  return (
    <AdminFrame toastClassName={TOAST_ABOVE_BAR}>
      <LiveScreen />
    </AdminFrame>
  );
}

function LiveHeader() {
  const { data: stats } = useStats();
  return (
    <header className="sticky top-0 z-(--z-sticky) flex items-center gap-3 border-b border-line bg-surface py-2 pt-[max(0.5rem,env(safe-area-inset-top))] pr-3 pl-4">
      <div className="grid min-w-0">
        <div className="flex items-baseline gap-2.5">
          <h1 className="text-lg font-bold">Live</h1>
          <ConnectionBadge />
        </div>
        <p className="truncate text-sm text-ink-muted tabular" aria-live="off">
          {stats ? (
            <>
              <span data-testid="stat-photos">{formatNumber(stats.photos)}</span>
              {NBSP}
              {stats.photos === 1 ? 'Foto' : 'Fotos'},{' '}
              <span data-testid="stat-hidden">{formatNumber(stats.hidden)}</span>
              {NBSP}ausgeblendet
            </>
          ) : (
            'Lädt…'
          )}
        </p>
      </div>
      <UploadStatusPill className="ml-auto" />
    </header>
  );
}

function LiveScreen() {
  const list = usePhotoList('live', ALL_PHOTOS);
  const merge = useMergeIncoming('live', ALL_PHOTOS);
  const extensions = useExtensionMap();
  const { toggle, busyId } = useHideToggle();
  const { photoId, openPhoto, closePhoto } = usePhotoParam();
  const atTop = useAtTop();
  const grid = useGridKeys<HTMLUListElement>();
  useAutoMerge('live', ALL_PHOTOS, isAtTop);

  const photos = listedPhotos(list.data);
  const incoming = incomingPhotos(list.data);
  const deepLinked = usePhoto(photoId && !photos.some((p) => p.id === photoId) ? photoId : null);
  const shown: AdminPhoto | null =
    (photoId ? photos.find((p) => p.id === photoId) : undefined) ??
    (deepLinked.data && !deepLinked.data.deleted ? deepLinked.data : null);

  const more = useLoadMore(() => {
    if (list.hasNextPage && !list.isFetchingNextPage) void list.fetchNextPage();
  }, list.hasNextPage);

  const closeViewer = () => {
    const last = shown?.id;
    closePhoto();
    if (last) focusLater(() => tileButton(last));
  };

  return (
    <div className={cx('min-h-dvh', bottomBarInset)}>
      <a
        href="#live-photos"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-(--z-toast) focus:rounded-control focus:bg-accent focus:px-4 focus:py-2 focus:text-on-accent"
      >
        Zu den Fotos
      </a>
      <LiveHeader />
      {incoming.length > 0 && !atTop ? (
        <div className="pointer-events-none sticky top-20 z-(--z-sticky) flex justify-center">
          <Button
            variant="primary"
            size="sm"
            icon={ArrowUp}
            data-testid="new-pill"
            className="pointer-events-auto shadow-float"
            onPress={() => {
              merge();
              window.scrollTo({ top: 0, behavior: 'smooth' });
            }}
          >
            {incoming.length === 1 ? '1 neues Foto' : `${incoming.length} neue Fotos`}
          </Button>
        </div>
      ) : null}
      <main id="live-photos" tabIndex={-1} className="px-2 pt-2 pb-6 outline-none">
        {list.isPending ? (
          <SkeletonGrid
            count={6}
            className="sm:grid-cols-3 landscape-phone:grid-cols-[repeat(auto-fill,minmax(8rem,1fr))]"
          />
        ) : list.isError && photos.length === 0 ? (
          <EmptyState
            icon={Images}
            title="Die Fotos laden gerade nicht"
            action={
              <Button icon={RotateCw} onPress={() => void list.refetch()}>
                Erneut laden
              </Button>
            }
          >
            {list.error.message}
          </EmptyState>
        ) : photos.length === 0 ? (
          <div data-testid="empty" className="px-2">
            <EmptyState icon={Images} title="Noch keine Fotos">
              Sobald jemand ein Foto macht, erscheint es hier sofort.
            </EmptyState>
          </div>
        ) : (
          <ul
            data-testid="feed"
            aria-label="Neueste Fotos"
            ref={grid}
            className={cx(
              'grid grid-cols-2 gap-x-2 gap-y-4 sm:grid-cols-3 md:grid-cols-4',
              'lg:grid-cols-[repeat(auto-fill,minmax(12rem,1fr))] landscape-phone:grid-cols-[repeat(auto-fill,minmax(8rem,1fr))]',
            )}
          >
            {photos.map((photo, i) => (
              <li key={photo.id} data-photo-id={photo.id} data-testid="photo-card">
                <PhotoTile
                  src={photo.thumb_url}
                  alt={photoLabel(photo)}
                  label={photoLabel(photo)}
                  sublabel={photo.user.name}
                  isHidden={photo.hidden}
                  isNew={arrivedLive.has(photo)}
                  loading={i < 6 ? 'eager' : 'lazy'}
                  onOpen={() => openPhoto(photo.id)}
                  openLabel={`${photoLabel(photo)} groß anzeigen`}
                  hiddenLabel={photo.hidden_reason === 'ban' ? 'Ausgeblendet, Gast gesperrt' : 'Ausgeblendet'}
                  overlay={
                    <HideToggle
                      photo={photo}
                      isPending={busyId === photo.id}
                      onToggle={() => void toggle(photo)}
                    />
                  }
                />
              </li>
            ))}
          </ul>
        )}
        {list.hasNextPage ? (
          <div ref={more} className="grid place-items-center pt-6">
            <Button
              variant="secondary"
              isPending={list.isFetchingNextPage}
              onPress={() => void list.fetchNextPage()}
              data-testid="more"
            >
              Ältere Fotos laden
            </Button>
          </div>
        ) : null}
      </main>
      <PhotoViewer
        photo={shown}
        list={photos}
        extensions={extensions}
        onNavigate={(id) => openPhoto(id, 'replace')}
        onClose={closeViewer}
        renderActions={(photo) => (
          <Button
            variant={photo.hidden ? 'primary' : 'secondary'}
            size="md"
            icon={photo.hidden ? Eye : EyeOff}
            isPending={busyId === photo.id}
            onPress={() => void toggle(photo)}
            data-testid="toggle"
          >
            {photo.hidden ? t.unhide : t.hide}
          </Button>
        )}
      />
      <BottomBar
        label="Bereiche"
        currentId="live"
        items={[
          { id: 'live', label: 'Live', icon: Images, href: '/live' },
          { id: 'upload', label: t.upload, icon: Upload, onPress: openUploadSheet },
          { id: 'manage', label: 'Verwaltung', icon: LayoutGrid, href: '/manage' },
        ]}
      />
    </div>
  );
}
