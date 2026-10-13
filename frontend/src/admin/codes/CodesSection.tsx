/**
 * QR-Codes (`/admin/manage?tab=qr`): every code with its number, animal name, Ziel,
 * Notiz and numbers; revoked ones („gelöscht“) stay grey in the list. A row opens the
 * code's sheet (`&code=<id>`, also as a deep link); „Gelöschte zeigen“ is `&deleted=1`.
 * The numbers refresh every 15 s and with each `code.changed` event.
 */
import { useQueryClient } from '@tanstack/react-query';
import { Plus, QrCode } from 'lucide-react';
import { useState } from 'react';
import { useSearchParams } from 'wouter';
import { formatDateTime, formatNumber, formatRelative } from '@/lib/format';
import { Badge } from '@/ui/Badge';
import { Button } from '@/ui/Button';
import { ConfirmDialog } from '@/ui/ConfirmDialog';
import { DataTable, type DataColumn } from '@/ui/DataTable';
import { EmptyState } from '@/ui/EmptyState';
import { HelpDisclosure } from '@/ui/HelpDisclosure';
import { Switch } from '@/ui/Switch';
import { showToast } from '@/ui/Toast';
import { errorText } from '../common/usePhotoActions';
import { parseCodeParam, withParams } from '../manage/manageUrl';
import { partyOrigin, revokeCode, useActivities, useCodes, type Activities, type AdminCode } from './api';
import { CodeSheet, type CodeAction } from './CodeSheet';
import { codeNumber, countText, revokedTitle, targetLabel } from './codeUrl';
import { EditCodeSheet } from './EditCodeSheet';
import { NewCodeSheet } from './NewCodeSheet';
import { TokenSheet } from './TokenSheet';

function columns(activities: Activities): ReadonlyArray<DataColumn<AdminCode>> {
  return [
    { id: 'id', label: 'Nr.', width: 'w-16', render: (c) => codeNumber(c.id) },
    {
      id: 'name',
      label: 'Name',
      isRowHeader: true,
      render: (c) => <span className="font-semibold">{c.name}</span>,
    },
    {
      id: 'target',
      label: 'Ziel',
      render: (c) => {
        const label = targetLabel(c.target, activities.byId);
        const missing = c.target !== '' && !activities.byId.has(c.target);
        return <span className={missing ? 'text-ink-muted italic' : undefined}>{label}</span>;
      },
    },
    {
      id: 'note',
      label: 'Notiz',
      hideBelow: 'md',
      render: (c) =>
        c.note ? (
          <span title={c.note} className="block max-w-[14rem] truncate">
            {c.note}
          </span>
        ) : (
          <span className="text-ink-muted">–</span>
        ),
    },
    { id: 'scans', label: 'Gescannt', align: 'end', render: (c) => formatNumber(c.stats.scans) },
    {
      id: 'people',
      label: 'Personen',
      align: 'end',
      hideBelow: 'md',
      render: (c) => formatNumber(c.stats.people),
    },
    { id: 'guests', label: 'Beigetreten', align: 'end', render: (c) => formatNumber(c.stats.guests) },
    { id: 'photos', label: 'Fotos', align: 'end', render: (c) => formatNumber(c.stats.photos) },
    {
      id: 'last',
      label: 'Zuletzt gescannt',
      hideBelow: 'md',
      render: (c) =>
        c.stats.last_scan_at ? (
          <time dateTime={c.stats.last_scan_at} title={formatDateTime(c.stats.last_scan_at)}>
            {formatRelative(c.stats.last_scan_at)}
          </time>
        ) : (
          <span className="text-ink-muted">–</span>
        ),
    },
    {
      id: 'status',
      label: 'Status',
      render: (c) =>
        c.active ? (
          <Badge tone="ok">Aktiv</Badge>
        ) : (
          <span title={c.revoked_at ? revokedTitle(c.revoked_at) : undefined}>
            <Badge>Gelöscht</Badge>
          </span>
        ),
    },
  ];
}

