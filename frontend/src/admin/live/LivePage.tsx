/**
 * /admin/live: the party screen on the host's phone (the manage area's light look). The newest photos
 * in a dense grid, arriving live; one tap hides one. This screen can only hide and
 * unhide: deleting, bans and everything else live in the manage area on purpose
 * (BRIEF invariant; live.test.ts checks this folder for any delete path). With the Live
 * Wall's analysis on, each tile carries the frames of its objects, faces and hands and
 * its chips, and the viewer the full analysis with frames („Analyse zeigen“ in the
 * header, with the frames' legend, turns it off).
 */
import { ArrowUp, Eye, EyeOff, Images, LayoutGrid, RotateCw } from 'lucide-react';
import { useState } from 'react';
import type { AdminPhoto } from '@/api/types';
import { formatNumber, NBSP } from '@/lib/format';
import { t } from '@/lib/messages.de';
import { BottomBar, bottomBarInset } from '@/ui/BottomBar';
import { Button, LinkButton } from '@/ui/Button';
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
import { OverviewStrip } from '../dashboard/OverviewStrip';
import { DESKTOP, focusLater, useMediaQuery } from '../lib/browser';
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
import { PartyControls, PartyStateBadges } from '../uploads/PartyControls';
import { AnalysisBoxes, AnalysisPanel } from '../wall/AnalysisPanel';
import {
  AnalysisChips,
  AnalysisLegend,
  AnalysisTileFrames,
  AnalysisToggle,
  AnalysisWins,
} from '../wall/LiveAnalysis';
import { useLiveAnalysis } from '../wall/liveAnalysisState';
import { guestName } from '../hostGuest/marks';

const isAtTop = () => window.scrollY < AT_TOP;

const TOAST_ABOVE_BAR =
  'bottom-[calc(4.75rem+env(safe-area-inset-bottom))] landscape-phone:bottom-3 landscape-phone:pl-19 lg:bottom-6';

export function LivePage() {
  return (
    <AdminFrame toastClassName={TOAST_ABOVE_BAR}>
      <LiveScreen />
    </AdminFrame>
  );
}

function LiveHeader({ desktop }: { desktop: boolean }) {
  const { data: stats } = useStats();
  return (
    <header className="flex items-center gap-3 border-b border-line bg-surface py-2 pt-[max(0.5rem,env(safe-area-inset-top))] pr-3 pl-4">
      <div className="mr-auto grid min-w-0">
        <div className="flex items-baseline gap-2.5">
          <h1 className="text-lg font-bold">Live</h1>
          <ConnectionBadge />
        </div>
        {/* phones: the switches scroll away with the page, their state stays in sight */}
        {desktop ? null : <PartyStateBadges className="my-0.5" />}
        <p className="truncate text-sm text-ink-muted tabular max-[380px]:text-xs" aria-live="off">
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
      <div className="grid shrink-0 justify-items-end gap-0.5">
        <AnalysisToggle />
        <AnalysisLegend />
      </div>
      {desktop ? (
        <LinkButton href="/manage" variant="secondary" size="sm" icon={LayoutGrid}>
          Verwaltung
        </LinkButton>
      ) : null}
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
  const desktop = useMediaQuery(DESKTOP);
  const analysis = useLiveAnalysis();
  const [showBoxes, setShowBoxes] = useState(true);
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
    <div className={cx('min-h-dvh', !desktop && bottomBarInset)}>
      <a
        href="#live-photos"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-(--z-toast) focus:rounded-control focus:bg-accent focus:px-4 focus:py-2 focus:text-on-accent"
      >
        Zu den Fotos
      </a>
      {/* the header stays on screen; on desktop with the three party switches */}
      <div className="sticky top-0 z-(--z-sticky) bg-surface">
        <LiveHeader desktop={desktop} />
        {desktop ? <PartyControls layout="row" className="border-b border-line px-4 py-2.5" /> : null}
        {incoming.length > 0 && !atTop ? (
          <div className="pointer-events-none absolute inset-x-0 top-full flex justify-center pt-3">
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
      </div>
      {desktop ? null : <PartyControls className="border-b border-line px-3 py-2.5" />}
      <OverviewStrip />
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
                  sublabel={guestName(photo.user)}
                  isHidden={photo.hidden}
                  isNew={arrivedLive.has(photo)}
                  loading={i < 6 ? 'eager' : 'lazy'}
                  onOpen={() => openPhoto(photo.id)}
                  openLabel={`${photoLabel(photo)} groß anzeigen`}
                  hiddenLabel={photo.hidden_reason === 'ban' ? 'Ausgeblendet, Gast gesperrt' : 'Ausgeblendet'}
                  photoLayer={<AnalysisTileFrames photoId={photo.id} aspect={photo.width / photo.height} />}
                  overlay={
                    <HideToggle
                      photo={photo}
                      isPending={busyId === photo.id}
                      onToggle={() => void toggle(photo)}
                    />
                  }
                />
                <AnalysisChips photoId={photo.id} className="mt-1.5" />
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
        renderOverlay={analysis ? (photo) => <AnalysisBoxes photo={photo} visible={showBoxes} /> : undefined}
        renderDetails={
          analysis
            ? (photo) => (
                <>
                  <AnalysisWins photoId={photo.id} />
                  <AnalysisPanel photo={photo} showBoxes={showBoxes} onShowBoxesChange={setShowBoxes} />
                </>
              )
            : undefined
        }
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
      {desktop ? null : (
        <BottomBar
          label="Bereiche"
          currentId="live"
          items={[
            { id: 'live', label: 'Live', icon: Images, href: '/live' },
            { id: 'manage', label: 'Verwaltung', icon: LayoutGrid, href: '/manage' },
          ]}
        />
      )}
    </div>
  );
}
