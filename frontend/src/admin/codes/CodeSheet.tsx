/**
 * One QR code: its link, token, Ziel, Notiz and numbers, and what can be done with it
 * (active codes only): „Token ändern…“, „Bearbeiten…“, „Löschen…“.
 */
import { Copy, KeyRound, Pencil, Trash2 } from 'lucide-react';
import type { ReactNode } from 'react';
import { formatDateTime, formatNumber, formatRelative } from '@/lib/format';
import { Button } from '@/ui/Button';
import { Sheet } from '@/ui/Sheet';
import { showToast } from '@/ui/Toast';
import { copyText } from '../lib/browser';
import { auditActor } from '../lib/labels';
import type { Activities, AdminCode } from './api';
import { codeUrl, revokedTitle, scansText, targetLabel } from './codeUrl';

export type CodeAction = 'token' | 'edit' | 'delete';

function Row({ label, children, testid }: { label: string; children: ReactNode; testid?: string }) {
  return (
    <div className="grid gap-0.5 sm:grid-cols-[10rem_minmax(0,1fr)] sm:gap-4">
      <dt className="text-sm text-ink-muted">{label}</dt>
      <dd className="min-w-0 break-words" data-testid={testid}>
        {children}
      </dd>
    </div>
  );
}

function capitalized(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function when(iso: string | null, relative = false) {
  if (!iso) return '–';
  return (
    <time dateTime={iso} title={formatDateTime(iso)}>
      {relative ? formatRelative(iso) : formatDateTime(iso)}
    </time>
  );
}

export function CodeSheet({
  code,
  baseUrl,
  activities,
  isOpen,
  onOpenChange,
  onAction,
}: {
  code: AdminCode;
  baseUrl: string | null;
  activities: Activities;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onAction: (action: CodeAction) => void;
}) {
  const url = codeUrl(baseUrl, code.entry_path, window.location.origin);
  const { stats } = code;
  const copy = async () => {
    const ok = await copyText(url);
    showToast(
      ok
        ? { message: 'Link kopiert.', tone: 'success' }
        : { message: 'Kopieren ging nicht. Markier den Link und kopier ihn selbst.', tone: 'error' },
    );
  };
  const unavailable = code.target !== '' && !activities.byId.has(code.target);

  return (
    <Sheet
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title={code.name}
      description={`QR-Code Nr. ${code.id}`}
      size="lg"
      data-testid="code-sheet"
      footer={
        code.active ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Button size="sm" icon={KeyRound} onPress={() => onAction('token')} data-testid="code-token">
              Token ändern…
            </Button>
            <Button size="sm" icon={Pencil} onPress={() => onAction('edit')} data-testid="code-edit">
              Bearbeiten…
            </Button>
            <Button
              size="sm"
              variant="danger-outline"
              icon={Trash2}
              onPress={() => onAction('delete')}
              className="col-span-2 sm:col-span-1"
              data-testid="code-delete"
            >
              Löschen…
            </Button>
          </div>
        ) : undefined
      }
    >
      <div className="grid gap-5">
        {code.active ? null : (
          <p className="rounded-small bg-surface-sunk px-3 py-2 text-sm" data-testid="code-revoked">
            {code.revoked_at ? capitalized(revokedTitle(code.revoked_at)) : 'Gelöscht'}. Sein Token
            funktioniert nicht mehr; wer darüber beigetreten ist, bleibt dabei.
          </p>
        )}
        <section aria-label="Link" className="grid gap-2">
          <h3 className="text-sm text-ink-muted">Link</h3>
          <code
            className="block rounded-small bg-surface-sunk px-3 py-2 text-sm break-all select-all"
            data-testid="code-url"
          >
            {url}
          </code>
          {code.active ? (
            <div>
              <Button size="xs" icon={Copy} onPress={() => void copy()} data-testid="code-copy">
                Link kopieren
              </Button>
            </div>
          ) : null}
        </section>
        {/*
          Exports of this code (integration step): „QR als PNG“, „QR groß (PDF)“,
          „Plakat (PDF)“ go into this slot.
        */}
        <div data-slot="code-exports" className="empty:hidden" />
        <dl className="grid gap-3">
          <Row label="Token" testid="code-token-value">
            <code className="text-sm break-all">{code.token}</code>
          </Row>
          <Row label="Ziel" testid="code-target-value">
            <span className={unavailable ? 'text-ink-muted' : undefined}>
              {targetLabel(code.target, activities.byId)}
            </span>
          </Row>
          <Row label="Notiz">{code.note || '–'}</Row>
          <Row label="Angelegt">
            {when(code.created_at)}
            {code.created_by === 'system' ? ' (beim ersten Start)' : ` von ${auditActor(code.created_by)}`}
          </Row>
        </dl>
        <section aria-labelledby="code-stats" className="grid gap-3">
          <h3 id="code-stats" className="text-md font-bold">
            Zahlen
          </h3>
          <dl className="grid gap-3" data-testid="code-stats">
            <Row label="Gescannt">{scansText(stats.scans, stats.people)}</Row>
            <Row label="Beigetreten" testid="code-stat-guests">
              {formatNumber(stats.guests)}
            </Row>
            <Row label="Noch nicht beigetreten">{formatNumber(stats.not_joined)}</Row>
            <Row label="Fotos">{formatNumber(stats.photos)}</Row>
            <Row label="Aktiv jetzt">{formatNumber(stats.active_now)}</Row>
            <Row label="Zuerst gescannt">{when(stats.first_scan_at)}</Row>
            <Row label="Zuletzt gescannt">{when(stats.last_scan_at, true)}</Row>
          </dl>
        </section>
      </div>
    </Sheet>
  );
}
