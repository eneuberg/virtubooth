/**
 * The corner's QR code (drawn by qr.ts) with the code's name under it.
 */
import { useEffect, useRef } from 'react';
import { drawQr, qrTarget } from './qr';

export function QrCode({ url, name }: { url: string; name: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const target = qrTarget(url);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas) drawQr(canvas, target);
  }, [target]);
  return (
    <figure className="wall-qr" data-testid="wall-qr" data-url={target} aria-label={`QR-Code ${name}`}>
      <canvas ref={canvasRef} className="wall-qr-code" aria-hidden="true" />
      <figcaption className="wall-qr-name">{name}</figcaption>
    </figure>
  );
}
