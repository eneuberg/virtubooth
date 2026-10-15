/**
 * The public address's copy without React (address.test.ts): the status line under the
 * field and the QR-Codes tab's warning.
 */
import { formatTime } from '@/lib/format';
import type { AddressCheck } from './api';

export type AddressTone = 'ok' | 'warn' | 'muted';

/** The QR-Codes tab's banner while the address is unchecked or broken. */
export const QR_ADDRESS_WARNING =
  'Die öffentliche Adresse ist nicht geprüft oder nicht erreichbar. Prüfe sie unter „Allgemeines“, bevor du druckst.';

export const ADDRESS_HINT = 'Leer lassen = automatisch aus dem Aufruf';

function checkedAt(check: AddressCheck): string {
  return check.at ? ` – geprüft ${formatTime(new Date(check.at))}` : '';
}

/**
 * „Erreichbar ✓ – geprüft 21:14“, „Nicht erreichbar – QR-Codes würden ins Leere
 * führen.“, „Antwortet, ist aber nicht diese Fotobox.“; `detail` is the server's reason.
 */
export function addressStatus(check: AddressCheck): {
  text: string;
  detail: string | null;
  tone: AddressTone;
} {
  switch (check.status) {
    case 'ok':
      return { text: `Erreichbar ✓${checkedAt(check)}`, detail: null, tone: 'ok' };
    case 'unreachable':
      return {
        text: 'Nicht erreichbar – QR-Codes würden ins Leere führen.',
        detail: `${check.message}${checkedAt(check)}`,
        tone: 'warn',
      };
    case 'mismatch':
      return {
        text: 'Antwortet, ist aber nicht diese Fotobox.',
        detail: `${check.message}${checkedAt(check)}`,
        tone: 'warn',
      };
    case 'auto':
      return {
        text: 'Automatisch: Die QR-Codes nehmen die Adresse, unter der die Verwaltung gerade offen ist.',
        detail: null,
        tone: 'muted',
      };
    default:
      return { text: 'Noch nicht geprüft.', detail: null, tone: 'warn' };
  }
}
