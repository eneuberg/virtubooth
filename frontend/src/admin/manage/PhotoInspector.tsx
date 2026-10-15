import { AtSign, Download, Eye, EyeOff, ImageOff, SquareCheck, Trash2, X } from 'lucide-react';
import { useState } from 'react';
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
import { downloadHref, hasFilterChoice, hasOriginal, useAdminPhotoSrc } from '@/lib/photoFilter';
import { FilterToggle } from '../common/FilterToggle';
import { FittedPhoto } from '../common/FittedPhoto';
import { metaRows, photoCount, photoLabel, photoName } from '../lib/labels';
import { AnalysisBoxes, AnalysisPanel } from '../wall/AnalysisPanel';
import { guestName } from '../hostGuest/marks';

export interface PhotoInspectorProps {
  photo: AdminPhoto | null;
  /** the photos ticked in the contact sheet: while there are any, they are shown instead */
  selection?: ReadonlyArray<AdminPhoto>;
  /** the deep-linked photo does not exist (any more) */
  gone?: boolean;
  extension: AdminExtension | undefined;
  onClose: () => void;
  onToggleHidden: (photo: AdminPhoto) => void;
  onDelete: (photo: AdminPhoto) => void;
  onCopyHandle: (handle: string) => void;
  busy: boolean;
}

/** "bier-00032.jpg" („-original“: without the filter), as the server names the download. */
function downloadName(photo: AdminPhoto, original = false): string {
  return `${photo.extension}-${String(photo.seq).padStart(5, '0')}${original ? '-original' : ''}.jpg`;
}

/** The open photo, under „Filter zeigen“. */
function InspectorImage({ photo, label }: { photo: AdminPhoto; label: string }) {
  const src = useAdminPhotoSrc(photo);
  return (
    <img
      key={photo.id}
      src={src}
      alt={label}
      width={photo.width}
      height={photo.height}
      data-testid="inspector-img"
      data-variant={src === photo.url ? 'filtered' : 'raw'}
      className={cx('size-full object-cover', photo.hidden && 'opacity-45 grayscale-[0.6]')}
    />
  );
}

const LINK =
  'font-semibold text-ink underline decoration-line-strong underline-offset-3 outline-none hover:decoration-ink focus-visible:outline-2 focus-visible:outline-focus';

/**
 * The right column of the desktop contact sheet: the open photo big, who took it, when,
 * with which settings, and every action on it. `?photo=<id>` opens it.
 */
const NONE: ReadonlyArray<AdminPhoto> = [];

/** How many of the ticked photos show as small frames. */
const SELECTION_PREVIEW = 12;

function SelectionSummary({ photos }: { photos: ReadonlyArray<AdminPhoto> }) {
  const shown = photos.slice(0, SELECTION_PREVIEW);
  const rest = photos.length - shown.length;
  return (
    <aside
      aria-label="Auswahl"
      className="grid content-start gap-4 px-5 py-4"
      data-testid="inspector"
      data-selection={photos.length}
    >
      <h2 className="flex items-center gap-2 text-lg font-bold tabular">
        <SquareCheck aria-hidden="true" className="size-5" strokeWidth={2} />
        {photoCount(photos.length)} ausgewählt
      </h2>
      <ul className="grid grid-cols-4 gap-1.5" aria-label="Ausgewählte Fotos">
        {shown.map((p) => (
          <li key={p.id} className="relative aspect-[3/4] overflow-hidden bg-surface-sunk">
            <img
              src={p.thumb_url}
              alt={photoLabel(p)}
              className={cx('size-full object-cover', p.hidden && 'opacity-45 grayscale-[0.6]')}
            />
          </li>
        ))}
        {rest > 0 ? (
          <li className="grid aspect-[3/4] place-items-center bg-surface-sunk text-sm font-semibold text-ink-muted tabular">
            +{rest}
          </li>
        ) : null}
      </ul>
      <p className="text-sm text-ink-muted">
        Ausblenden, Einblenden und Löschen gelten für alle ausgewählten Fotos: unten in der Leiste. Ein Klick
        auf ein Foto nimmt es dazu oder heraus, Esc hebt die Auswahl auf.
      </p>
    </aside>
  );
}

export function PhotoInspector({
  photo,
  selection = NONE,
  gone = false,
  extension,
  onClose,
  onToggleHidden,
  onDelete,
  onCopyHandle,
  busy,
}: PhotoInspectorProps) {
  const [showBoxes, setShowBoxes] = useState(true);
  if (selection.length > 0) return <SelectionSummary photos={selection} />;
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
      aria-label={photoName(photo)}
      className="grid content-start gap-4 px-5 py-4"
      data-testid="inspector"
    >
      <div className="relative aspect-[3/4] overflow-hidden bg-surface-sunk">
        <FittedPhoto width={photo.width} height={photo.height}>
          <InspectorImage photo={photo} label={label} />
          {photo.hidden ? (
            <GreaseX className="pointer-events-none absolute inset-[8%] size-[84%] text-mark" />
          ) : null}
          <AnalysisBoxes photo={photo} visible={showBoxes} />
        </FittedPhoto>
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
            {guestName(photo.user)}
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
      {hasFilterChoice(photo) ? <FilterToggle photo={photo} /> : null}
      <AnalysisPanel photo={photo} showBoxes={showBoxes} onShowBoxesChange={setShowBoxes} />
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
          href={downloadHref(photo)}
          download={downloadName(photo)}
          data-testid="download"
        >
          {hasOriginal(photo) ? 'Herunterladen (mit Filter)' : t.download}
        </LinkButton>
        {hasOriginal(photo) ? (
          <LinkButton
            size="sm"
            variant="secondary"
            icon={Download}
            href={downloadHref(photo, true)}
            download={downloadName(photo, true)}
            data-testid="download-original"
          >
            Original ohne Filter
          </LinkButton>
        ) : null}
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
