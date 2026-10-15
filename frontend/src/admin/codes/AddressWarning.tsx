/**
 * The QR-Codes tab's warning while the public address is unchecked or does not reach
 * this server: printed codes would lead nowhere. Opening the tab repeats a check older
 * than 10 minutes (once per mount). Automatic addresses need no check.
 */
import { useQueryClient } from '@tanstack/react-query';
import { TriangleAlert } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { Link } from 'react-aria-components';
import { sectionHref } from '../manage/manageUrl';
import { QR_ADDRESS_WARNING } from '../settings/address';
import { addressIsFine, checkIsStale, checkPublicAddress, useSettings } from '../settings/api';

export function AddressWarning() {
  const qc = useQueryClient();
  const settings = useSettings();
  const check = settings.data?.public_address.check;
  const rechecked = useRef(false);

  useEffect(() => {
    if (!check || rechecked.current || !checkIsStale(check)) return;
    rechecked.current = true;
    // a failed request leaves the stored state: the warning stays as it was
    checkPublicAddress(qc).catch(() => undefined);
  }, [check, qc]);

  if (!check || addressIsFine(check)) return null;
  return (
    <div
      role="status"
      data-testid="address-warning"
      data-status={check.status}
      className="flex items-start gap-3 border-l-4 border-accent bg-surface-sunk px-3 py-2.5 text-sm"
    >
      <TriangleAlert aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-accent-ink" strokeWidth={2} />
      <p className="grid gap-1">
        <span className="font-semibold">{QR_ADDRESS_WARNING}</span>
        <Link
          href={sectionHref('allgemein')}
          className="justify-self-start font-semibold text-ink underline underline-offset-2 outline-none focus-visible:outline-2 focus-visible:outline-focus"
        >
          Zu „Allgemeines“
        </Link>
      </p>
    </div>
  );
}
