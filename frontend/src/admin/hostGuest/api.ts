/**
 * The admin guest's state (GET /api/admin/guest) and the button's texts.
 */
import { api } from '@/api/client';
import type { components } from '@/api/schema.gen';
import { call } from '../store/api';

export type HostGuestState = components['schemas']['HostGuestState'];

export const hostGuestKey = ['admin', 'host-guest'] as const;

export function fetchHostGuest(): Promise<HostGuestState> {
  return call(api.GET('/api/admin/guest'));
}

export function hostGuestLabel(state: HostGuestState | undefined): string {
  return state?.user ? 'Als Gast öffnen' : 'Als Gast teilnehmen';
}

/** What happens, said before the press: shown under the button where there is room. */
export function hostGuestHint(state: HostGuestState | undefined): string {
  const lines = [
    'Öffnet die Gäste-App in einem neuen Tab: du bist dort ein normaler Gast namens „Gastgeber“, ' +
      'für die anderen Gäste ohne Admin-Kennzeichen. Kein Foto-Limit, keine Pause für neue Gäste; ' +
      '„Hochladen stoppen“ gilt aber auch für dich.',
  ];
  if (state?.browser_guest) {
    lines.push(
      `Dieser Browser ist gerade als Gast „${state.browser_guest}“ angemeldet: der wird hier durch den ` +
        'Admin-Gast ersetzt.',
    );
  }
  return lines.join(' ');
}
