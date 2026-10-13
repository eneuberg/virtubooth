import { useQueryClient } from '@tanstack/react-query';
import { AtSign, Copy, ExternalLink, FileArchive } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-aria-components';
import type { AdminPhoto, InstagramHandle } from '@/api/types';
import { formatRelative, NBSP } from '@/lib/format';
import { Button, LinkButton } from '@/ui/Button';
import { Checkbox } from '@/ui/Checkbox';
import { cx } from '@/ui/cx';
import { EmptyState } from '@/ui/EmptyState';
import { PhotoTile } from '@/ui/PhotoTile';
import { SegmentedControl } from '@/ui/SegmentedControl';
import { SkeletonGrid } from '@/ui/Skeleton';
import { showToast } from '@/ui/Toast';
import { PhotoViewer } from '../common/PhotoViewer';
import { showError, useHideToggle } from '../common/usePhotoActions';
import { copyText, sortedCopy } from '../lib/browser';
import { guestCount, handleCount, photoCount, photoLabel } from '../lib/labels';
import { handleZipUrl, setHandleDone } from '../store/actions';
import { useExtensionMap, useInstagram } from '../store/hooks';

type Show = 'open' | 'done' | 'all';

const LINK =
  'font-semibold text-ink underline decoration-line-strong underline-offset-3 outline-none hover:decoration-ink focus-visible:outline-2 focus-visible:outline-focus';

/** Handles with at least one guest who is not banned: those get tagged. */
function taggable(h: InstagramHandle): boolean {
  return h.users.some((u) => !u.banned);
}

function facts(h: InstagramHandle): string {
  const parts = [photoCount(h.visible)];
  if (h.hidden > 0) parts.push(`${h.hidden}${NBSP}ausgeblendet`);
  if (h.last_upload_at) parts.push(`zuletzt ${formatRelative(h.last_upload_at)}`);
  return parts.join(', ');
}

async function copy(text: string, what: string): Promise<void> {
  const ok = await copyText(text);
  showToast(
    ok
      ? { message: `Kopiert: ${what}`, tone: 'success' }
      : { message: 'Kopieren ging nicht. Bitte von Hand markieren.', tone: 'error' },
  );
}

/**
 * The after-party board: one row per Instagram name with its guests and photos, the
 * photos as one ZIP, and an "Erledigt" mark to track what is posted and tagged.
 */
