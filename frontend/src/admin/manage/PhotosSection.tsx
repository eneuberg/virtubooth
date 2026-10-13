import { useQueryClient } from '@tanstack/react-query';
import { ArrowUp, Images, RotateCw, SquareCheck } from 'lucide-react';
import { useState } from 'react';
import { useSearchParams } from 'wouter';
import type { AdminPhoto } from '@/api/types';
import { formatNumber, NBSP } from '@/lib/format';
import { t } from '@/lib/messages.de';
import { Button } from '@/ui/Button';
import { cx } from '@/ui/cx';
import { EmptyState } from '@/ui/EmptyState';
import { SegmentedControl } from '@/ui/SegmentedControl';
import { Select } from '@/ui/Select';
import { SkeletonGrid } from '@/ui/Skeleton';
import { showToast } from '@/ui/Toast';
import { DeletePhotosDialog } from '../common/DeletePhotosDialog';
import { useLoadMore } from '../common/grid';
import { PhotoViewer } from '../common/PhotoViewer';
import { usePhotoParam } from '../common/usePhotoParam';
import { showError, useHideToggle } from '../common/usePhotoActions';
import { copyText, DESKTOP, focusLater, sortedCopy, thumbFor, useMediaQuery } from '../lib/browser';
import { photoCount } from '../lib/labels';
import { bulkSetHidden } from '../store/actions';
import { incomingPhotos, listedPhotos } from '../store/cache';
import {
  useExtensionMap,
  useExtensions,
  useMergeIncoming,
  usePhoto,
  usePhotoList,
  useStats,
  useUserOptions,
} from '../store/hooks';
import type { PhotoStatus } from '../store/types';
import { ContactSheet } from './ContactSheet';
import { parsePhotoFilter, photoStatusParam, withParams } from './manageUrl';
import { PhotoInspector } from './PhotoInspector';
import { SelectionBar } from './SelectionBar';

const STATUS_OPTIONS: ReadonlyArray<{ id: PhotoStatus; label: string }> = [
  { id: 'all', label: 'Alle' },
  { id: 'visible', label: 'Sichtbar' },
  { id: 'hidden', label: 'Ausgeblendet' },
];

/** The neighbour to show (and focus) when `id` leaves the list: the next older, else the newer one. */
function neighbour(photos: ReadonlyArray<AdminPhoto>, ids: ReadonlySet<string>, from: string): string | null {
  const i = photos.findIndex((p) => p.id === from);
  if (i === -1) return null;
  const after = photos.slice(i + 1).find((p) => !ids.has(p.id));
  const before = photos.slice(0, i).findLast((p) => !ids.has(p.id));
  return (after ?? before)?.id ?? null;
}

async function copyHandle(handle: string): Promise<void> {
  const ok = await copyText(`@${handle}`);
  showToast(
    ok
      ? { message: `Kopiert: @${handle}`, tone: 'success' }
      : { message: 'Kopieren ging nicht. Bitte von Hand markieren.', tone: 'error' },
  );
}

