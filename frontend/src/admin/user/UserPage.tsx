/**
 * /admin/user?id=: one guest on the light table. First screen: who it is, one status
 * line, two actions (pause uploading, ban / unban in a sheet). Then the statistics
 * (online time, photos per activity), the guest's photos, then the technical details,
 * collapsed.
 */
import { useQueryClient } from '@tanstack/react-query';
import {
  Ban,
  ChevronLeft,
  Copy,
  ExternalLink,
  Images,
  RotateCcw,
  ShieldCheck,
  UserRoundX,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { useSearchParams } from 'wouter';
import { isApiError } from '@/api/client';
import type { AdminPhoto, AdminUser, UserDetail } from '@/api/types';
import { formatTime, NBSP } from '@/lib/format';
import { t } from '@/lib/messages.de';
import { Button, LinkButton } from '@/ui/Button';
import { cx } from '@/ui/cx';
import { EmptyState } from '@/ui/EmptyState';
import { IconButton } from '@/ui/IconButton';
import { PhotoTile } from '@/ui/PhotoTile';
import { Skeleton, SkeletonGrid } from '@/ui/Skeleton';
import { Switch } from '@/ui/Switch';
import { showToast } from '@/ui/Toast';
import { AdminFrame } from '../common/AdminFrame';
import { GuestBadges } from '../common/GuestBadges';
import { ConnectionBadge } from '../common/ConnectionBadge';
import { DeletePhotosDialog } from '../common/DeletePhotosDialog';
import { tileButton, useGridKeys } from '../common/grid';
import { HideToggle } from '../common/HideToggle';
import { PhotoViewer } from '../common/PhotoViewer';
import { usePhotoParam } from '../common/usePhotoParam';
import { showError, useHideToggle } from '../common/usePhotoActions';
import { copyText, focusLater } from '../lib/browser';
import { autoBanSource, clock, guestState, photoCount, photoLabel } from '../lib/labels';
import { setUserPaused } from '../store/actions';
import { useExtensionMap, useUploadPause, useUploadStop, useUserDetail } from '../store/hooks';
import { useDocumentSurface } from '../surface';
import { UploadStatusPill } from '../uploads/UploadStatusPill';
import { pauseSource } from '../uploads/uploadState';
import { resetDisplayName } from './api';
import { BanSheet } from './BanSheet';
import { TechDetails } from './TechDetails';
import { UnbanSheet } from './UnbanSheet';
import { UserStats } from './UserStats';

const ID_RE = /^[1-9]\d{0,15}$/;
const LINK =
  'font-semibold text-ink underline decoration-line-strong underline-offset-3 outline-none hover:decoration-ink focus-visible:outline-2 focus-visible:outline-focus';

export function UserPage() {
  useDocumentSurface('light');
  return (
    <AdminFrame toastClassName="lg:right-6 lg:bottom-6 lg:left-auto lg:mx-0">
      <UserScreen />
    </AdminFrame>
  );
}

function TopBar() {
  return (
    <div className="flex items-center gap-3">
      <LinkButton
        href="/manage?tab=gaeste"
        variant="quiet"
        size="xs"
        icon={ChevronLeft}
        data-testid="back"
        className="-ml-2"
      >
        Gäste
      </LinkButton>
      <ConnectionBadge className="ml-auto max-sm:hidden" />
      <UploadStatusPill className="max-sm:ml-auto" />
    </div>
  );
}

function statusLine(user: AdminUser, photos: ReadonlyArray<AdminPhoto>): string {
  const hidden = photos.filter((p) => p.hidden).length;
  const count = `${photoCount(photos.length)}${hidden > 0 ? `, davon ${hidden}${NBSP}ausgeblendet` : ''}.`;
  const state = guestState(user);
  if (state === 'auto-banned') return `Automatisch gesperrt seit ${clock(user.banned_at)}. ${count}`;
  if (state === 'banned') {
    return `Gesperrt seit ${clock(user.banned_at)}${user.ban_reason ? `: ${user.ban_reason}` : ''}. ${count}`;
  }
  return state === 'paused' ? `Hochladen pausiert. ${count}` : `Darf hochladen. ${count}`;
}

async function copyHandle(handle: string): Promise<void> {
  const ok = await copyText(`@${handle}`);
  showToast(
    ok
      ? { message: `Kopiert: @${handle}`, tone: 'success' }
      : { message: 'Kopieren ging nicht. Bitte von Hand markieren.', tone: 'error' },
  );
}

/** After a ban or unban: the status line says the new state (and screen readers read it). */
function focusStatus(): void {
  focusLater(() => document.getElementById('user-status'));
}

const DOT = { ok: 'bg-ok', paused: 'bg-accent', banned: 'bg-danger', 'auto-banned': 'bg-danger' } as const;

function UserScreen() {
  const [params] = useSearchParams();
  const raw = params.get('id');
  const id = raw && ID_RE.test(raw) ? Number(raw) : null;
  const query = useUserDetail(id);

  let body;
  if (id === null) {
    body = (
      <EmptyState
        icon={UserRoundX}
        title="Kein Gast ausgewählt."
        action={<LinkButton href="/manage?tab=gaeste">Zur Gästeliste</LinkButton>}
      />
    );
  } else if (query.isPending) {
    body = (
      <div className="grid gap-4" aria-busy="true">
        <Skeleton shape="line" className="h-10 w-2/3" />
        <Skeleton shape="line" className="w-1/2" />
        <SkeletonGrid count={6} className="grid-cols-3 sm:grid-cols-6" />
      </div>
    );
  } else if (query.isError) {
    const gone = isApiError(query.error) && query.error.status === 404;
    body = (
      <EmptyState
        icon={UserRoundX}
        title={gone ? 'Gast nicht gefunden.' : 'Der Gast lädt gerade nicht.'}
        action={
          gone ? (
            <LinkButton href="/manage?tab=gaeste">Zur Gästeliste</LinkButton>
          ) : (
            <Button onPress={() => void query.refetch()}>Erneut laden</Button>
          )
        }
      >
        {gone ? null : query.error.message}
      </EmptyState>
    );
  } else {
    body = <Guest detail={query.data} />;
  }

  return (
    <main className="mx-auto grid w-full max-w-[67.5rem] content-start gap-6 px-4 pt-[max(1rem,env(safe-area-inset-top))] pb-12 sm:px-6">
      <TopBar />
      {body}
    </main>
  );
}

function Guest({ detail }: { detail: UserDetail }) {
  const qc = useQueryClient();
  const { user, photos } = detail;
  const extensions = useExtensionMap();
  const { data: pause } = useUploadPause();
  const { data: stop } = useUploadStop();
  const { toggle, busyId } = useHideToggle();
  const { photoId, openPhoto, closePhoto } = usePhotoParam();
  const [sheet, setSheet] = useState<'ban' | 'unban' | null>(null);
  const grid = useGridKeys<HTMLUListElement>();
  const [pausing, setPausing] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [deleting, setDeleting] = useState<AdminPhoto[]>([]);
  const state = guestState(user);
  const shown = photoId ? (photos.find((p) => p.id === photoId) ?? null) : null;
  const source = pauseSource(user, pause);

  useEffect(() => {
    document.title = `${user.name} · Admin`;
    return () => {
      document.title = 'Admin';
    };
  }, [user.name]);

  const setPaused = async (paused: boolean) => {
    setPausing(true);
    try {
      await setUserPaused(qc, user.id, paused);
      showToast({
        message: paused ? `Hochladen für ${user.name} pausiert` : `${user.name} darf wieder hochladen`,
        tone: 'success',
      });
    } catch (err) {
      showError(err);
    } finally {
      setPausing(false);
    }
  };

  const resetName = async () => {
    setResetting(true);
    try {
      await resetDisplayName(qc, user.id);
      showToast({ message: `Anzeigename von ${user.name} zurückgesetzt`, tone: 'success' });
    } catch (err) {
      showError(err);
    } finally {
      setResetting(false);
    }
  };

  return (
    <>
      <header className="grid gap-3">
        <h1 data-testid="user-name" translate="no" className="text-2xl font-bold break-words sm:text-3xl">
          {user.name}
        </h1>
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-md" data-testid="user-ident">
          <span className="text-ink-muted tabular">Gast #{user.id}</span>
          {user.display_name ? (
            <>
              <span data-testid="user-display-name">
                · nennt sich <strong translate="no">„{user.display_name}“</strong>
                <span className="text-ink-muted"> (so sehen die anderen den Gast)</span>
              </span>
              <Button
                variant="quiet"
                size="xs"
                icon={RotateCcw}
                isPending={resetting}
                pendingLabel="Setzt zurück…"
                onPress={() => void resetName()}
                data-testid="reset-display-name"
              >
                Zurücksetzen
              </Button>
            </>
          ) : null}
        </p>
        {user.analysis_opt_out || user.ai_opt_out ? (
          <p className="flex flex-wrap gap-1.5" data-testid="user-opt-outs">
            <GuestBadges
              user={{
                banned: false,
                auto_banned: false,
                uploads_paused: false,
                analysis_opt_out: user.analysis_opt_out,
                ai_opt_out: user.ai_opt_out,
              }}
            />
          </p>
        ) : null}
        <p className="flex flex-wrap items-center text-md text-ink-muted">
          {user.instagram ? (
            <>
              {/* the comma stays with the name when the line wraps */}
              <span className="inline-flex min-w-0 items-center">
                <a
                  href={`https://www.instagram.com/${encodeURIComponent(user.instagram)}/`}
                  target="_blank"
                  rel="noopener noreferrer"
                  translate="no"
                  className={cx(LINK, 'inline-flex min-w-0 items-center gap-1 break-all')}
                  data-testid="user-insta"
                >
                  @{user.instagram}
                  <ExternalLink aria-hidden="true" className="size-4 shrink-0" strokeWidth={2} />
                </a>
                ,
              </span>
              <span className="ml-1">seit {formatTime(user.created_at)} dabei</span>
              <IconButton
                label="Instagram-Namen kopieren"
                icon={Copy}
                onPress={() => void copyHandle(user.instagram ?? '')}
                data-testid="copy-handle"
                className="ml-1"
              />
            </>
          ) : (
            <>
              <span>
                <span data-testid="user-insta">ohne Instagram</span>,
              </span>
              <span className="ml-1">seit {formatTime(user.created_at)} dabei</span>
            </>
          )}
        </p>
        <p
          id="user-status"
          tabIndex={-1}
          data-testid="user-status"
          data-state={state}
          className="flex items-baseline gap-2 text-md outline-none"
        >
          <span
            aria-hidden="true"
            className={cx('size-2.5 shrink-0 translate-y-[-1px] rounded-full', DOT[state])}
          />
          <span>{statusLine(user, photos)}</span>
        </p>
        {user.uploads_paused && source && !user.banned ? (
          <p className="text-sm text-ink-muted" data-testid="guest-uploads-source">
            {source}
          </p>
        ) : null}
        {stop?.enabled ? (
          <p className="text-sm font-semibold text-accent-ink">
            Gerade ist Hochladen ohnehin für alle gestoppt (seit {clock(stop.since)}).
          </p>
        ) : null}
        {user.auto_banned ? (
          <p
            className="max-w-prose rounded-control bg-surface-sunk px-4 py-3 text-sm"
            data-testid="auto-ban-note"
          >
            <strong>Automatisch gesperrt:</strong> Dieses Gerät hat sich neu angemeldet, mit{' '}
            {autoBanSource(user)}. Gleiche Handymodelle haben oft dasselbe Merkmal, vielleicht ist das jemand
            anderes.
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-3 pt-1">
          <Switch
            isSelected={user.uploads_paused}
            isPending={pausing}
            isDisabled={user.banned}
            onChange={(paused) => void setPaused(paused)}
            description={user.banned ? 'Gesperrt: kann ohnehin nicht hochladen' : undefined}
            className="rounded-control border border-line-strong bg-surface-raised px-4 py-1"
            data-testid="guest-uploads-toggle"
          >
            Hochladen pausieren
          </Switch>
          {user.banned ? (
            <Button
              variant="secondary"
              icon={ShieldCheck}
              onPress={() => setSheet('unban')}
              data-testid="unban"
            >
              {t.unbanEllipsis}
            </Button>
          ) : (
            <Button variant="danger-outline" icon={Ban} onPress={() => setSheet('ban')} data-testid="ban">
              {t.banEllipsis}
            </Button>
          )}
        </div>
      </header>

      <UserStats detail={detail} extensions={extensions} />

      <section aria-labelledby="user-photos-title" className="grid gap-3">
        <h2 id="user-photos-title" className="flex items-baseline gap-2 text-lg font-bold">
          Fotos
          <span className="text-sm font-normal text-ink-muted tabular" data-testid="uploads-count">
            {photos.length}
          </span>
        </h2>
        {photos.length === 0 ? (
          <EmptyState icon={Images} title="Keine Fotos">
            Dieser Gast hat noch nichts hochgeladen.
          </EmptyState>
        ) : (
          <ul
            data-testid="user-photos"
            aria-label={`Fotos von ${user.name}`}
            ref={grid}
            className="grid grid-cols-3 gap-x-2 gap-y-4 sm:grid-cols-[repeat(auto-fill,minmax(8.5rem,1fr))]"
          >
            {photos.map((photo) => (
              <li key={photo.id} data-photo-id={photo.id} data-testid="photo-tile">
                <PhotoTile
                  src={photo.thumb_url}
                  alt={photoLabel(photo)}
                  label={photoLabel(photo)}
                  sublabel={formatTime(photo.created_at)}
                  isHidden={photo.hidden}
                  hiddenLabel={photo.hidden_reason === 'ban' ? 'Ausgeblendet (Sperre)' : 'Ausgeblendet'}
                  onOpen={() => openPhoto(photo.id)}
                  openLabel={`${photoLabel(photo)} groß anzeigen`}
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
      </section>

      <TechDetails detail={detail} />

      <PhotoViewer
        photo={shown}
        list={photos}
        extensions={extensions}
        onNavigate={(next) => openPhoto(next, 'replace')}
        onClose={() => {
          const last = shown?.id;
          closePhoto();
          if (last) focusLater(() => tileButton(last));
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
      <DeletePhotosDialog
        photos={deleting}
        onClose={() => setDeleting([])}
        onDeleted={(gone) => {
          if (photoId && gone.includes(photoId)) closePhoto();
          const i = photos.findIndex((p) => p.id === gone[0]);
          const next =
            photos.slice(i + 1).find((p) => !gone.includes(p.id)) ?? photos.slice(0, Math.max(0, i)).at(-1);
          if (next) focusLater(() => tileButton(next.id));
        }}
      />
      <BanSheet
        detail={detail}
        isOpen={sheet === 'ban'}
        onOpenChange={(open) => setSheet(open ? 'ban' : null)}
        onDone={focusStatus}
      />
      <UnbanSheet
        detail={detail}
        isOpen={sheet === 'unban'}
        onOpenChange={(open) => setSheet(open ? 'unban' : null)}
        onDone={focusStatus}
      />
    </>
  );
}