export function InstagramSection() {
  const qc = useQueryClient();
  const board = useInstagram();
  const extensions = useExtensionMap();
  const { toggle, busyId } = useHideToggle();
  const [show, setShow] = useState<Show>('open');
  const [viewer, setViewer] = useState<{ handle: string; id: string } | null>(null);

  const handles = board.data ?? [];
  const open = handles.filter((h) => !h.done);
  const shown = sortedCopy(
    handles.filter((h) => (show === 'all' ? true : show === 'done' ? h.done : !h.done)),
    (a, b) => Number(a.done) - Number(b.done) || b.photos - a.photos || a.handle.localeCompare(b.handle),
  );
  const guests = handles.reduce((n, h) => n + h.users.length, 0);
  const viewerList: AdminPhoto[] = viewer
    ? (handles.find((h) => h.handle === viewer.handle)?.recent ?? [])
    : [];
  const viewerPhoto = viewer ? (viewerList.find((p) => p.id === viewer.id) ?? null) : null;

  const markDone = async (handle: string, done: boolean) => {
    try {
      await setHandleDone(qc, handle, done);
    } catch (err) {
      showError(err);
    }
  };

  const copyAll = () => {
    const list = handles.filter(taggable);
    if (list.length === 0) {
      showToast({ message: 'Noch keine Instagram-Namen.', tone: 'info' });
      return;
    }
    void copy(list.map((h) => `@${h.handle}`).join(' '), handleCount(list.length));
  };

  return (
    <section aria-labelledby="section-title" className="grid content-start gap-4 px-4 py-4 lg:px-6 lg:py-5">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="grid gap-1">
          <div className="flex items-baseline gap-3">
            <h1 id="section-title" tabIndex={-1} className="text-xl font-bold outline-none">
              Instagram
            </h1>
            <span data-testid="insta-count" className="text-sm text-ink-muted tabular">
              {board.data
                ? `${handleCount(handles.length)}, ${guestCount(guests)}, ${open.length} offen`
                : ''}
            </span>
          </div>
          <p className="max-w-prose text-sm text-ink-muted">
            Zum Markieren beim Posten. Gesperrte Gäste bleiben beim Kopieren aller Namen und im ZIP außen vor.
          </p>
        </div>
        <Button
          size="xs"
          variant="secondary"
          icon={Copy}
          onPress={copyAll}
          className="ml-auto"
          data-testid="copy-all-handles"
        >
          Alle Namen kopieren
        </Button>
      </header>
      <SegmentedControl
        label="Anzeigen"
        size="sm"
        options={[
          { id: 'open', label: 'Offen' },
          { id: 'done', label: 'Erledigt' },
          { id: 'all', label: 'Alle' },
        ]}
        value={show}
        onChange={setShow}
        className="justify-self-start"
        data-testid="insta-show"
      />
      {board.isPending ? (
        <SkeletonGrid count={8} className="grid-cols-4 sm:grid-cols-8" />
      ) : shown.length === 0 ? (
        <EmptyState
          icon={AtSign}
          title={handles.length === 0 ? 'Noch keine Instagram-Namen' : 'Hier ist nichts'}
        >
          {handles.length === 0
            ? 'Gäste können ihren Instagram-Namen beim Beitreten oder später im Gäste-Pass angeben.'
            : show === 'open'
              ? 'Alles erledigt.'
              : 'Noch nichts als erledigt markiert.'}
        </EmptyState>
      ) : (
        <ul className="grid border-t border-line" aria-label="Instagram-Namen">
          {shown.map((h) => (
            <li
              key={h.handle}
              data-testid="insta-row"
              data-handle={h.handle}
              data-done={h.done || undefined}
              className={cx(
                'grid gap-3 border-b border-line py-4 lg:grid-cols-[minmax(13rem,17rem)_minmax(0,1fr)_auto] lg:items-start lg:gap-6',
                h.done && 'opacity-60 focus-within:opacity-100 hover:opacity-100',
              )}
            >
              <div className="grid min-w-0 gap-1">
                <h2 className="flex min-w-0 items-center gap-1.5 text-md font-bold">
                  <a
                    href={`https://www.instagram.com/${encodeURIComponent(h.handle)}/`}
                    target="_blank"
                    rel="noopener noreferrer"
                    translate="no"
                    className={cx(LINK, 'truncate')}
                  >
                    @{h.handle}
                  </a>
                  <ExternalLink
                    aria-hidden="true"
                    className="size-4 shrink-0 text-ink-muted"
                    strokeWidth={2}
                  />
                </h2>
                <p className="text-sm text-ink-muted tabular">{facts(h)}</p>
                <p className="flex flex-wrap gap-x-3 gap-y-1 text-sm">
                  {h.users.map((u) => (
                    <Link key={u.id} href={`/user?id=${u.id}`} translate="no" className={LINK}>
                      {u.name}
                      {u.banned ? <span className="font-normal text-mark"> (gesperrt)</span> : null}
                    </Link>
                  ))}
                </p>
              </div>
              {h.recent.length > 0 ? (
                <ul className="grid grid-cols-4 gap-2 sm:grid-cols-8" aria-label={`Fotos von @${h.handle}`}>
                  {h.recent.map((p) => (
                    <li key={p.id} data-photo-id={p.id}>
                      <PhotoTile
                        src={p.thumb_url}
                        alt={photoLabel(p)}
                        label={photoLabel(p)}
                        onOpen={() => setViewer({ handle: h.handle, id: p.id })}
                        openLabel={`${photoLabel(p)} ansehen`}
                      />
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-ink-muted">Keine sichtbaren Fotos.</p>
              )}
              <div className="flex flex-wrap items-center gap-2 lg:grid lg:justify-items-stretch">
                <Checkbox
                  isSelected={h.done}
                  onChange={(done) => void markDone(h.handle, done)}
                  data-testid="insta-done"
                >
                  Erledigt
                </Checkbox>
                <Button
                  size="xs"
                  variant="secondary"
                  icon={Copy}
                  onPress={() => void copy(`@${h.handle}`, `@${h.handle}`)}
                  aria-label={`@${h.handle} kopieren`}
                  data-testid="copy-handle"
                >
                  Kopieren
                </Button>
                {h.visible > 0 && taggable(h) ? (
                  <LinkButton
                    size="xs"
                    variant="secondary"
                    icon={FileArchive}
                    href={handleZipUrl(h.handle)}
                    download={`fotos-${h.handle}.zip`}
                    aria-label={`Fotos von @${h.handle} als ZIP herunterladen`}
                    data-testid="insta-zip"
                  >
                    Fotos als ZIP
                  </LinkButton>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
      <PhotoViewer
        photo={viewerPhoto}
        list={viewerList}
        extensions={extensions}
        onNavigate={(id) => viewer && setViewer({ ...viewer, id })}
        onClose={() => setViewer(null)}
        renderActions={(photo) => (
          <Button
            size="sm"
            variant="secondary"
            isPending={busyId === photo.id}
            onPress={() => void toggle(photo)}
            data-testid="toggle"
          >
            {photo.hidden ? 'Einblenden' : 'Ausblenden'}
          </Button>
        )}
      />
    </section>
  );
}
