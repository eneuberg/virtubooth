/**
 * The corner overlay: event name and photo counter. `overlay.qr` renders nothing yet
 * (WINT adds the QR code).
 */
import { formatCount } from '@/lib/format';
import type { WallConfig } from '../api/types';

export function Corner({
  overlay,
  eventName,
  total,
}: {
  overlay: WallConfig['overlay'];
  eventName: string;
  total: number;
}) {
  const name = overlay.event_name && eventName ? eventName : null;
  if (!name && !overlay.counter) return null;
  return (
    <div className="wall-corner" data-corner={overlay.corner} data-testid="wall-corner">
      {name ? <span className="wall-corner-name">{name}</span> : null}
      {overlay.counter ? (
        <span className="wall-corner-count">
          <span className="wall-corner-num">{formatCount(total)}</span> {total === 1 ? 'Foto' : 'Fotos'}
        </span>
      ) : null}
    </div>
  );
}
