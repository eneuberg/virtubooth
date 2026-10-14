/**
 * Building a code's downloads (QR als PNG, QR groß (PDF), Plakat (PDF)): the code
 * sheet's buttons (CodeExports) and the table's row menu (CodeRowMenu). The print
 * library loads on the first use (its own chunks).
 */
import { useQueryClient } from '@tanstack/react-query';
import { FileImage, FileText, Printer } from 'lucide-react';
import { useState } from 'react';
import { showToast } from '@/ui/Toast';
import { loadPosterTemplate } from '../poster/template';
import { fetchSettings } from '../settings/api';
import { settingsKey } from '../settings/keys';
import type { Activities, AdminCode } from './api';
import { exportErrorText, printInput } from './printInput';

export type ExportKind = 'png' | 'qr-pdf' | 'poster';
/** The three downloads, in the order both places show them. */
export const EXPORTS: ReadonlyArray<{ kind: ExportKind; label: string; icon: typeof Printer }> = [
  { kind: 'png', label: 'QR als PNG', icon: FileImage },
  { kind: 'qr-pdf', label: 'QR groß (PDF)', icon: FileText },
  { kind: 'poster', label: 'Plakat (PDF)', icon: Printer },
];

/** Builds and saves one download of a code; `busy` is the one being made. */
export function useCodeExport(baseUrl: string | null, activities: Activities) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState<ExportKind | null>(null);
  const run = async (code: AdminCode, kind: ExportKind) => {
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
  return { busy, run };
}
