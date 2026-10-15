/**
 * /admin/manage?tab=livewall: the Live Wall's settings. Edits collect in a draft and go
 * to the server in one PUT ("Änderungen speichern"); open walls pick them up at once.
 * Password and categories are their own requests; the analysis is in the ML-Pipeline.
 */
import { useQueryClient } from '@tanstack/react-query';
import { ExternalLink, Save, Tv, Undo2 } from 'lucide-react';
import { useState } from 'react';
import { Button, LinkButton } from '@/ui/Button';
import { cx } from '@/ui/cx';
import { ConfirmDialog } from '@/ui/ConfirmDialog';
import { EmptyState } from '@/ui/EmptyState';
import { Spinner } from '@/ui/Spinner';
import { showToast } from '@/ui/Toast';
import { toastAvoid } from '@/ui/toastPlacement';
import { errorText, showError } from '../common/usePhotoActions';
import { useLeaveGuard } from '../lib/leaveGuard';
import { AccessCard } from './AccessCard';
import { isRouteMissing, saveWallConfig } from './api';
import { CategoriesCard } from './categories/CategoriesCard';
import { GalleryCard, LookCard, OverlayCard, PhotosCard, PlaylistCard, SpotlightCard } from './ConfigCards';
import { isDirty, validate } from './draft';
import { useWallAdmin, useWallEnabled } from './hooks';
import { wk } from './keys';
import { openWallsText } from './text';
import type { WallAdminOut, WallConfig } from './types';

export function WallSection() {
  const enabled = useWallEnabled();
  const admin = useWallAdmin(enabled === true);
  const off = enabled === false || (admin.isError && isRouteMissing(admin.error));
  return (
    <section aria-labelledby="section-title" className="grid content-start gap-5 px-4 py-4 lg:px-6 lg:py-5">
      <header className="grid gap-2">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 id="section-title" tabIndex={-1} className="text-xl font-bold outline-none">
            Live-Wall
          </h1>
          {admin.data ? (
            <span className="text-sm text-ink-muted tabular" data-testid="wall-open-count">
              {openWallsText(admin.data.open_walls)}
            </span>
          ) : null}
        </div>
        <p className="max-w-prose text-sm text-ink-muted">
          Die Live-Wall zeigt die Fotos der Party auf einem Fernseher: groß nacheinander, als Galerie und in
          lustigen Kategorien.
        </p>
        {off ? null : (
          <LinkButton
            href={admin.data?.wall_path ?? '/livewall'}
            target="_blank"
            rel="noopener"
            size="xs"
            variant="secondary"
            icon={Tv}
            iconEnd={ExternalLink}
            className="justify-self-start"
            data-testid="wall-open"
          >
            Live-Wall öffnen
          </LinkButton>
        )}
      </header>
      {off ? (
        <EmptyState icon={Tv} title="Die Live-Wall ist auf diesem Server aus.">
          Die Erweiterung „wall“ ist nicht geladen.
        </EmptyState>
      ) : admin.data ? (
        <Editor admin={admin.data} />
      ) : admin.isError ? (
        <EmptyState
          title="Die Einstellungen ließen sich nicht laden."
          action={
            <Button size="sm" variant="secondary" onPress={() => void admin.refetch()}>
              Nochmal versuchen
            </Button>
          }
        >
          {errorText(admin.error)}
        </EmptyState>
      ) : (
        <Spinner label="Lädt…" />
      )}
    </section>
  );
}

function Editor({ admin }: { admin: WallAdminOut }) {
  const qc = useQueryClient();
  const [edits, setEdits] = useState<WallConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const base = admin.config;
  const draft = edits ?? base;
  const dirty = isDirty(base, edits);
  const errors = validate(draft);

  const update = (change: (config: WallConfig) => WallConfig) => {
    setSaveError(null);
    setEdits((prev) => change(prev ?? base));
  };

  const save = async () => {
    if (Object.keys(errors).length > 0) {
      setSaveError('Bitte die markierten Felder prüfen.');
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const out = await saveWallConfig(draft);
      qc.setQueryData(wk.config, out);
      setEdits(null);
      void qc.invalidateQueries({ queryKey: wk.categories });
      showToast({ message: 'Gespeichert. Offene Wände übernehmen es sofort.', tone: 'success' });
    } catch (err) {
      setSaveError(errorText(err));
      showError(err);
    } finally {
      setSaving(false);
    }
  };

  const discard = () => {
    setEdits(null);
    setSaveError(null);
  };

  // leaving with unsaved changes: ask first (in-app links), or the browser asks (reload, close)
  const [leaving, setLeaving] = useState<(() => void) | null>(null);
  useLeaveGuard(dirty, (proceed) => setLeaving(() => proceed));

  const props = { draft, update, errors };
  return (
    <>
      {/* two independent stacks on wide screens: a short card never leaves a hole */}
      <div className="grid items-start gap-x-10 gap-y-8 xl:grid-cols-2">
        <div className="grid min-w-0 content-start gap-y-8" data-testid="wall-column">
          <AccessCard admin={admin} />
          <PlaylistCard {...props} />
          <SpotlightCard {...props} />
          <GalleryCard {...props} />
          <PhotosCard {...props} sources={admin.sources} />
        </div>
        <div className="grid min-w-0 content-start gap-y-8" data-testid="wall-column">
          <LookCard {...props} defaults={admin.defaults} />
          <OverlayCard {...props} />
          <CategoriesCard />
        </div>
      </div>
      {dirty ? (
        <section
          aria-label="Ungespeicherte Änderungen"
          data-testid="wall-savebar"
          data-surface="dark"
          {...toastAvoid}
          className="sticky bottom-[calc(4rem+env(safe-area-inset-bottom))] z-(--z-bar) -mx-4 flex items-center gap-2 bg-negativ px-4 py-2 text-leuchttisch lg:bottom-0 lg:-mx-6 lg:px-6 lg:py-3"
        >
          {/* one row on every phone: a short status, Verwerfen as an icon below sm */}
          <p
            className={cx(
              'mr-auto min-w-0 flex-1 text-sm leading-tight',
              saveError ? 'line-clamp-2' : 'truncate',
            )}
            role={saveError ? 'alert' : undefined}
          >
            {saveError ?? (
              <>
                <span className="sm:hidden">Nicht gespeichert</span>
                <span className="max-sm:hidden">Ungespeicherte Änderungen</span>
              </>
            )}
          </p>
          <Button
            size="xs"
            variant="quiet"
            icon={Undo2}
            isDisabled={saving}
            onPress={discard}
            className="shrink-0"
            data-testid="wall-discard"
          >
            <span className="max-sm:sr-only">Verwerfen</span>
          </Button>
          <Button
            size="xs"
            variant="primary"
            icon={Save}
            isPending={saving}
            onPress={() => void save()}
            className="shrink-0"
            data-testid="wall-save"
          >
            <span className="sm:hidden">Speichern</span>
            <span className="max-sm:hidden">Änderungen speichern</span>
          </Button>
        </section>
      ) : null}
      <ConfirmDialog
        isOpen={leaving !== null}
        onOpenChange={(open) => {
          if (!open) setLeaving(null);
        }}
        title="Änderungen verwerfen?"
        confirmLabel="Verwerfen"
        cancelLabel="Hierbleiben"
        onConfirm={() => {
          const proceed = leaving;
          discard();
          setLeaving(null);
          proceed?.();
        }}
        data-testid="wall-leave"
      >
        <p>Die Einstellungen der Live-Wall sind noch nicht gespeichert.</p>
      </ConfirmDialog>
    </>
  );
}
