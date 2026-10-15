/**
 * /admin/manage?tab=allgemein („Allgemeines“, old bookmarks: tab=einstellungen): the
 * event name, the admin password and the public address. The Fotobox's filters have
 * their own section (admin/booth).
 */
import { Settings2 } from 'lucide-react';
import { Button } from '@/ui/Button';
import { EmptyState } from '@/ui/EmptyState';
import { Spinner } from '@/ui/Spinner';
import { useSettings } from './api';
import { EventNameCard } from './EventNameCard';
import { PasswordCard } from './PasswordCard';
import { PublicAddressCard } from './PublicAddressCard';

export function SettingsSection() {
  const settings = useSettings();
  const data = settings.data;
  return (
    <section aria-labelledby="section-title" className="grid content-start gap-6 px-4 py-4 lg:px-6 lg:py-5">
      <header className="grid gap-1">
        <h1 id="section-title" tabIndex={-1} className="text-xl font-bold outline-none">
          Allgemeines
        </h1>
      </header>
      {data ? (
        <div className="grid items-start gap-8 md:grid-cols-2 xl:grid-cols-3" data-testid="settings">
          <EventNameCard event={data.event} />
          <PublicAddressCard state={data.public_address} />
          <PasswordCard state={data.password} />
        </div>
      ) : settings.isError ? (
        <EmptyState
          icon={Settings2}
          title="Allgemeines ist gerade nicht erreichbar"
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