export function CodesSection() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const codesQuery = useCodes();
  const activities = useActivities();
  const [creating, setCreating] = useState(false);
  const [action, setAction] = useState<CodeAction | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const data = codesQuery.data;
  const codes = data?.codes ?? [];
  const showRevoked = params.get('deleted') === '1';
  const openId = parseCodeParam(params);
  const open = openId === null ? undefined : codes.find((c) => c.id === openId);
  const origin = partyOrigin(data?.base_url);
  const rows = showRevoked ? codes : codes.filter((c) => c.active);
  const active = data?.active ?? 0;

  const openCode = (id: number | null) => {
    setAction(null);
    // a sheet is no page of its own: no history entry, but a link that opens it
    setParams((prev) => withParams(prev, { code: id }), { replace: true });
  };

  const revoke = async (code: AdminCode) => {
    setDeleteError(null);
    try {
      await revokeCode(qc, code.id);
      showToast({ message: `${code.name} gelöscht.`, tone: 'success' });
      openCode(null);
    } catch (err) {
      setDeleteError(errorText(err));
      throw err;
    }
  };

  const columnList = columns(activities);
  return (
    <section aria-labelledby="section-title" className="grid content-start gap-4 px-4 py-4 lg:px-6 lg:py-5">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 id="section-title" tabIndex={-1} className="text-xl font-bold outline-none">
            QR-Codes
          </h1>
          {data ? (
            <span className="text-sm text-ink-muted tabular" data-testid="code-count">
              {countText(data.active, data.revoked)}
            </span>
          ) : null}
        </div>
        <Switch
          isSelected={showRevoked}
          onChange={(on) =>
            setParams((prev) => withParams(prev, { deleted: on ? '1' : null }), { replace: true })
          }
          data-testid="show-revoked"
        >
          Gelöschte zeigen
        </Switch>
        <Button
          variant="primary"
          size="sm"
          icon={Plus}
          onPress={() => setCreating(true)}
          data-testid="new-code"
        >
          Neuer QR-Code
        </Button>
      </header>
      <HelpDisclosure summary="Wie funktionieren die Codes?">
        <p>
          Jeder Code hat eine feste Nummer und einen Tiernamen, z. B. „Gorilla 2“. Nummern werden nie neu
          vergeben: Gelöschte Codes bleiben grau in der Liste, mit ihren Zahlen. Wer über einen Code
          beigetreten ist, bleibt dabei, auch wenn der Code gelöscht oder sein Token geändert wird.
        </p>
      </HelpDisclosure>
      {data && active === 0 ? (
        <EmptyState
          icon={QrCode}
          title="Kein aktiver QR-Code"
          action={
            <Button variant="primary" size="sm" icon={Plus} onPress={() => setCreating(true)}>
              Neuer QR-Code
            </Button>
          }
          className="py-2"
        >
          Ohne aktiven Code kommt niemand Neues auf die Party. Leg einen neuen an.
        </EmptyState>
      ) : null}
      {codesQuery.isError && !data ? (
        <EmptyState
          icon={QrCode}
          title="Die QR-Codes sind gerade nicht erreichbar"
          action={<Button onPress={() => void codesQuery.refetch()}>Erneut laden</Button>}
        >
          {codesQuery.error.message}
        </EmptyState>
      ) : null}
      {rows.length > 0 || !data ? (
        <DataTable
          aria-label="QR-Codes"
          data-testid="codes"
          columns={columnList}
          rows={rows}
          getRowId={(c) => c.id}
          rowProps={(c) => ({ 'data-testid': 'code-row', 'data-id': c.id, 'data-revoked': !c.active })}
          onRowAction={(id) => openCode(Number(id))}
          isLoading={codesQuery.isPending}
          maxHeightClass="max-h-none"
          className="min-w-0 [&_[data-revoked=true]_td]:text-ink-muted"
        />
      ) : null}
      {open ? (
        <>
          <CodeSheet
            code={open}
            baseUrl={data?.base_url ?? null}
            activities={activities}
            isOpen={action === null}
            onOpenChange={(isOpen) => {
              if (!isOpen) openCode(null);
            }}
            onAction={(next) => {
              setDeleteError(null);
              setAction(next);
            }}
          />
          <TokenSheet
            code={open}
            isOpen={action === 'token'}
            onOpenChange={(isOpen) => !isOpen && setAction(null)}
            activities={activities}
            partyOrigin={origin}
          />
          <EditCodeSheet
            code={open}
            isOpen={action === 'edit'}
            onOpenChange={(isOpen) => !isOpen && setAction(null)}
            activities={activities}
          />
          <ConfirmDialog
            isOpen={action === 'delete'}
            onOpenChange={(isOpen) => !isOpen && setAction(null)}
            title={`${open.name} löschen?`}
            confirmLabel="Löschen"
            onConfirm={() => revoke(open)}
            error={deleteError}
            data-testid="code-delete-dialog"
          >
            <p>
              Gedruckte Codes mit diesem Token funktionieren danach nicht mehr. Wer darüber schon beigetreten
              ist, bleibt dabei. Nummer und Name werden nie neu vergeben: {open.name} bleibt grau in der
              Liste, mit seinen Zahlen.
            </p>
            {open.active && active === 1 ? (
              <p className="font-semibold" data-testid="last-code-warning">
                Das ist der letzte aktive Code: Danach kommt niemand Neues mehr auf die Party.
              </p>
            ) : null}
          </ConfirmDialog>
        </>
      ) : null}
      <NewCodeSheet
        isOpen={creating}
        onOpenChange={setCreating}
        activities={activities}
        partyOrigin={origin}
        onCreated={(code) => openCode(code.id)}
      />
    </section>
  );
}
