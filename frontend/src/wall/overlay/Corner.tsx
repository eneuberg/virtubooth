/**
 * The corner overlay: the QR code (`overlay.qr` and an active code: `qr`), event name
 * and photo counter. Its size goes to `--wall-corner-w` / `--wall-corner-h` on `.wall`, so
 * the modes can keep their content clear of it (wall.css, categories).
 */

/** Publishes the element's size on the closest `.wall` while it is mounted. */
function usePublishedSize(ref: RefObject<HTMLElement | null>): void {
  useLayoutEffect(() => {
    const el = ref.current;
    const wall = el?.closest<HTMLElement>('.wall');
    if (!el || !wall) return undefined;
    const publish = (): void => {
      wall.style.setProperty('--wall-corner-w', `${Math.ceil(el.offsetWidth)}px`);
      wall.style.setProperty('--wall-corner-h', `${Math.ceil(el.offsetHeight)}px`);
    };
    publish();
    // next frame: style changes inside the callback make WebKit report a ResizeObserver loop
    let frame = 0;
    const later = (): void => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(publish);
    };
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(later) : null;
    observer?.observe(el);
    return () => {
      cancelAnimationFrame(frame);
      observer?.disconnect();
      wall.style.removeProperty('--wall-corner-w');
      wall.style.removeProperty('--wall-corner-h');
    };
  }, [ref]);
}
import { useLayoutEffect, useRef, type RefObject } from 'react';
import { formatCount } from '@/lib/format';
import { GooglyEyes } from '@/ui/goofy/GooglyEyes';
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
    <CornerBox corner={overlay.corner} name={name} counter={overlay.counter} total={total} code={code} />
  );
}

function CornerBox({
  corner,
  name,
  counter,
  total,
  code,
}: {
  corner: WallConfig['overlay']['corner'];
  name: string | null;
  counter: boolean;
  total: number;
  code: WallQr | null;
}) {
  const ref = useRef<HTMLDivElement>(null);
  usePublishedSize(ref);
  return (
    <div ref={ref} className="wall-corner" data-corner={corner} data-testid="wall-corner">
      {/* goofy style: the peeker from Start looks over the box and around the room */}
      <GooglyEyes gaze="room" className="wall-peeker" />
      {code ? <QrCode url={code.url} name={code.name} /> : null}
      {name ? <span className="wall-corner-name">{name}</span> : null}
      {counter ? (
        <span className="wall-corner-count">
          <span className="wall-corner-num">{formatCount(total)}</span> {total === 1 ? 'Foto' : 'Fotos'}
        </span>
      ) : null}
    </div>
  );
}