export function PhotosSection() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const filter = parsePhotoFilter(params);
  const filterKey = JSON.stringify(filter);
  const desktop = useMediaQuery(DESKTOP);
  const list = usePhotoList('manage', filter);
  const merge = useMergeIncoming('manage', filter);
  const { data: stats } = useStats();
  const { data: extensions } = useExtensions();
  const extensionMap = useExtensionMap();
  const users = useUserOptions(true);
  const { toggle, busyId } = useHideToggle();
  const { photoId, openPhoto, closePhoto } = usePhotoParam();

  // the selection belongs to one filter: changing the filter starts a new one
  const [selection, setSelection] = useState<{ key: string; ids: ReadonlySet<string> }>({
    key: filterKey,
    ids: new Set(),
  });
  const selected = selection.key === filterKey ? selection.ids : new Set<string>();
  const select = (ids: ReadonlySet<string>) => setSelection({ key: filterKey, ids });
  const [deleting, setDeleting] = useState<AdminPhoto[]>([]);
  const [bulkBusy, setBulkBusy] = useState<'hide' | 'unhide' | null>(null);

  const photos = listedPhotos(list.data);
  const incoming = incomingPhotos(list.data);
  const total = list.data?.pages[0]?.total ?? null;
  const deepLinked = usePhoto(photoId && !photos.some((p) => p.id === photoId) ? photoId : null);
  const current: AdminPhoto | null =
    (photoId ? photos.find((p) => p.id === photoId) : undefined) ??
    (deepLinked.data && !deepLinked.data.deleted ? deepLinked.data : null);
  const chosen = photos.filter((p) => selected.has(p.id));

  const more = useLoadMore(() => {
    if (list.hasNextPage && !list.isFetchingNextPage) void list.fetchNextPage();
  }, list.hasNextPage);

  const setFilter = (changes: Record<string, string | number | null>) =>
    setParams((prev) => withParams(prev, { ...changes, photo: null }), { replace: true });

  const open = (photo: AdminPhoto) => openPhoto(photo.id, desktop ? 'replace' : 'push');

  const afterDelete = (gone: string[]) => {
    const goneSet = new Set(gone);
    select(new Set([...selected].filter((id) => !goneSet.has(id))));
    const anchor = gone.find((id) => id === photoId) ?? gone[0];
    const next = anchor ? neighbour(photos, goneSet, anchor) : null;
    if (photoId && goneSet.has(photoId)) {
      if (next && desktop) openPhoto(next, 'replace');
      else closePhoto();
    }
    if (next) focusLater(() => thumbFor(next));
  };

  const bulk = async (hidden: boolean) => {
    const targets = chosen;
    setBulkBusy(hidden ? 'hide' : 'unhide');
    try {
      const n = await bulkSetHidden(qc, targets, hidden);
      select(new Set());
      showToast({
        message: `${photoCount(n)} ${hidden ? 'ausgeblendet' : 'eingeblendet'}`,
        tone: 'success',
        action: {
          label: t.undo,
          onAction: () => {
            bulkSetHidden(qc, targets, !hidden).then(
              (m) =>
                showToast({
                  message: `${photoCount(m)} ${hidden ? 'eingeblendet' : 'ausgeblendet'}`,
                  tone: 'info',
                }),
              showError,
            );
          },
        },
      });
    } catch (err) {
      showError(err);
    } finally {
      setBulkBusy(null);
    }
  };

  const extOptions = [
    { id: 'all', label: 'Alle' },
    ...(extensions ?? []).map((e) => ({ id: e.id, label: e.title })),
    ...(filter.ext && !extensions?.some((e) => e.id === filter.ext)
      ? [{ id: filter.ext, label: filter.ext }]
      : []),
  ];
  const userOptions = [
    { id: 'all', label: 'Alle' },
    ...sortedCopy(
      (users.data ?? []).filter((u) => u.photo_count > 0 || u.id === filter.user),
      (a, b) => a.name.localeCompare(b.name, 'de'),
    ).map((u) => ({
      id: String(u.id),
      label: `${u.name}${u.instagram ? ` @${u.instagram}` : ''} (${u.photo_count})`,
    })),
    ...(filter.user !== null && !users.data?.some((u) => u.id === filter.user)
      ? [{ id: String(filter.user), label: `Gast #${filter.user}` }]
      : []),
  ];

  const summary =
    total === null
      ? ''
      : filter.status === 'all' && !filter.ext && filter.user === null && stats
        ? `${formatNumber(total)}, davon ${formatNumber(stats.hidden)}${NBSP}ausgeblendet`
        : photoCount(total);

  return (
    <div
      className={cx('lg:grid lg:min-h-dvh lg:grid-cols-[minmax(0,1fr)_20rem]', chosen.length > 0 && 'pb-16')}
    >
      <section aria-labelledby="section-title" className="grid content-start gap-4 px-4 py-4 lg:px-6 lg:py-5">
        <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 id="section-title" tabIndex={-1} className="text-xl font-bold outline-none">
            Fotos
          </h1>
          <span data-testid="photo-total" className="text-sm text-ink-muted tabular">
            {summary}
          </span>
        </header>
        <div className="flex flex-wrap items-end gap-2">
          <Select
            label="Aktivität"
            inlineLabel
            size="sm"
            options={extOptions}
            value={filter.ext ?? 'all'}
            onChange={(id) => setFilter({ ext: id === 'all' ? null : id })}
            data-testid="filter-ext"
            className="min-w-0 max-sm:flex-1"
          />
          <Select
            label="Gast"
            inlineLabel
            size="sm"
            options={userOptions}
            value={filter.user === null ? 'all' : String(filter.user)}
            onChange={(id) => setFilter({ user: id === 'all' ? null : id })}
            data-testid="filter-user"
            className="max-w-72 min-w-0 max-sm:flex-1"
          />
          <SegmentedControl
            label="Sichtbarkeit"
            size="sm"
            options={STATUS_OPTIONS}
            value={filter.status}
            onChange={(status) => setFilter({ status: photoStatusParam(status) })}
            data-testid="filter-status"
            className="max-sm:w-full"
          />
        </div>
        <div className="flex min-h-11 flex-wrap items-center gap-x-4 gap-y-1">
          <Button
            size="xs"
            variant="quiet"
            icon={SquareCheck}
            isDisabled={photos.length === 0}
            onPress={() => select(new Set(photos.map((p) => p.id)))}
            data-testid="select-all"
          >
            Alle auswählen
          </Button>
          <span className="text-xs text-ink-muted max-lg:hidden">
            Shift-Klick wählt einen Bereich, Esc hebt die Auswahl auf. Pfeiltasten bewegen, X blendet aus,
            Entf löscht.
          </span>
          {incoming.length > 0 ? (
            <Button
              size="xs"
              variant="primary"
              icon={ArrowUp}
              data-testid="new-pill"
              className="ml-auto"
              onPress={merge}
            >
              {incoming.length === 1 ? '1 neues Foto anzeigen' : `${incoming.length} neue Fotos anzeigen`}
            </Button>
          ) : null}
        </div>
        {list.isPending ? (
          <SkeletonGrid
            count={14}
            className="grid-cols-3 sm:grid-cols-[repeat(auto-fill,minmax(6.5rem,1fr))]"
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
          <div data-testid="grid-empty">
            <EmptyState icon={Images} title="Keine Fotos">
              {filter.ext || filter.user !== null || filter.status !== 'all'
                ? 'Für diesen Filter gibt es noch nichts.'
                : 'Sobald jemand ein Foto macht, erscheint es hier.'}
            </EmptyState>
          </div>
        ) : (
          <ContactSheet
            photos={photos}
            selected={selected}
            onSelectionChange={select}
            onOpen={open}
            currentId={current?.id ?? null}
            onToggleHidden={(photo) => void toggle(photo)}
            onDelete={setDeleting}
          />
        )}
        {list.hasNextPage ? (
          <div ref={more} className="grid place-items-center pt-2">
            <Button
              variant="secondary"
              size="sm"
              isPending={list.isFetchingNextPage}
              onPress={() => void list.fetchNextPage()}
              data-testid="more"
            >
              Mehr laden
            </Button>
          </div>
        ) : null}
      </section>
      {desktop ? (
        <div className="border-l border-line bg-surface-raised">
          <div className="sticky top-0 max-h-dvh overflow-y-auto">
            <PhotoInspector
              photo={current}
              gone={Boolean(photoId) && !current && (deepLinked.isError || Boolean(deepLinked.data?.deleted))}
              extension={current ? extensionMap.get(current.extension) : undefined}
              onClose={closePhoto}
              onToggleHidden={(photo) => void toggle(photo)}
              onDelete={(photo) => setDeleting([photo])}
              onCopyHandle={(handle) => void copyHandle(handle)}
              busy={busyId === current?.id}
            />
          </div>
        </div>
      ) : (
        <PhotoViewer
          photo={current}
          list={photos}
          extensions={extensionMap}
          onNavigate={(id) => openPhoto(id, 'replace')}
          onClose={() => {
            const last = current?.id;
            closePhoto();
            if (last) focusLater(() => thumbFor(last));
          }}
          renderActions={(photo) => (
            <div className="grid grid-cols-2 gap-2">
              <Button
                size="sm"
                variant="secondary"
                isPending={busyId === photo.id}
                onPress={() => void toggle(photo)}
                data-testid="toggle"
              >
                {photo.hidden ? t.unhide : t.hide}
              </Button>
              <Button
                size="sm"
                variant="danger-outline"
                onPress={() => setDeleting([photo])}
                data-testid="lightbox-delete"
              >
                {t.deleteEllipsis}
              </Button>
            </div>
          )}
        />
      )}
      <SelectionBar
        count={chosen.length}
        busy={bulkBusy}
        onHide={() => void bulk(true)}
        onUnhide={() => void bulk(false)}
        onDelete={() => setDeleting(chosen)}
        onClear={() => select(new Set())}
      />
      <DeletePhotosDialog photos={deleting} onClose={() => setDeleting([])} onDeleted={afterDelete} />
    </div>
  );
}
