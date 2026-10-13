/**
 * The typed API client. Paths and request bodies come from openapi.json
 * (`pnpm gen:api` → schema.gen.ts); every failure becomes an ApiError with a German
 * message (errors.ts).
 *
 *   const data = await unwrap(api.GET('/api/admin/stats'));
 *
 * TODO(wave 2): the provisional schema has untyped responses (`unknown`); until it is
 * regenerated, narrow with the types in types.ts, or use apiFetch<T>().
 */
import createClient from 'openapi-fetch';
import { msg } from '@/lib/messages.de';
import { ApiError, errorFromResponse, isApiError, unreachable } from './errors';
import type { paths } from './schema.gen';

export { ApiError, isApiError };
export type { ApiErrorCode, ErrorCode } from './errors';

function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === 'AbortError';
}

/** fetch that turns "no answer" (offline, or dropped by a blocker) into an ApiError. */
async function fetchOrUnreachable(input: Request): Promise<Response> {
  try {
    // looked up per call so tests (and wave-2 code) can stub globalThis.fetch
    return await globalThis.fetch(input);
  } catch (err) {
    if (isAbort(err)) throw err;
    throw unreachable(msg.offline, msg.noAnswer);
  }
}

export const api = createClient<paths>({
  baseUrl: '',
  credentials: 'same-origin',
  headers: { Accept: 'application/json' },
  fetch: fetchOrUnreachable,
});

type ClientResult = { data?: unknown; error?: unknown; response: Response };

/** The data of an openapi-fetch call, or an ApiError for any non-2xx answer. */
export async function unwrap<R extends ClientResult>(
  result: Promise<R> | R,
): Promise<Exclude<R['data'], undefined>> {
  const { data, error, response } = await result;
  if (!response.ok) {
    throw errorFromResponse(response.status, error, response.headers.get('Retry-After'), msg.generic);
  }
  // oxlint-disable-next-line typescript/no-unsafe-type-assertion -- openapi-fetch: data is set when ok
  return data as Exclude<R['data'], undefined>;
}

export interface ApiFetchInit extends Omit<RequestInit, 'body'> {
  /** Serialised as JSON with the matching Content-Type. */
  json?: unknown;
  body?: BodyInit | null;
}

/**
 * Escape hatch for routes the schema does not describe yet (same error mapping as
 * the client). Returns the parsed JSON body, or null for an empty answer.
 */
export async function apiFetch<T>(path: string, init: ApiFetchInit = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const finalHeaders = new Headers(headers);
  finalHeaders.set('Accept', 'application/json');
  let body = init.body;
  if (json !== undefined) {
    finalHeaders.set('Content-Type', 'application/json');
    body = JSON.stringify(json);
  }
  const response = await fetchOrUnreachable(
    new Request(new URL(path, location.href), {
      credentials: 'same-origin',
      ...rest,
      headers: finalHeaders,
      body: body ?? null,
    }),
  );
  let data: unknown = null;
  try {
    data = await response.json();
  } catch {
    // empty or non-JSON body
  }
  if (!response.ok) {
    throw errorFromResponse(response.status, data, response.headers.get('Retry-After'), msg.generic);
  }
  // oxlint-disable-next-line typescript/no-unsafe-type-assertion -- trust boundary: the server's JSON
  return data as T;
}
