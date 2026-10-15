/**
 * How the admin marks its own admin guest („Als Gast teilnehmen“, `is_host`) wherever it
 * lists guests or names a photo's guest. Admin only: guests never see the mark.
 */

/** The badge and the suffix after the guest's name. */
export const HOST_MARK = 'Admin-Gast';

/** Where other guests show their QR code. */
export const HOST_CODE = 'über die Verwaltung';

/** „Tanzende Giraffe #5 · Admin-Gast“ for the admin guest, else the plain name. */
export function guestName(user: { name: string; is_host?: boolean }): string {
  return user.is_host ? `${user.name} · ${HOST_MARK}` : user.name;
}
