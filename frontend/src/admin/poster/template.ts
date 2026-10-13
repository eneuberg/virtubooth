/**
 * The saved template for the exports (the integrator wires it into the QR table):
 *
 *   const template = await loadPosterTemplate(); // null: the standard poster
 *   const pdf = await (await import('@/print')).posterPdf(code, template);
 *
 * The PDF's bytes are cached per SHA-256 (the editor shares the cache).
 */
import type { PosterTemplateInput } from '@/print/types';
import { fetchPoster, fetchTemplateBytes } from './api';

const cache = new Map<string, Promise<ArrayBuffer>>();

/** The template's bytes for this SHA-256 (fetched once; only the newest is kept). */
export function templateBytes(sha256: string): Promise<ArrayBuffer> {
  let bytes = cache.get(sha256);
  if (!bytes) {
    cache.clear();
    bytes = fetchTemplateBytes();
    cache.set(sha256, bytes);
    bytes.catch(() => cache.delete(sha256));
  }
  return bytes;
}

/** The template with its saved QR field, or null (no template, or no field saved yet). */
export async function loadPosterTemplate(): Promise<PosterTemplateInput | null> {
  const { template } = await fetchPoster();
  if (!template || template.rect === null || template.page === null) return null;
  return { pdf: await templateBytes(template.sha256), page: template.page, rect: template.rect };
}
