/**
 * Image preloader for long-running TV pages: images are decoded before they are shown,
 * at most `max` wait in the cache, and every image leaves with `src = ''` so the
 * browser can drop its decoded pixels.
 */
export interface Preloader {
  /** Start loading `url` in the background (kept in the cache). */
  warm(url: string): void;
  /** The decoded image for `url`; it leaves the cache and belongs to the caller now. */
  take(url: string): Promise<HTMLImageElement>;
  /** Free an image the caller no longer shows. */
  release(img: HTMLImageElement | null | undefined): void;
  clear(): void;
}

const DECODE_TIMEOUT_MS = 15_000;

function load(url: string): { img: HTMLImageElement; ready: Promise<HTMLImageElement> } {
  const img = new Image();
  img.decoding = 'async';
  img.draggable = false;
  img.src = url;
  const timeout = new Promise<never>((_, reject) =>
    setTimeout(() => reject(new Error('decode timeout')), DECODE_TIMEOUT_MS),
  );
  const ready = Promise.race([img.decode().then(() => img), timeout]);
  ready.catch(() => undefined); // a warmed image nobody takes must not log an unhandled rejection
  return { img, ready };
}

export function releaseImage(img: HTMLImageElement | null | undefined): void {
  if (!img) return;
  img.src = '';
  img.removeAttribute('src');
}

export function createPreloader(max = 3): Preloader {
  const cache = new Map<string, { img: HTMLImageElement; ready: Promise<HTMLImageElement> }>();

  function trim(): void {
    while (cache.size > max) {
      const [url, entry] = cache.entries().next().value!;
      cache.delete(url);
      releaseImage(entry.img);
    }
  }

  return {
    warm(url) {
      if (cache.has(url)) return;
      cache.set(url, load(url));
      trim();
    },
    take(url) {
      const entry = cache.get(url) ?? load(url);
      cache.delete(url);
      return entry.ready.catch((err: unknown) => {
        releaseImage(entry.img);
        throw err;
      });
    },
    release: releaseImage,
    clear() {
      for (const entry of cache.values()) releaseImage(entry.img);
      cache.clear();
    },
  };
}
