/**
 * „Fotobox-Filter“: which filters guests get in the Fotobox's strip. A switch saves at
 * once (the whole list of the enabled ids), optimistic, rolled back with a toast on an
 * error. The last filter that is on cannot be switched off.
 */
import { useQueryClient } from '@tanstack/react-query';
import { Camera } from 'lucide-react';
import { useState } from 'react';
import { quoted } from '@/lib/messages.de';
import { Button } from '@/ui/Button';
import { Spinner } from '@/ui/Spinner';
import { Switch } from '@/ui/Switch';
import { showToast } from '@/ui/Toast';
import { errorText, showError } from '../common/usePhotoActions';
import { boothFiltersKey, saveBoothFilters, useBoothFilters, type BoothFilterSettings } from './api';
import { LAST_ONE, lockedFilter, withFilter } from './rules';
import { SettingsCard } from './SettingsCard';

export function BoothFiltersCard() {
  const qc = useQueryClient();
  const query = useBoothFilters();
  const [busy, setBusy] = useState<string | null>(null);
  const filters = query.data?.filters ?? [];
  const locked = lockedFilter(filters);

  const toggle = async (id: string, name: string, enabled: boolean) => {
    const before = qc.getQueryData<BoothFilterSettings>(boothFiltersKey);
    if (busy !== null || !before) return;
    const next = withFilter(before, id, enabled);
    qc.setQueryData(boothFiltersKey, next);
    setBusy(id);
    try {
      await saveBoothFilters(
        qc,
        next.filters.filter((f) => f.enabled).map((f) => f.id),
      );
      showToast({
        message: enabled ? `${quoted(name)} ist wieder an.` : `${quoted(name)} ist aus.`,
        tone: 'success',
      });
    } catch (err) {
      qc.setQueryData(boothFiltersKey, before);
      showError(err);
    } finally {
      setBusy(null);
    }
  };

  return (
    <SettingsCard title="Fotobox-Filter" icon={Camera} testid="settings-booth-filters">
      <p className="text-sm text-ink-muted">
        Ausgeschaltete Filter verschwinden bei den Gästen aus der Filterleiste, spätestens nach 30 Sekunden.
        Fotos, die schon unterwegs sind, kommen trotzdem an. Mindestens ein Filter bleibt an.
      </p>
      {query.isPending ? (
        <Spinner />
      ) : query.isError && !query.data ? (
        <div className="grid justify-items-start gap-2">
          <p role="alert" className="text-sm font-semibold text-danger">
            {errorText(query.error)}
          </p>
          <Button size="sm" onPress={() => void query.refetch()}>
            Erneut laden
          </Button>
        </div>
      ) : (
        <ul className="grid divide-y divide-line border-y border-line" data-testid="booth-filter-list">
          {filters.map((f) => (
            <li key={f.id}>
              <Switch
                isSelected={f.enabled}
                isPending={busy === f.id}
                isDisabled={(busy !== null && busy !== f.id) || f.id === locked}
                onChange={(enabled) => void toggle(f.id, f.name, enabled)}
                description={f.id === locked ? LAST_ONE : undefined}
                className="py-1"
                data-testid={`booth-filter-${f.id}`}
              >
                {f.name}
              </Switch>
            </li>
          ))}
        </ul>
      )}
    </SettingsCard>
  );
}
