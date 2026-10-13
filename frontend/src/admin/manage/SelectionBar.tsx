import { Eye, EyeOff, Trash2, X } from 'lucide-react';
import { t } from '@/lib/messages.de';
import { Button } from '@/ui/Button';
import { formatNumber } from '@/lib/format';

/**
 * The sticky bar while photos are selected: bulk Ausblenden / Einblenden / Löschen….
 * One row on a phone too (labels shrink to icons; they stay in the accessible name).
 */
export function SelectionBar({
  count,
  busy,
  onHide,
  onUnhide,
  onDelete,
  onClear,
}: {
  count: number;
  busy: 'hide' | 'unhide' | null;
  onHide: () => void;
  onUnhide: () => void;
  onDelete: () => void;
  onClear: () => void;
}) {
  if (count === 0) return null;
  return (
    <div
      role="toolbar"
      aria-label="Auswahl"
      data-testid="bulkbar"
      data-surface="dark"
      className="fixed inset-x-0 bottom-[calc(4rem+env(safe-area-inset-bottom))] z-(--z-bar) flex items-center gap-2 bg-negativ px-3 py-2 text-leuchttisch lg:bottom-0 lg:left-62 lg:px-6 lg:py-3"
    >
      <strong data-testid="bulk-count" className="mr-1 shrink-0 text-sm tabular">
        {formatNumber(count)} ausgewählt
      </strong>
      <Button
        size="xs"
        variant="secondary"
        icon={EyeOff}
        isPending={busy === 'hide'}
        onPress={onHide}
        data-testid="bulk-hide"
      >
        <span className="max-sm:sr-only">{t.hide}</span>
      </Button>
      <Button
        size="xs"
        variant="secondary"
        icon={Eye}
        isPending={busy === 'unhide'}
        onPress={onUnhide}
        data-testid="bulk-unhide"
      >
        <span className="max-sm:sr-only">{t.unhide}</span>
      </Button>
      <Button size="xs" variant="danger-outline" icon={Trash2} onPress={onDelete} data-testid="bulk-delete">
        <span className="max-sm:sr-only">{t.deleteEllipsis}</span>
      </Button>
      <Button
        size="xs"
        variant="quiet"
        icon={X}
        onPress={onClear}
        data-testid="bulk-clear"
        className="ml-auto"
      >
        <span className="max-sm:sr-only">Auswahl aufheben</span>
      </Button>
    </div>
  );
}
