/**
 * Admin navigation outside React: the login redirect with `?next=` and its validation.
 */

const FALLBACK = '/admin/live';

/**
 * Only same-site admin pages, never an open redirect (web-serving.md §3): a lower-case
 * page name under /admin/ and an optional query of harmless characters. The login
 * page itself and the bare /admin/ fall back to the live screen.
 */
const NEXT_RE = /^\/admin\/[a-z][a-z0-9-]{0,30}(\?[A-Za-z0-9_=&%.,+-]{0,300})?$/;

export function safeNext(raw: string | null | undefined): string {
  if (!raw || !NEXT_RE.test(raw)) return FALLBACK;
  if (raw === '/admin/login' || raw.startsWith('/admin/login?')) return FALLBACK;
  return raw;
}

/** /admin/login?next=<this page, with its query> */
export function loginUrl(here: { pathname: string; search: string } = location): string {
  const next = here.pathname + here.search;
  return next.startsWith('/admin/') && !next.startsWith('/admin/login')
    ? `/admin/login?next=${encodeURIComponent(next)}`
    : '/admin/login';
}

let leaving = false;

/** The session is gone: off to the login page, once (every failing request calls this). */
export function goLogin(): void {
  if (leaving) return;
  leaving = true;
  location.assign(loginUrl());
}

/** A promise that never settles: the page is leaving, nobody should show an error. */
export function never<T>(): Promise<T> {
  return new Promise<T>(() => undefined);
}
