/**
 * The code sheet's downloads (active codes only): „QR als PNG“, „QR groß (PDF)“,
 * „Plakat (PDF)“. The print library loads on the first click (its own chunks); the
 * poster uses the template from the tab „Plakat“ when one is saved, else the
 * standard poster. The event name is the one from Einstellungen.
 */
import { useQueryClient } from '@tanstack/react-query';
import { FileImage, FileText, Printer } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-aria-components';
import { Button } from '@/ui/Button';
import { showToast } from '@/ui/Toast';
import { loadPosterTemplate } from '../poster/template';
import { fetchSettings } from '../settings/api';
import { settingsKey } from '../settings/keys';
import type { Activities, AdminCode } from './api';
import { exportErrorText, printInput } from './printInput';

type Kind = 'png' | 'qr-pdf' | 'poster';

const LINK =
  'font-semibold text-ink underline decoration-line-strong underline-offset-3 outline-none hover:decoration-ink focus-visible:outline-2 focus-visible:outline-focus';

export function CodeExports({
  code,
  baseUrl,
  activities,
}: {
  code: AdminCode;
  baseUrl: string | null;
  activities: Activities;
}) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState<Kind | null>(null);

  const run = async (kind: Kind) => {
    setBusy(kind);
    try {
      const [print, settings] = await Promise.all([
        import('@/print'),
        qc.fetchQuery({ queryKey: settingsKey, queryFn: fetchSettings, staleTime: 30_000 }),
      ]);
      const input = printInput(code, baseUrl, activities, settings.event.name);
      const data =
        kind === 'png'
          ? await print.qrPng(input)
          : kind === 'qr-pdf'
            ? await print.bigQrPdf(input)
            : await print.posterPdf(input, await loadPosterTemplate());
      print.downloadBlob(data, print.exportFileName(input, kind));
    } catch (err) {
      showToast({ message: `Export ging nicht: ${exportErrorText(err)}`, tone: 'error' });
    } finally {
      setBusy(null);
    }
  };

  const button = (kind: Kind, label: string, icon: typeof Printer, testid: string) => (
    <Button
      size="sm"
      icon={icon}
      isPending={busy === kind}
      isDisabled={busy !== null && busy !== kind}
      pendingLabel="Wird erstellt…"
      onPress={() => void run(kind)}
      data-testid={testid}
    >
      {label}
    </Button>
  );

  return (
    <section aria-labelledby="code-exports" className="grid gap-2" data-testid="code-exports">
      <h3 id="code-exports" className="text-sm text-ink-muted">
        Drucken
      </h3>
      <div className="flex flex-wrap gap-2">
        {button('png', 'QR als PNG', FileImage, 'code-export-png')}
        {button('qr-pdf', 'QR groß (PDF)', FileText, 'code-export-qr-pdf')}
        {button('poster', 'Plakat (PDF)', Printer, 'code-export-poster')}
      </div>
      <p className="text-sm text-ink-muted">
        Mit Vorlage aus dem Tab{' '}
        <Link href="/manage?tab=plakat" className={LINK}>
          „Plakat“
        </Link>
        , sonst das Standard-Plakat.
      </p>
    </section>
  );
}
