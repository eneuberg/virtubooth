/**
 * /admin/manage?tab=erscheinungsbild („Erscheinungsbild“, right after Allgemeines): the
 * colours and the style of the guest pages and the Live-Wall (ThemeCard). The admin
 * keeps its own look.
 */
import { Palette } from 'lucide-react';
import { Button } from '@/ui/Button';
import { EmptyState } from '@/ui/EmptyState';
import { Spinner } from '@/ui/Spinner';
import { ThemeCard } from './ThemeCard';
import { useAdminTheme } from './themeApi';

export function LookSection() {
  const theme = useAdminTheme();
  return (
    <section aria-labelledby="section-title" className="grid content-start gap-6 px-4 py-4 lg:px-6 lg:py-5">
      <header className="grid gap-1">
        <h1 id="section-title" tabIndex={-1} className="text-xl font-bold outline-none">
          Erscheinungsbild
        </h1>
        <p className="max-w-prose text-sm text-ink-muted">
          Farben und Stil der Gästeseiten und der Live-Wall. Die Verwaltung behält ihr eigenes Aussehen.
        </p>
      </header>
      {theme.data ? (
        <div className="grid items-start" data-testid="look">
          <ThemeCard data={theme.data} />
        </div>
      ) : theme.isError ? (
        <EmptyState
          icon={Palette}
          title="Das Erscheinungsbild ist gerade nicht erreichbar"
          action={<Button onPress={() => void theme.refetch()}>Erneut laden</Button>}
        >
          {theme.error.message}
        </EmptyState>
      ) : (
        <Spinner />
      )}
    </section>
  );
}
