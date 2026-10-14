/**
 * The code sheet's downloads (active codes only): „QR als PNG“, „QR groß (PDF)“,
 * „Plakat (PDF)“; the table's row menu (CodeRowMenu) offers the same through
 * useCodeExport.ts. The print library loads on the first click (its own chunks); the
 * poster uses the template from the tab „Plakat“ when one is saved, else the
 * standard poster. The event name is the one from Einstellungen.
 */
import { Link } from 'react-aria-components';
import { Button } from '@/ui/Button';
import type { Activities, AdminCode } from './api';
import { EXPORTS, useCodeExport } from './useCodeExport';

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
  const { busy, run } = useCodeExport(baseUrl, activities);

  return (
    <section aria-labelledby="code-exports" className="grid gap-2" data-testid="code-exports">
      <h3 id="code-exports" className="text-sm text-ink-muted">
        Drucken
      </h3>
      <div className="flex flex-wrap gap-2">
        {EXPORTS.map(({ kind, label, icon }) => (
          <Button
            key={kind}
            size="sm"
            icon={icon}
            isPending={busy === kind}
            isDisabled={busy !== null && busy !== kind}
            pendingLabel="Wird erstellt…"
            onPress={() => void run(code, kind)}
            data-testid={`code-export-${kind}`}
          >
            {label}
          </Button>
        ))}
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
