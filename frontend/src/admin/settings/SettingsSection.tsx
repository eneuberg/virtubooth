/**
 * /admin/manage?tab=einstellungen: the event name, the Fotobox's filters (when the
 * Fotobox is loaded) and the admin password. Reached from the sidebar's footer
 * (desktop) and the header's gear (phones), not from the section list.
 */
import { Settings } from 'lucide-react';
import { Button } from '@/ui/Button';
import { EmptyState } from '@/ui/EmptyState';
import { Spinner } from '@/ui/Spinner';
import { useExtensionMap } from '../store/hooks';
import { BOOTH_ID, useSettings } from './api';
import { BoothFiltersCard } from './BoothFiltersCard';
import { EventNameCard } from './EventNameCard';
import { PasswordCard } from './PasswordCard';

export function SettingsSection() {
  const settings = useSettings();
  const hasBooth = useExtensionMap().has(BOOTH_ID);
  const data = settings.data;
  return (
    <section aria-labelledby="section-title" className="grid content-start gap-6 px-4 py-4 lg:px-6 lg:py-5">
      <header className="grid gap-1">
        <h1 id="section-title" tabIndex={-1} className="text-xl font-bold outline-none">
          Einstellungen
        </h1>
      </header>
      {data ? (
        <div className="grid items-start gap-8 md:grid-cols-2 xl:grid-cols-3" data-testid="settings">
          <EventNameCard event={data.event} />
          {hasBooth ? <BoothFiltersCard /> : null}
          <PasswordCard state={data.password} />
        </div>
      ) : settings.isError ? (
        <EmptyState
          icon={Settings}
          title="Einstellungen sind gerade nicht erreichbar"
          action={<Button onPress={() => void settings.refetch()}>Erneut laden</Button>}
        >
          {settings.error.message}
        </EmptyState>
      ) : (
        <Spinner />
      )}
    </section>
  );
}
