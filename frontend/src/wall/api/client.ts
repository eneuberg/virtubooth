/**
 * Fetch helpers for the screen API under /livewall/api (PLAN-WALL §4.2). Errors are
 * `{error, message}` JSON; every failure becomes a WallApiError (status 0 = no answer).
 */
import type { WallCategory, WallFeed, WallSession } from './types';

export const API = '/livewall/api';

export class WallApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = 'WallApiError';
    this.status = status;
    this.code = code;
  }
}

const NO_ANSWER = 'Keine Antwort vom Server.';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

async function errorFrom(res: Response): Promise<WallApiError> {
  let code = 'http_' + String(res.status);
  let message = `Fehler ${res.status}.`;
  try {
    const body: unknown = await res.json();
    if (isRecord(body)) {
      if (typeof body['error'] === 'string') code = body['error'];
      if (typeof body['message'] === 'string') message = body['message'];
    }
  } catch {
    // not JSON (a proxy page): keep the generic message
  }
  return new WallApiError(res.status, code, message);
}

export async function wallFetch<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = init;
  const headers = new Headers(rest.headers);
  headers.set('Accept', 'application/json');
  if (json !== undefined) headers.set('Content-Type', 'application/json');
  let res: Response;
  try {
    res = await globalThis.fetch(API + path, {
      credentials: 'same-origin',
      cache: 'no-store',
      ...rest,
      headers,
      body: json !== undefined ? JSON.stringify(json) : (rest.body ?? null),
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    throw new WallApiError(0, 'unreachable', NO_ANSWER);
  }
  if (!res.ok) throw await errorFrom(res);
  const text = await res.text();
  // oxlint-disable-next-line typescript/no-unsafe-type-assertion -- the contract types the body
  return (text ? JSON.parse(text) : null) as T;
}

/** GET /session: the HTTP status only (200 ok, 401 login, 409 no password, 0 no answer). */
export async function sessionStatus(): Promise<number> {
  try {
    await wallFetch<WallSession>('/session');
    return 200;
  } catch (err) {
    if (err instanceof WallApiError) return err.status;
    throw err;
  }
}

export function login(password: string): Promise<WallSession> {
  return wallFetch<WallSession>('/session', { method: 'POST', json: { password } });
}

export function fetchFeed(limit = 1000): Promise<WallFeed> {
  return wallFetch<WallFeed>(`/feed?limit=${limit}`);
}

export async function fetchCategories(): Promise<WallCategory[]> {
  const body = await wallFetch<{ categories: WallCategory[] }>('/categories');
  return body.categories;
}
