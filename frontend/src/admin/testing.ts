/**
 * Test helpers for the admin (Vitest + Testing Library): a fetch stub that answers by
 * "METHOD /path", and a fresh QueryClient per test.
 */
import { QueryClient } from '@tanstack/react-query';
import { vi } from 'vitest';

export type Route = (request: Request) => unknown;

export function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', 'X-VB-Event-Id': 'abcd1234-1', ...headers },
  });
}

/** Stub fetch; unknown routes answer 404. Returns the requests seen. */
export function stubApi(routes: Record<string, Route>): Request[] {
  const seen: Request[] = [];
  vi.stubGlobal('fetch', async (input: Request) => {
    seen.push(input);
    const key = `${input.method} ${new URL(input.url).pathname}`;
    const route = routes[key];
    if (!route) return json(404, { error: 'http_404', message: 'Not Found' });
    const out = await route(input);
    return out instanceof Response ? out : json(200, out);
  });
  return seen;
}

export function testClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
}

/** A field of a JSON request body (tests read what the app sent). */
export async function bodyField(request: Request, key: string): Promise<unknown> {
  const body: unknown = await request.clone().json();
  return body && typeof body === 'object' ? Object.getOwnPropertyDescriptor(body, key)?.value : undefined;
}

/** The value, or a test failure when it is missing. */
export function must<T>(value: T | null | undefined, what = 'value'): T {
  if (value === null || value === undefined) throw new Error(`missing ${what}`);
  return value;
}
