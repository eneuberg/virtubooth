import { Search, Users } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import type { SortDescriptor } from 'react-aria-components';
import { useLocation, useSearchParams } from 'wouter';
import type { AdminUser } from '@/api/types';
import type { SelectOption } from '@/ui/Select';
import { formatDateTime, formatDuration, formatNumber, formatRelative } from '@/lib/format';
import { Button } from '@/ui/Button';
import { DataTable, type DataColumn } from '@/ui/DataTable';
import { EmptyState } from '@/ui/EmptyState';
import { Select } from '@/ui/Select';
import { TextField } from '@/ui/TextField';
import { fetchCodes } from '../codes/api';
import { codesKey, type CodesList } from '../codes/keys';
import { GuestBadges } from '../common/GuestBadges';
import { HostGuestButton } from '../hostGuest/HostGuestButton';
import { HOST_CODE } from '../hostGuest/marks';
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

/** The „QR-Code“ filter's choice for every guest. */
const ALL_CODES = 0;

/** „Alle“, then every code by number; deleted ones marked (their guests stay). */
function codeOptions(list: CodesList | undefined, current: number | null): SelectOption<number>[] {
  const codes = (list?.codes ?? []).map((c) => ({
    id: c.id,
    label: c.active ? c.name : `${c.name} (gelöscht)`,
  }));
  if (current !== null && !codes.some((c) => c.id === current))
    codes.push({ id: current, label: `#${current}` });
  return [{ id: ALL_CODES, label: 'Alle' }, ...codes];
}

/** The visible time added up; a green dot while the page is open right now. */
function OnlineTime({ user }: { user: AdminUser }) {
  return (
    <span className="inline-flex items-center gap-1.5" data-testid="guest-online">
      {user.online_now ? (
        <span title="Seite gerade offen" className="inline-flex">
          <span aria-hidden="true" className="size-2 rounded-full bg-ok" />
          <span className="sr-only">gerade online</span>
        </span>
      ) : null}
      <span className={user.online_seconds > 0 ? undefined : 'text-ink-muted'}>
        {formatDuration(user.online_seconds)}
      </span>
    </span>
  );
}

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
      <span translate="no" className="grid">
        <span className="font-semibold">{u.name}</span>
        {u.display_name ? (
          <span className="text-xs text-ink-muted" data-testid="guest-display-name">
            nennt sich „{u.display_name}“
          </span>
        ) : null}
      </span>
    ),
  },
  {
    id: 'status',
    label: 'Status',
    render: (u) => (
      <span className="inline-flex flex-wrap gap-1.5">
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
    id: 'online',
    label: 'Online',
    align: 'end',
    allowsSorting: true,
    hideBelow: 'md',
    render: (u) => <OnlineTime user={u} />,
  },
  {
    id: 'code',
    label: 'QR-Code',
    allowsSorting: true,
    hideBelow: 'md',
    render: (u) =>
      u.is_host ? (
        <span className="text-ink-muted" data-testid="guest-code">
          {HOST_CODE}
        </span>
      ) : u.code ? (
        <span
          translate="no"
          className={u.code.active ? undefined : 'text-ink-muted'}
          title={u.code.active ? undefined : 'Code gelöscht'}
          data-testid="guest-code"
        >
          {u.code.name}
        </span>
      ) : (
        <span className="text-ink-muted">–</span>
      ),
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
  {
    id: 'device',
    label: 'Gerät',
    hideBelow: 'md',
    // an unknown browser shows its raw user agent: cut it off, the full text is the tooltip
    render: (u) => (
      <span title={u.user_agent || undefined} className="block max-w-56 truncate">
        {describeUA(u.user_agent)}
      </span>
    ),
  },
];

function compare(column: string, a: AdminUser, b: AdminUser): number {
  switch (column) {
    case 'name':
      return a.name.localeCompare(b.name, 'de');
    case 'photos':
      return a.photo_count - b.photo_count;
    case 'online':
      return a.online_seconds - b.online_seconds || Number(a.online_now) - Number(b.online_now);
    case 'code':
      return (a.code?.id ?? 0) - (b.code?.id ?? 0);
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
  const codes = useQuery({ queryKey: codesKey, queryFn: fetchCodes });
  const codeChoices = useMemo(() => codeOptions(codes.data, filter.code), [codes.data, filter.code]);

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
  const filtered = filter.search !== '' || filter.status !== 'all' || filter.code !== null;
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
        <Select
          label="QR-Code"
          inlineLabel
          size="sm"
          options={codeChoices}
          value={filter.code ?? ALL_CODES}
          onChange={(code) =>
            setParams((prev) => withParams(prev, { code: code === ALL_CODES ? null : code }), {
              replace: true,
            })
          }
          data-testid="guest-code-filter"
          className="min-w-0"
        />
      </div>
      <HostGuestButton hint variant="secondary" size="sm" />
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
