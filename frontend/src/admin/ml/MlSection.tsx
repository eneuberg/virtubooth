/**
 * /admin/manage?tab=ml: the ML-Pipeline. Every analyzer (Modelle), a test image, the
 * external AI (Claude) with its key, the properties it rates, and the budget. Every
 * card makes its own requests; nothing here is a draft of the wall config.
 */
import { Cpu } from 'lucide-react';
import { Button } from '@/ui/Button';
import { EmptyState } from '@/ui/EmptyState';
import { Spinner } from '@/ui/Spinner';
import { ADMIN_COLUMNS } from '../common/layout';
import { errorText } from '../common/usePhotoActions';
import { isRouteMissing } from '../wall/api';
import { useWallEnabled } from '../wall/hooks';
import { BudgetCard } from './BudgetCard';
import { useLlm } from './hooks';
import { LlmCard } from './LlmCard';
import { ModelsCard } from './ModelsCard';
import { PropertiesCard } from './PropertiesCard';
import { TestImageCard } from './TestImageCard';

/** Claude, Eigenschaften and Budget share GET /llm. */
function ExternalAi() {
  const llm = useLlm();
  if (llm.data) {
    return (
      <>
        <LlmCard status={llm.data} />
        <PropertiesCard />
        <BudgetCard status={llm.data} />
      </>
    );
  }
  if (llm.isPending) return <Spinner label="Lädt…" />;
  if (isRouteMissing(llm.error)) {
    return (
      <EmptyState icon={Cpu} title="Der externe KI-Dienst fehlt auf diesem Server.">
        Diese Version kann keine externe KI ansprechen.
      </EmptyState>
    );
  }
  return (
    <EmptyState
      title="Die KI-Einstellungen ließen sich nicht laden."
      action={
        <Button size="sm" variant="secondary" onPress={() => void llm.refetch()}>
          Nochmal versuchen
        </Button>
      }
    >
      {errorText(llm.error)}
    </EmptyState>
  );
}

export function MlSection() {
  const enabled = useWallEnabled();
  return (
    <section
      aria-labelledby="section-title"
      className="@container grid content-start gap-5 px-4 py-4 lg:px-6 lg:py-5"
    >
      <header className="grid gap-2">
        <h1 id="section-title" tabIndex={-1} className="text-xl font-bold outline-none">
          ML-Pipeline
        </h1>
        <p className="max-w-prose text-sm text-ink-muted">
          Jedes Foto läuft nach dem Hochladen einmal durch die Analyse. Die Ergebnisse füllen die Kategorien
          der Live-Wall.
        </p>
      </header>
      {enabled === false ? (
        <EmptyState icon={Cpu} title="Die Analyse ist auf diesem Server aus.">
          Die Erweiterung „wall“ ist nicht geladen.
        </EmptyState>
      ) : enabled === undefined ? (
        <Spinner label="Lädt…" />
      ) : (
        // two independent stacks once the section has room for two ~32rem columns (a
        // 1440 px window with the sidebar), else one column of readable width
        <div className={ADMIN_COLUMNS}>
          <div className="grid min-w-0 content-start gap-y-8" data-testid="ml-column">
            <ModelsCard />
            <TestImageCard />
          </div>
          <div className="grid min-w-0 content-start gap-y-8" data-testid="ml-column">
            <ExternalAi />
          </div>
        </div>
      )}
    </section>
  );
}
