/**
 * /admin/manage?tab=fotobox: the Fotobox's settings (today: which filters guests get).
 * Without the Fotobox loaded on this server, a calm note instead.
 */
import { Camera } from 'lucide-react';
import { EmptyState } from '@/ui/EmptyState';
import { BOOTH_ID } from '../settings/api';
import { useExtensionMap, useExtensions } from '../store/hooks';
import { BoothFiltersCard } from './BoothFiltersCard';

export function FotoboxSection() {
  const extensions = useExtensions();
  const hasBooth = useExtensionMap().has(BOOTH_ID);
  return (
    <section aria-labelledby="section-title" className="grid content-start gap-6 px-4 py-4 lg:px-6 lg:py-5">
      <header className="grid gap-1">
        <h1 id="section-title" tabIndex={-1} className="text-xl font-bold outline-none">
          Fotobox
        </h1>
        <p className="max-w-prose text-sm text-ink-muted">
          Was Gäste in der Fotobox bekommen. Änderungen gelten sofort.
        </p>
      </header>
      {hasBooth ? (
        <div className="grid max-w-xl gap-8" data-testid="fotobox">
          <BoothFiltersCard />
        </div>
      ) : extensions.isPending ? null : (
        <EmptyState icon={Camera} title="Die Fotobox ist nicht aktiv">
          Auf diesem Server läuft keine Fotobox. Sie lässt sich mit VB_EXTENSIONS einschalten.
        </EmptyState>
      )}
    </section>
  );
}
