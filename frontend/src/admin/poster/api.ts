/** The poster template API (`/api/admin/poster`, see backend services/posters.py). */
import { api } from '@/api/client';
import { unreachable } from '@/api/errors';
import type { PosterLayoutIn, PosterOut, PosterTemplate } from '@/api/types';
import { msg } from '@/lib/messages.de';
import { call } from '../store/api';

export type { PosterLayoutIn, PosterOut, PosterTemplate };

export function fetchPoster(): Promise<PosterOut> {
  return call(api.GET('/api/admin/poster'));
}

/** The template's bytes (409 `no_template` without one). */
export function fetchTemplateBytes(): Promise<ArrayBuffer> {
  return call(api.GET('/api/admin/poster/template', { parseAs: 'arrayBuffer' }));
}

export function saveLayout(body: PosterLayoutIn): Promise<PosterOut> {
  return call(api.PUT('/api/admin/poster/layout', { body }));
}

export function deleteTemplate(): Promise<PosterOut> {
  return call(api.DELETE('/api/admin/poster/template'));
}

/**
 * Upload a new template: the raw PDF as the body (the browser sets Content-Length).
 * Errors become ApiErrors with the server's German message, like every other call.
 */
export async function uploadTemplate(file: Blob): Promise<PosterOut> {
  let response: Response;
  try {
    response = await fetch('/api/admin/poster/template', {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/pdf', Accept: 'application/json' },
      body: file,
    });
  } catch {
    throw unreachable(msg.offline, msg.noAnswer);
  }
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // a proxy's HTML error page: the status decides
  }
  if (response.ok) {
    // oxlint-disable-next-line typescript/no-unsafe-type-assertion -- the server's PosterOut
    return call(Promise.resolve({ data: body as PosterOut, response }));
  }
  return call(Promise.resolve({ data: undefined, error: body, response }));
}
