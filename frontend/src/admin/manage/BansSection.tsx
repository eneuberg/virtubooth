import { useQueryClient } from '@tanstack/react-query';
import { ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-aria-components';
import type { AdminUser, DeviceBan } from '@/api/types';
import { formatDateTime, formatNumber, formatRelative } from '@/lib/format';
import { quoted } from '@/lib/messages.de';
import { Button } from '@/ui/Button';
import { DataTable, type DataColumn } from '@/ui/DataTable';
import { EmptyState } from '@/ui/EmptyState';
import { HelpDisclosure } from '@/ui/HelpDisclosure';
import { showToast } from '@/ui/Toast';
import { GuestBadges } from '../common/GuestBadges';
import { showError } from '../common/usePhotoActions';
import { deviceCount, releasedText, shortHash } from '../lib/labels';
import { liftDeviceBan, unbanUser } from '../store/actions';
import { useBannedUsers, useDeviceBans } from '../store/hooks';

const LINK =
  'font-semibold text-ink underline decoration-line-strong underline-offset-3 outline-none hover:decoration-ink focus-visible:outline-2 focus-visible:outline-focus';

function when(iso: string | null) {
  return iso ? (
    <time dateTime={iso} title={formatDateTime(iso)}>
      {formatRelative(iso)}
    </time>
  ) : (
    '–'
  );
}

/** Sperren: banned guests and banned device traits, each one tap to lift. */
export function BansSection() {
  const qc = useQueryClient();
  const users = useBannedUsers();
  const bans = useDeviceBans();
  const [busy, setBusy] = useState<string | null>(null);

  const unban = async (user: AdminUser) => {
    setBusy(`user:${user.id}`);
    try {
      await unbanUser(qc, user.id, false);
      showToast({ message: `${user.name} ist entsperrt`, tone: 'success' });
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
  };

  const lift = async (ban: DeviceBan) => {
    setBusy(`fp:${ban.fp_hash}`);
    try {
      const res = await liftDeviceBan(qc, ban.fp_hash);
      showToast({
        message: `Gerätemerkmal entsperrt${releasedText(res.users_unbanned.length)}`,
        tone: 'success',
      });
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
  };

  const userColumns: ReadonlyArray<DataColumn<AdminUser>> = [
    {
      id: 'name',
      label: 'Gast',
      isRowHeader: true,
      render: (u) => (
        <span className="inline-flex items-center gap-2">
          <Link href={`/user?id=${u.id}`} translate="no" className={LINK}>
            {u.name}
          </Link>
          {u.auto_banned ? <GuestBadges user={u} /> : null}
        </span>
      ),
    },
    {
      id: 'reason',
      label: 'Grund',
      render: (u) =>
        u.auto_banned ? (
          <span className="text-ink-muted">
            Gleiches Gerätemerkmal wie{' '}
            {u.auto_ban?.source_user_name ? quoted(u.auto_ban.source_user_name) : 'ein gesperrter Gast'}
          </span>
        ) : (
          u.ban_reason || <span className="text-ink-muted">–</span>
        ),
    },
    { id: 'since', label: 'Seit', render: (u) => when(u.banned_at) },
    { id: 'photos', label: 'Fotos', align: 'end', render: (u) => formatNumber(u.photo_count) },
    {
      id: 'action',
      label: 'Aktion',
      align: 'end',
      render: (u) => (
        <Button
          size="xs"
          variant="secondary"
          isPending={busy === `user:${u.id}`}
          onPress={() => void unban(u)}
          aria-label={`${u.name} entsperren`}
          data-testid="unban-user"
        >
          Entsperren
        </Button>
      ),
    },
  ];

  const banColumns: ReadonlyArray<DataColumn<DeviceBan>> = [
    {
      id: 'hash',
      label: 'Gerätemerkmal',
      isRowHeader: true,
      render: (b) => (
        <span title={b.fp_hash} className="font-semibold tabular">
          {shortHash(b.fp_hash)}
        </span>
      ),
    },
    { id: 'reason', label: 'Grund', render: (b) => b.reason || <span className="text-ink-muted">–</span> },
    { id: 'since', label: 'Seit', render: (b) => when(b.created_at) },
    {
      id: 'source',
      label: 'Gesperrt über',
      render: (b) =>
        b.source_user_id ? (
          <Link href={`/user?id=${b.source_user_id}`} translate="no" className={LINK}>
            {b.source_user_name ?? `Gast #${b.source_user_id}`}
          </Link>
        ) : (
          '–'
        ),
    },
    {
      id: 'devices',
      label: 'Geräte',
      render: (b) => {
        const auto = b.users.filter((u) => u.auto_banned).length;
        return (
          <span>
            {deviceCount(b.users.length)}
            {auto > 0 ? (
              <span data-testid="fp-auto-note" className="text-ink-muted">
                , {formatNumber(auto)} nur deshalb gesperrt
              </span>
            ) : null}
          </span>
        );
      },
    },
    {
      id: 'action',
      label: 'Aktion',
      align: 'end',
      render: (b) => (
        <Button
          size="xs"
          variant="secondary"
          isPending={busy === `fp:${b.fp_hash}`}
          onPress={() => void lift(b)}
          aria-label={`Gerätemerkmal ${shortHash(b.fp_hash)} entsperren`}
          data-testid="unban-fp"
        >
          Entsperren
        </Button>
      ),
    },
  ];

  return (
    <section aria-labelledby="section-title" className="grid content-start gap-6 px-4 py-4 lg:px-6 lg:py-5">
      <header className="grid gap-1">
        <h1 id="section-title" tabIndex={-1} className="text-xl font-bold outline-none">
          Sperren
        </h1>
        <p className="max-w-prose text-sm text-ink-muted">
          Gesperrte Gäste können nichts hochladen, ihre Fotos sind ausgeblendet. Entsperren holt nur die Fotos
          zurück, die durch die Sperre ausgeblendet wurden.
        </p>
      </header>
      <section aria-labelledby="bans-users" className="grid gap-3" data-testid="banned-users">
        <h2 id="bans-users" className="flex items-baseline gap-2 text-lg font-bold">
          Gesperrte Gäste
          <span className="text-sm font-normal text-ink-muted tabular">{users.data?.length ?? ''}</span>
        </h2>
        <DataTable
          aria-label="Gesperrte Gäste"
          columns={userColumns}
          rows={users.data ?? []}
          getRowId={(u) => u.id}
          rowProps={(u) => ({
            'data-testid': 'banned-user-row',
            'data-id': u.id,
            'data-auto': u.auto_banned,
          })}
          isLoading={users.isPending}
          maxHeightClass="max-h-none"
          emptyState={
            <div className="px-4">
              <EmptyState icon={ShieldCheck} title="Niemand gesperrt" />
            </div>
          }
        />
      </section>
      <section aria-labelledby="bans-devices" className="grid gap-3" data-testid="device-bans">
        <h2 id="bans-devices" className="flex items-baseline gap-2 text-lg font-bold">
          Gesperrte Gerätemerkmale
          <span className="text-sm font-normal text-ink-muted tabular">{bans.data?.length ?? ''}</span>
        </h2>
        <HelpDisclosure summary="Was ist ein Gerätemerkmal?">
          <p>
            Ein Merkmal des Geräts (Bildschirm, Grafik, Sprache und Ähnliches), keine Identität. Neue Geräte
            mit einem gesperrten Merkmal starten automatisch gesperrt.
          </p>
          <p>
            Gleiche Handymodelle haben oft dasselbe Merkmal, dann trifft es auch Unbeteiligte. Bereits
            bekannte Gäste sind nicht betroffen. Entsperren hebt auch die automatischen Sperren auf, die nur
            an diesem Merkmal hängen.
          </p>
        </HelpDisclosure>
        <DataTable
          aria-label="Gesperrte Gerätemerkmale"
          columns={banColumns}
          rows={bans.data ?? []}
          getRowId={(b) => b.fp_hash}
          rowProps={() => ({ 'data-testid': 'fp-ban-row' })}
          isLoading={bans.isPending}
          maxHeightClass="max-h-none"
          emptyState={
            <div className="px-4">
              <EmptyState icon={ShieldCheck} title="Keine Gerätemerkmal-Sperren" />
            </div>
          }
        />
      </section>
    </section>
  );
}
