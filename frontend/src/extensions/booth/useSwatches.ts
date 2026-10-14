/**
 * Filter swatches made from the guest's own picture: once the camera runs, the frame
 * on screen goes through every filter at thumbnail size (one shader pass each), one
 * after the other so the preview keeps running; each swatch appears when it is ready.
 * They stay (object URLs) until the page goes. The map holds an object URL per filter
 * once its swatch is there, or null when it failed (the strip shows the catalogue icon
 * then); until then the strip shows a neutral placeholder.
 */
import { useEffect, useRef, useState } from 'react';
import type { Filter } from '@/sdk/camera/filters';
import { drawOverlay, type OverlayInfo } from '@/sdk/camera/overlays';
import { canvasToJpeg } from '@/sdk/camera/renderer';
import type { CameraSession } from '@/sdk/camera/session';

const W = 150;
const H = 200;
/** let the exposure settle before taking the sample frame */
const SETTLE_MS = 700;

export function useSwatches(
  session: CameraSession | null,
  filters: ReadonlyArray<Filter>,
  info: OverlayInfo | null,
  live: boolean,
): ReadonlyMap<string, string | null> {
  const [urls, setUrls] = useState<ReadonlyMap<string, string | null>>(() => new Map());
  const made = useRef<string[]>([]);
  const ready = live && !!session && !!info && filters.length > 0;

  useEffect(() => {
    if (!ready || !session || !info) return undefined;
    let cancelled = false;
    const timer = setTimeout(() => {
      void (async () => {
        const overlayCanvas = document.createElement('canvas');
        overlayCanvas.width = W;
        overlayCanvas.height = H;
        for (const filter of filters) {
          if (cancelled) return;
          try {
            const overlay = drawOverlay(overlayCanvas, filter.id, info);
            const canvas = session.snapshotWith(filter, overlay, W, H);
            // oxlint-disable-next-line no-await-in-loop -- one swatch after the other on purpose
            const blob = await canvasToJpeg(canvas, 0.82);
            const url = URL.createObjectURL(blob);
            made.current.push(url);
            if (!cancelled) setUrls((current) => new Map(current).set(filter.id, url));
          } catch {
            // this filter shows its icon
            if (!cancelled) setUrls((current) => new Map(current).set(filter.id, null));
          }
          // yield to the render loop between swatches
          // oxlint-disable-next-line no-await-in-loop -- on purpose
          await new Promise((resolve) => setTimeout(resolve, 16));
        }
      })();
    }, SETTLE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [ready, session, info, filters]);

  // the swatches die with the page
  useEffect(
    () => () => {
      for (const url of made.current) URL.revokeObjectURL(url);
      made.current = [];
    },
    [],
  );
  return urls;
}
