/**
 * „Als Gast teilnehmen“: the admin signs this browser in to the guest app as the party's
 * admin guest (POST /api/admin/guest; created on the first press, the same one after
 * that: then the button says „Als Gast öffnen“) and opens the guest app in a new tab, so
 * the admin panel stays open. The cookies are shared (same origin): no QR code, no token.
 * Another guest identity this browser had is replaced; a toast says so.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { PartyPopper } from 'lucide-react';
import { useId, useState } from 'react';
import { api, isApiError } from '@/api/client';
import { Button } from '@/ui/Button';
import { cx } from '@/ui/cx';
import { showToast } from '@/ui/Toast';
import { call } from '../store/api';
import { fetchHostGuest, hostGuestHint, hostGuestKey, hostGuestLabel, type HostGuestState } from './api';

interface HostGuestButtonProps {
  /** show the explanation under the button (the Gäste section; the sidebar is too narrow) */
  hint?: boolean;
  size?: 'xs' | 'sm';
  variant?: 'quiet' | 'secondary';
  className?: string;
}

export function HostGuestButton({
  hint = false,
  size = 'xs',
  variant = 'quiet',
  className,
}: HostGuestButtonProps) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: hostGuestKey, queryFn: fetchHostGuest });
  const [pending, setPending] = useState(false);
  const hintId = useId();

  const join = async () => {
    // the tab opens inside the click (popup blockers allow only that) and gets its
    // address once the guest cookie is set
    const tab = window.open('', '_blank');
    setPending(true);
    try {
      const res = await call(api.POST('/api/admin/guest'));
      qc.setQueryData<HostGuestState>(hostGuestKey, {
        user: res.user,
        browser_is_host: true,
        browser_guest: null,
      });
      if (tab) {
        tab.opener = null;
        tab.location.href = res.url;
      } else {
        window.location.assign(res.url);
      }
      if (res.replaced) {
        showToast({
          message: `Dieser Browser war als Gast „${res.replaced}“ angemeldet. Jetzt bist du hier der Admin-Gast.`,
        });
      } else if (res.created) {
        showToast({ message: 'Admin-Gast angelegt. Die Gäste-App ist im neuen Tab offen.', tone: 'success' });
      }
    } catch (err) {
      tab?.close();
      showToast({
        message: isApiError(err) ? err.message : 'Das hat nicht geklappt. Versuch es noch mal.',
        tone: 'error',
      });
    } finally {
      setPending(false);
    }
  };

  const button = (
    <Button
      variant={variant}
      size={size}
      icon={PartyPopper}
      isPending={pending}
      pendingLabel="Meldet an…"
      onPress={() => void join()}
      aria-describedby={hint ? hintId : undefined}
      data-testid="host-guest-button"
      data-state={data?.user ? 'exists' : 'new'}
      className={hint ? undefined : className}
    >
      {hostGuestLabel(data)}
    </Button>
  );
  if (!hint) return button;
  return (
    <div className={cx('grid max-w-prose justify-items-start gap-1', className)}>
      {button}
      <p id={hintId} className="text-xs text-ink-muted" data-testid="host-guest-hint">
        {hostGuestHint(data)}
      </p>
    </div>
  );
}
