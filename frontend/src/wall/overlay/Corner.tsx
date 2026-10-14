/**
 * The corner overlay: the QR code (`overlay.qr` and an active code: `qr`), event name
 * and photo counter.
 */
import { formatCount } from '@/lib/format';
import type { WallConfig, WallQr } from '../api/types';
import { QrCode } from './QrCode';

export function Corner({
  overlay,
  eventName,
  total,
  qr = null,
}: {
  overlay: WallConfig['overlay'];
  eventName: string;
  total: number;
  qr?: WallQr | null;
}) {
  const name = overlay.event_name && eventName ? eventName : null;
  const code = overlay.qr ? qr : null;
  if (!name && !overlay.counter && !code) return null;
  return (
    <div className="wall-corner" data-corner={overlay.corner} data-testid="wall-corner">
      {code ? <QrCode url={code.url} name={code.name} /> : null}
      {name ? <span className="wall-corner-name">{name}</span> : null}
      {overlay.counter ? (
        <span className="wall-corner-count">
          <span className="wall-corner-num">{formatCount(total)}</span> {total === 1 ? 'Foto' : 'Fotos'}
        </span>
      ) : null}
    </div>
  );
}
