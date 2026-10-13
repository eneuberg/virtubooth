/**
 * Instagram, WhatsApp, Facebook & co. open links in their own browser, which often
 * gets no camera. "Open in browser" from their menu would not help either: the page
 * there has no party access yet (the QR code's token is gone from the address).
 * So the advice is: scan the QR code with the phone's camera app.
 * Shown on Start; "Verstanden" hides it for this tab. Test id `inapp-hint`.
 */
import { Smartphone } from 'lucide-react';
import { useState } from 'react';
import { inAppBrowserName } from '@/sdk/platform';
import { Button } from '@/ui/Button';
import { cx } from '@/ui/cx';
import { inAppAdvice } from './copy';

const SEEN_KEY = 'vb_inapp_seen';

function seen(): boolean {
  try {
    return sessionStorage.getItem(SEEN_KEY) === '1';
  } catch {
    return false;
  }
}

export function InAppHint({ className }: { className?: string }) {
  const app = inAppBrowserName();
  const [hidden, setHidden] = useState(seen);
  if (!app || hidden) return null;
  const { title, text } = inAppAdvice(app);
  return (
    <aside
      data-testid="inapp-hint"
      aria-label={title}
      className={cx('grid gap-3 rounded-control border border-accent bg-accent-tint p-4', className)}
    >
      <p className="flex items-start gap-3">
        <Smartphone aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-accent-ink" strokeWidth={2} />
        <span className="grid gap-1">
          <strong className="font-semibold">{title}</strong>
          <span className="text-ink-muted">{text}</span>
        </span>
      </p>
      <Button
        variant="secondary"
        size="sm"
        className="justify-self-end"
        onPress={() => {
          try {
            sessionStorage.setItem(SEEN_KEY, '1');
          } catch {
            // hidden for this page view only
          }
          setHidden(true);
        }}
      >
        Verstanden
      </Button>
    </aside>
  );
}
