/**
 * A code as the print library (`@/print`) needs it, and the text of a failed export.
 * Used by the code sheet's downloads and the poster's test print.
 */
import { isApiError } from '@/api/errors';
import type { CodePrintInput } from '@/print/types';
import type { Activities, AdminCode } from './api';
import { codeUrl } from './codeUrl';

/** The URL (public base URL, else this page's origin), number, name, event name, activity. */
export function printInput(
  code: AdminCode,
  baseUrl: string | null,
  activities: Activities,
  eventName: string,
): CodePrintInput {
  return {
    url: codeUrl(baseUrl, code.entry_path, window.location.origin),
    number: code.id,
    name: code.name,
    eventName,
    subtitle: code.target ? (activities.byId.get(code.target)?.title ?? null) : null,
  };
}

/** The server's or the print library's message, else a generic one. */
export function exportErrorText(err: unknown): string {
  const known = isApiError(err) || (err instanceof Error && err.name === 'PrintError');
  return known && err instanceof Error ? err.message : 'Die Datei ließ sich nicht erstellen.';
}
