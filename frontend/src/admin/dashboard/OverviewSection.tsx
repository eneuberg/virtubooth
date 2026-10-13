import type { Overview, OverviewActivity } from '@/api/types';
import { formatNumber } from '@/lib/format';
import { DataTable, type DataColumn } from '@/ui/DataTable';
import { HelpDisclosure } from '@/ui/HelpDisclosure';
import { Skeleton } from '@/ui/Skeleton';
import { clock } from '../lib/labels';
import { useOverview } from './data';
import { QuickControls } from './QuickControls';
import { freshness, minutes, scansSince } from './text';

interface Item {
  id: string;
  label: string;
  value: number | string;
}

function Group({ title, items, note }: { title: string; items: Item[]; note?: string }) {
  return (
    <section className="grid content-start gap-2 rounded-control bg-surface-raised p-4" aria-label={title}>
      <h2 className="text-md font-bold">{title}</h2>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
        {items.map((item) => (
          <div key={item.id} className="flex min-w-0 flex-col-reverse" data-testid={`overview-${item.id}`}>
            <dt className="text-xs text-ink-muted">{item.label}</dt>
            <dd className="text-xl font-bold tabular">
              {typeof item.value === 'number' ? formatNumber(item.value) : item.value}
            </dd>
          </div>
        ))}
      </dl>
      {note ? <p className="text-xs text-ink-muted">{note}</p> : null}
    </section>
  );
}

const ACTIVITY_COLUMNS: ReadonlyArray<DataColumn<OverviewActivity>> = [
  {
    id: 'title',
    label: 'Aktivität',
    isRowHeader: true,
    render: (a) => <span translate="no">{a.title}</span>,
  },
  { id: 'photos', label: 'Fotos', align: 'end', render: (a) => formatNumber(a.photos) },
  { id: 'visible', label: 'Sichtbar', align: 'end', render: (a) => formatNumber(a.visible) },
  {
    id: 'recent',
    label: `Letzte ${minutes(60)}`,
    align: 'end',
    render: (a) => formatNumber(a.last_60_min),
  },
];

function Groups({ o }: { o: Overview }) {
  const now = minutes(o.active_minutes);
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <Group
        title={`Jetzt (letzte ${now})`}
        items={[
          { id: 'active', label: 'Aktiv', value: o.guests.active_now },
          { id: 'uploading', label: 'Laden gerade hoch', value: o.guests.uploading_now },
          { id: 'waiting', label: 'Gescannt, noch nicht dabei', value: o.scans.waiting_now },
        ]}
      />
      <Group
        title="Scans"
        items={[
          { id: 'scanned', label: 'Gescannt', value: o.scans.scanned },
          { id: 'joined', label: 'Beigetreten', value: o.scans.joined },
          { id: 'not-joined', label: 'Nicht beigetreten', value: o.scans.not_joined },
        ]}
        note={scansSince(o)}
      />
      <Group
        title="Gäste"
        items={[
          { id: 'guests', label: 'Gesamt', value: o.guests.total },
          { id: 'instagram', label: 'Mit Instagram', value: o.guests.instagram },
          { id: 'paused', label: 'Pausiert', value: o.guests.paused },
          { id: 'banned', label: 'Gesperrt', value: o.guests.banned },
        ]}
      />
      <Group
        title="Fotos"
        items={[
          { id: 'photos', label: 'Gesamt', value: o.photos.total },
          { id: 'visible', label: 'Sichtbar', value: o.photos.visible },
          { id: 'hidden', label: 'Ausgeblendet', value: o.photos.hidden },
          { id: 'recent', label: `Letzte ${minutes(15)}`, value: o.photos.last_15_min },
          { id: 'recent-hour', label: `Letzte ${minutes(60)}`, value: o.photos.last_60_min },
          { id: 'last-upload', label: 'Letzter Upload', value: clock(o.photos.last_upload_at) },
        ]}
      />
    </div>
  );
}

/** Übersicht (manage): every live counter, grouped, plus the two switches. */
export function OverviewSection() {
  const { data, isError } = useOverview();
  return (
    <section
      aria-labelledby="section-title"
      data-testid="overview-section"
      className="grid content-start gap-4 px-4 py-4 lg:px-6 lg:py-5"
    >
      <header className="grid gap-1">
        <h1 id="section-title" tabIndex={-1} className="text-xl font-bold outline-none">
          Übersicht
        </h1>
        <p className="max-w-prose text-sm text-ink-muted" aria-live="off">
          {data ? freshness(data) : 'Was gerade auf der Party los ist.'}
        </p>
      </header>
      <QuickControls className="max-w-md" />
      {data ? (
        <>
          <Groups o={data} />
          <DataTable
            data-testid="overview-activities"
            aria-label="Aktivitäten"
            columns={ACTIVITY_COLUMNS}
            rows={data.activities}
            getRowId={(a) => a.id}
            maxHeightClass="max-h-none"
            className="min-w-0"
          />
        </>
      ) : isError ? (
        <p className="text-sm text-ink-muted">Die Zahlen laden gerade nicht. Gleich nochmal.</p>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2" aria-hidden="true">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      )}
      <HelpDisclosure summary="Wie wird gezählt?" variant="section">
        <p>
          <strong className="text-ink">Aktiv:</strong> Gäste (nicht gesperrt), deren Seite in den letzten{' '}
          {minutes(5)} mit dem Server gesprochen hat. <strong className="text-ink">Laden gerade hoch:</strong>{' '}
          Gäste mit einem Upload in dieser Zeit.
        </p>
        <p>
          <strong className="text-ink">Gescannt:</strong> Browser, die einen gültigen QR-Code geöffnet haben.
          Dafür speichert die Seite nur eine zufällige Kennung mit Uhrzeit, ohne IP und ohne Gerätedaten.{' '}
          <strong className="text-ink">Nicht beigetreten:</strong> gescannt, aber nie beigetreten. Gäste von
          vor dem Update zählen erst, wenn ihr Browser wiederkommt.
        </p>
        <p>
          <strong className="text-ink">Fotos der letzten Minuten</strong> zählen jeden Upload, auch später
          ausgeblendete oder gelöschte.
        </p>
      </HelpDisclosure>
    </section>
  );
}
