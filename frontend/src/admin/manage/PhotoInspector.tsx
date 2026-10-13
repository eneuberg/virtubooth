import { AtSign, Download, Eye, EyeOff, ImageOff, Trash2, X } from 'lucide-react';
import { Link } from 'react-aria-components';
import type { AdminExtension, AdminPhoto } from '@/api/types';
import { formatDateTime, formatRelative } from '@/lib/format';
import { t } from '@/lib/messages.de';
import { Badge } from '@/ui/Badge';
import { Button, LinkButton } from '@/ui/Button';
import { cx } from '@/ui/cx';
import { EmptyState } from '@/ui/EmptyState';
import { GreaseX } from '@/ui/GreaseMarks';
import { IconButton } from '@/ui/IconButton';
import { metaRows, photoLabel } from '../lib/labels';

export interface PhotoInspectorProps {
  photo: AdminPhoto | null;
  /** the deep-linked photo does not exist (any more) */
  gone?: boolean;
  extension: AdminExtension | undefined;
  onClose: () => void;
  onToggleHidden: (photo: AdminPhoto) => void;
  onDelete: (photo: AdminPhoto) => void;
  onCopyHandle: (handle: string) => void;
  busy: boolean;
}

/** "bier-00032.jpg", as the server names the download. */
function downloadName(photo: AdminPhoto): string {
  return `${photo.extension}-${String(photo.seq).padStart(5, '0')}.jpg`;
}

const LINK =
  'font-semibold text-ink underline decoration-line-strong underline-offset-3 outline-none hover:decoration-ink focus-visible:outline-2 focus-visible:outline-focus';

/**
 * The right column of the desktop contact sheet: the open photo big, who took it, when,
 * with which settings, and every action on it. `?photo=<id>` opens it.
 */
export function PhotoInspector({
  photo,
  gone = false,
  extension,
  onClose,
  onToggleHidden,
  onDelete,
  onCopyHandle,
  busy,
}: PhotoInspectorProps) {
  if (!photo && gone) {
    return (
      <aside aria-label="Foto" className="grid content-start px-5 py-4" data-testid="inspector">
        <EmptyState icon={ImageOff} title="Dieses Foto gibt es nicht mehr.">
          Es wurde gelöscht. Im Protokoll steht, wann und von wem.
        </EmptyState>
      </aside>
    );
  }
  if (!photo) {
    return (
      <aside aria-label="Foto" className="grid content-start px-5 py-4" data-testid="inspector">
        <EmptyState icon={ImageOff} title="Kein Foto offen">
          Klick ein Foto an, um es hier groß zu sehen. Mit den Pfeiltasten gehst du durch den Bogen, X blendet
          aus, Entf löscht.
        </EmptyState>
      </aside>
    );
  }
  const label = photoLabel(photo);
  return (
    <aside
      aria-label={`Foto ${label}`}
      className="grid content-start gap-4 px-5 py-4"
      data-testid="inspector"
    >
      <div className="relative aspect-[3/4] overflow-hidden bg-surface-sunk">
        <img
          key={photo.id}
          src={photo.url}
          alt={label}
          width={photo.width}
          height={photo.height}
          className={cx('size-full object-cover', photo.hidden && 'opacity-45 grayscale-[0.6]')}
        />
        {photo.hidden ? (
          <GreaseX className="pointer-events-none absolute inset-[8%] size-[84%] text-mark" />
        ) : null}
      </div>
      <div className="flex items-start gap-2">
        <div className="grid min-w-0 flex-1 gap-1">
          <h2 className="text-lg font-bold tabular">{label}</h2>
          <Link
            href={`/user?id=${photo.user.id}`}
            translate="no"
            className={cx(LINK, 'truncate')}
            data-testid="user-link"
          >
            {photo.user.name}
          </Link>
        </div>
        <IconButton label="Schließen" icon={X} onPress={onClose} />
      </div>
      {photo.hidden ? (
        <Badge tone="mark" className="justify-self-start">
          {photo.hidden_reason === 'ban' ? 'Ausgeblendet, Gast gesperrt' : 'Ausgeblendet'}
        </Badge>
      ) : null}
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-5 gap-y-1.5 text-sm">
        <dt className="text-ink-muted">Instagram</dt>
        <dd translate="no" className="truncate">
          {photo.user.instagram ? `@${photo.user.instagram}` : 'ohne'}
        </dd>
        <dt className="text-ink-muted">Aufgenommen</dt>
        <dd>
          <time dateTime={photo.created_at} title={formatDateTime(photo.created_at)}>
            {formatRelative(photo.created_at)}
          </time>
        </dd>
        {metaRows(photo, extension).map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-ink-muted">{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      <div className="grid gap-2">
        <Button
          size="sm"
          variant="secondary"
          icon={photo.hidden ? Eye : EyeOff}
          isPending={busy}
          onPress={() => onToggleHidden(photo)}
          data-testid="toggle"
        >
          {photo.hidden ? t.unhide : t.hide}
        </Button>
        <LinkButton
          size="sm"
          variant="secondary"
          icon={Download}
          href={`${photo.url}?download=1`}
          download={downloadName(photo)}
          data-testid="download"
        >
          {t.download}
        </LinkButton>
        {photo.user.instagram ? (
          <Button
            size="sm"
            variant="secondary"
            icon={AtSign}
            onPress={() => onCopyHandle(photo.user.instagram ?? '')}
            data-testid="copy-handle"
          >
            Instagram-Namen kopieren
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="danger-outline"
          icon={Trash2}
          onPress={() => onDelete(photo)}
          data-testid="delete"
        >
          {t.deleteEllipsis}
        </Button>
      </div>
    </aside>
  );
}
