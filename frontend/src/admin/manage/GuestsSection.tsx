import { Search, Users } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { SortDescriptor } from 'react-aria-components';
import { useLocation, useSearchParams } from 'wouter';
import type { AdminUser } from '@/api/types';
import { formatDateTime, formatNumber, formatRelative } from '@/lib/format';
import { Button } from '@/ui/Button';
import { DataTable, type DataColumn } from '@/ui/DataTable';
import { EmptyState } from '@/ui/EmptyState';
import { Select } from '@/ui/Select';
import { TextField } from '@/ui/TextField';
import { GuestBadges } from '../common/GuestBadges';
import { sortedCopy } from '../lib/browser';
import { describeUA, guestCount } from '../lib/labels';
import { quoted } from '@/lib/messages.de';
import { useGuestList, useStats } from '../store/hooks';
import type { GuestStatus } from '../store/types';
import { parseGuestFilter, withParams } from './manageUrl';

const STATUS_OPTIONS: ReadonlyArray<{ id: GuestStatus; label: string }> = [
  { id: 'all', label: 'Alle' },
  { id: 'banned', label: 'Gesperrt' },
  { id: 'ok', label: 'Nicht gesperrt' },
  { id: 'paused', label: 'Hochladen pausiert' },
];

const COLUMNS: ReadonlyArray<DataColumn<AdminUser>> = [
  {
    id: 'id',
    label: 'Nr.',
    align: 'end',
    allowsSorting: true,
    width: 'w-16',
    hideBelow: 'sm',
    render: (u) => <span className="text-ink-muted">#{u.id}</span>,
  },
  {
    id: 'name',
    label: 'Name',
    isRowHeader: true,
    allowsSorting: true,
    render: (u) => (
      <span translate="no" className="font-semibold">
        {u.name}
      </span>
    ),
  },
  {
    id: 'status',
    label: 'Status',
    render: (u) => (
      <span className="inline-flex gap-1.5">
        <GuestBadges user={u} />
      </span>
    ),
  },
  {
    id: 'instagram',
    label: 'Instagram',
    render: (u) =>
      u.instagram ? <span translate="no">@{u.instagram}</span> : <span className="text-ink-muted">–</span>,
  },
  {
    id: 'photos',
    label: 'Fotos',
    align: 'end',
    allowsSorting: true,
    render: (u) => formatNumber(u.photo_count),
  },
  {
    id: 'seen',
    label: 'Zuletzt',
    allowsSorting: true,
    hideBelow: 'sm',
    render: (u) => (
      <time dateTime={u.last_seen_at} title={formatDateTime(u.last_seen_at)}>
        {formatRelative(u.last_seen_at)}
      </time>
    ),
  },
  { id: 'device', label: 'Gerät', hideBelow: 'md', render: (u) => describeUA(u.user_agent) },
];

function compare(column: string, a: AdminUser, b: AdminUser): number {
  switch (column) {
    case 'name':
      return a.name.localeCompare(b.name, 'de');
    case 'photos':
      return a.photo_count - b.photo_count;
    case 'seen':
      return a.last_seen_at < b.last_seen_at ? -1 : a.last_seen_at > b.last_seen_at ? 1 : 0;
    default:
      return a.id - b.id;
  }
}

/** Gäste: search, status filter, the guests as a table; a row opens the user page. */
export function GuestsSection() {
  const [params, setParams] = useSearchParams();
  const [, navigate] = useLocation();
  const filter = parseGuestFilter(params);
  const [search, setSearch] = useState(filter.search);
  const [sort, setSort] = useState<SortDescriptor>({ column: 'id', direction: 'descending' });
  const list = useGuestList(filter);
  const { data: stats } = useStats();

  // typing updates the URL (and the query) 250 ms after the last key
  useEffect(() => {
    if (search.trim() === filter.search.trim()) return undefined;
    const timer = window.setTimeout(
      () => setParams((prev) => withParams(prev, { q: search.trim() }), { replace: true }),
      250,
    );
    return () => window.clearTimeout(timer);
  }, [search, filter.search, setParams]);

  const users = list.data?.pages.flatMap((p) => p.users) ?? [];
  const rows = sortedCopy(users, (a, b) => {
    const order = compare(String(sort.column), a, b);
    return sort.direction === 'descending' ? -order : order;
  });
  const filtered = filter.search !== '' || filter.status !== 'all';
  const count = filtered
    ? `${formatNumber(users.length)}${list.hasNextPage ? '+' : ''} Treffer`
    : stats
      ? guestCount(stats.guests)
      : '';

  return (
    <section aria-labelledby="section-title" className="grid content-start gap-4 px-4 py-4 lg:px-6 lg:py-5">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 id="section-title" tabIndex={-1} className="text-xl font-bold outline-none">
          Gäste
        </h1>
        <span className="text-sm text-ink-muted tabular" data-testid="guest-count">
          {count}
        </span>
      </header>
      <div className="flex flex-wrap items-end gap-2">
        <TextField
          label="Gäste suchen"
          hideLabel
          type="search"
          icon={Search}
          size="sm"
          placeholder="Name, @instagram oder #Nummer…"
          autoComplete="off"
          spellCheck="false"
          maxLength={100}
          value={search}
          onChange={setSearch}
          className="w-full max-w-sm"
        />
        <Select
          label="Status"
          inlineLabel
          size="sm"
          options={STATUS_OPTIONS}
          value={filter.status}
          onChange={(status) => setParams((prev) => withParams(prev, { show: status }), { replace: true })}
          data-testid="guest-filter"
          className="min-w-0"
        />
      </div>
      <DataTable
        aria-label="Gäste"
        columns={COLUMNS}
        rows={rows}
        getRowId={(u) => u.id}
        rowProps={(u) => ({ 'data-testid': 'guest-row', 'data-id': u.id, 'data-banned': u.banned })}
        sortDescriptor={sort}
        onSortChange={setSort}
        onRowAction={(id) => navigate(`/user?id=${String(id)}`)}
        isLoading={list.isPending}
        maxHeightClass="max-h-none"
        emptyState={
          <div className="px-4">
            <EmptyState
              icon={Users}
              title={filter.search ? `Niemand passt zu ${quoted(filter.search)}.` : 'Keine Gäste'}
            >
              {filtered ? 'Probier einen anderen Filter.' : 'Sobald jemand beitritt, steht er hier.'}
            </EmptyState>
          </div>
        }
      />
      {list.hasNextPage ? (
        <div className="grid place-items-center">
          <Button
            variant="secondary"
            size="sm"
            isPending={list.isFetchingNextPage}
            onPress={() => void list.fetchNextPage()}
            data-testid="more"
          >
            Mehr laden
          </Button>
        </div>
      ) : null}
    </section>
  );
}
