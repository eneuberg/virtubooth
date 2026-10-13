import { ScrollText } from 'lucide-react';
import { useMemo } from 'react';
import { Link } from 'react-aria-components';
import type { AuditEntry } from '@/api/types';
import { formatDateTime } from '@/lib/format';
import { Button } from '@/ui/Button';
import { DataTable, type DataColumn } from '@/ui/DataTable';
import { EmptyState } from '@/ui/EmptyState';
import { auditAction, auditActor, auditDetails, auditTarget, clock, shortHash } from '../lib/labels';
import { BOOTH_ID, useBoothFilters } from '../settings/api';
import { useAudit, useExtensionMap } from '../store/hooks';

const LINK =
  'font-semibold text-ink underline decoration-line-strong underline-offset-3 outline-none hover:decoration-ink focus-visible:outline-2 focus-visible:outline-focus';

function Target({ entry, titles }: { entry: AuditEntry; titles: ReadonlyMap<string, string> }) {
  const target = auditTarget(entry.target);
  switch (target.kind) {
    case 'user':
      return (
        <Link href={`/user?id=${target.id}`} className={LINK}>
          Gast #{target.id}
        </Link>
      );
    case 'photo':
      // the files are gone: a link would only open "Dieses Foto gibt es nicht mehr"
      if (entry.action === 'photo.delete') return <span className="text-ink-muted">Foto (gelöscht)</span>;
      return (
        <Link href={`/manage?photo=${encodeURIComponent(target.id)}`} className={LINK}>
          Foto ansehen
        </Link>
      );
    case 'device':
      return <span title={target.hash}>Gerätemerkmal {shortHash(target.hash)}</span>;
    case 'ip':
      return <span>IP {target.ip}</span>;
    case 'instagram':
      return <span translate="no">@{target.handle}</span>;
    case 'export':
      return <span>Export</span>;
    case 'code':
      return (
        <Link href={`/manage?tab=qr&code=${target.id}`} className={LINK}>
          QR-Code {target.id}
        </Link>
      );
    case 'extension':
      return <span translate="no">{titles.get(target.id) ?? target.id}</span>;
    default:
      return <span className="text-ink-muted">{target.text}</span>;
  }
}

/** Activity titles and booth filter names: the readable target and details. */
interface Names {
  titles: ReadonlyMap<string, string>;
  filters: ReadonlyMap<string, string>;
}

const columns = ({ titles, filters }: Names): ReadonlyArray<DataColumn<AuditEntry>> => [
  {
    id: 'at',
    label: 'Zeit',
    width: 'w-28',
    render: (e) => (
      <time dateTime={e.at} title={formatDateTime(e.at)}>
        {clock(e.at)}
      </time>
    ),
  },
  { id: 'action', label: 'Aktion', isRowHeader: true, render: (e) => auditAction(e.action) },
  { id: 'target', label: 'Ziel', render: (e) => <Target entry={e} titles={titles} /> },
  {
    id: 'details',
    label: 'Details',
    hideBelow: 'md',
    render: (e) => {
      const text = auditDetails(e, e.target === `x:${BOOTH_ID}` ? filters : undefined) || '–';
      return (
        <span title={text} className="block max-w-[22rem] truncate text-ink-muted">
          {text}
        </span>
      );
    },
  },
  { id: 'actor', label: 'Wer', hideBelow: 'sm', render: (e) => auditActor(e.actor) },
];

/** Protokoll: who did what, newest first, 100 at a time. */
export function AuditSection() {
  const audit = useAudit();
  const entries = audit.data?.pages.flatMap((p) => p.entries) ?? [];
  const extensions = useExtensionMap();
  // the filter names only when a booth setting is in the list
  const booth = useBoothFilters(entries.some((e) => e.target === `x:${BOOTH_ID}`));
  const columnList = useMemo(
    () =>
      columns({
        titles: new Map([...extensions].map(([id, e]) => [id, e.title])),
        filters: new Map((booth.data?.filters ?? []).map((f) => [f.id, f.name])),
      }),
    [extensions, booth.data],
  );
  return (
    <section aria-labelledby="section-title" className="grid content-start gap-4 px-4 py-4 lg:px-6 lg:py-5">
      <header className="grid gap-1">
        <h1 id="section-title" tabIndex={-1} className="text-xl font-bold outline-none">
          Protokoll
        </h1>
        <p className="max-w-prose text-sm text-ink-muted">
          Wer hat wann was gemacht. Jede Admin-Sitzung hat eine eigene Kennung.
        </p>
      </header>
      <DataTable
        data-testid="audit"
        aria-label="Protokoll"
        columns={columnList}
        rows={entries}
        getRowId={(e) => e.id}
        rowProps={(e) => ({ 'data-testid': 'audit-row', 'data-action': e.action })}
        isLoading={audit.isPending}
        maxHeightClass="max-h-none"
        className="min-w-0"
        emptyState={
          <div className="px-4">
            <EmptyState icon={ScrollText} title="Noch nichts passiert" />
          </div>
        }
      />
      {audit.hasNextPage ? (
        <div className="grid place-items-center">
          <Button
            variant="secondary"
            size="sm"
            isPending={audit.isFetchingNextPage}
            onPress={() => void audit.fetchNextPage()}
            data-testid="audit-more"
          >
            Ältere Einträge
          </Button>
        </div>
      ) : null}
    </section>
  );
}
