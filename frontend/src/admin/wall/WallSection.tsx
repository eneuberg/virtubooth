/**
 * /admin/manage?tab=livewall: the Live Wall's settings. Edits collect in a draft and go
 * to the server in one PUT ("Änderungen speichern"); open walls pick them up at once.
 * Password, analyzers and re-runs are their own requests.
 */
import { useQueryClient } from '@tanstack/react-query';
import { ExternalLink, Save, Tv, Undo2 } from 'lucide-react';
import { useState } from 'react';
import { Button, LinkButton } from '@/ui/Button';
import { EmptyState } from '@/ui/EmptyState';
import { Spinner } from '@/ui/Spinner';
import { showToast } from '@/ui/Toast';
import { toastAvoid } from '@/ui/toastPlacement';
import { errorText, showError } from '../common/usePhotoActions';
import { AccessCard } from './AccessCard';
import { AnalysisCard } from './AnalysisCard';
import { isRouteMissing, saveWallConfig } from './api';
import { CategoriesCard } from './CategoriesCard';
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

  const props = { draft, update, errors };
  return (
    <>
      <div className="grid items-start gap-x-10 gap-y-8 xl:grid-cols-2">
        <AccessCard admin={admin} />
        <PlaylistCard {...props} />
        <SpotlightCard {...props} />
        <GalleryCard {...props} />
        <PhotosCard {...props} sources={admin.sources} />
        <LookCard {...props} defaults={admin.defaults} />
        <OverlayCard {...props} />
        <CategoriesCard {...props} categories={admin.categories} />
        <AnalysisCard />
      </div>
      {dirty ? (
        <section
          aria-label="Ungespeicherte Änderungen"
          data-testid="wall-savebar"
          data-surface="dark"
          {...toastAvoid}
          className="sticky bottom-[calc(4rem+env(safe-area-inset-bottom))] z-(--z-bar) -mx-4 flex flex-wrap items-center gap-2 bg-negativ px-4 py-2 text-leuchttisch lg:bottom-0 lg:-mx-6 lg:px-6 lg:py-3"
        >
          <p className="mr-auto text-sm" role={saveError ? 'alert' : undefined}>
            {saveError ?? 'Ungespeicherte Änderungen'}
          </p>
          <Button
            size="xs"
            variant="quiet"
            icon={Undo2}
            isDisabled={saving}
            onPress={() => {
              setEdits(null);
              setSaveError(null);
            }}
            data-testid="wall-discard"
          >
            Verwerfen
          </Button>
          <Button
            size="xs"
            variant="primary"
            icon={Save}
            isPending={saving}
            onPress={() => void save()}
            data-testid="wall-save"
          >
            Änderungen speichern
          </Button>
        </section>
      ) : null}
    </>
  );
}
