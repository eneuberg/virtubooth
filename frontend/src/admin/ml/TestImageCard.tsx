/**
 * "Testbild": run the pipeline (or one analyzer) on an image and see what comes out:
 * frames, objects, values, durations. Optionally also through the external AI (costs
 * money, counts against the budget). The objects as three tabs: the local model's,
 * the AI's and the merged list a photo would get. Nothing is stored as a party photo.
 */
import { FlaskConical, ImageUp, Play } from 'lucide-react';
import { useState } from 'react';
import { FileTrigger } from 'react-aria-components';
import { formatBytes } from '@/lib/format';
import { Button } from '@/ui/Button';
import { Checkbox } from '@/ui/Checkbox';
import { Select } from '@/ui/Select';
import { BoxLayer } from '../wall/AnalysisPanel';
import { Card } from '../wall/fields';
import { useAnalysisStatus } from '../wall/hooks';
import { testViews, viewFrames, type ObjectView } from '../wall/objectViews';
import { ObjectViewTabs } from '../wall/ObjectViewTabs';
import { factValue, type FrameBox } from '../wall/text';
import { runTestImage } from './api';
import { useLlm } from './hooks';
import { externalBlocked, testErrorText } from './forms';
import { durationsText, usdText } from './text';
import type { TestImageResult } from './types';

const ACCEPT = ['image/jpeg', 'image/png'];
const ALL = '__all__';

const EMPTY: Record<ObjectView, string> = {
  local: 'Das lokale Modell lief nicht (nicht gewählt oder aus).',
  ai: 'Nicht an die KI geschickt (Haken „Auch an Claude schicken“).',
  merged: 'Keine Objekte erkannt.',
};

function Result({
  result,
  preview,
  titles,
}: {
  result: TestImageResult;
  preview: string | null;
  titles: Map<string, string>;
}) {
  const local = result.local;
  const external = result.external;
  const [view, setView] = useState<ObjectView>('merged');
  const [hovered, setHovered] = useState<string | null>(null);
  const views = testViews(result);
  const frames: FrameBox[] = [
    ...(local?.boxes ?? []).filter((b) => b.kind !== 'object' && b.kind !== 'person'),
    ...viewFrames(views[view] ?? [], view),
  ];
  const highlight = hovered?.startsWith(`${view}:`) ? Number(hovered.slice(view.length + 1)) : null;
  const facts = Object.entries(local?.facts ?? {});
  const skipped = Object.entries(local?.skipped ?? {});
  const durations = local ? durationsText(local.durations_ms, titles) : '';
  return (
    <div className="grid gap-4" data-testid="ml-test-result">
      {preview ? (
        <div
          className="relative mx-auto w-full max-w-md overflow-hidden bg-surface-sunk"
          style={{ aspectRatio: `${result.width} / ${result.height}` }}
        >
          <img src={preview} alt="Testbild" className="size-full object-fill" />
          <BoxLayer boxes={frames} highlight={highlight} />
        </div>
      ) : null}
      {local?.error ? <p className="text-sm text-danger">{local.error}</p> : null}
      {external?.error ? <p className="text-sm text-danger">KI-Dienst: {external.error}</p> : null}
      {skipped.length > 0 ? (
        <p className="text-sm text-ink-muted" data-testid="ml-test-skipped">
          Nicht gelaufen: {skipped.map(([name, why]) => `${titles.get(name) ?? name} (${why})`).join(', ')}
        </p>
      ) : null}
      <div className="grid gap-1.5">
        <h3 className="text-sm font-bold">Objekte</h3>
        <ObjectViewTabs
          views={views}
          value={view}
          onChange={setView}
          onHover={(v, key) => setHovered(key === null ? null : `${v}:${key}`)}
          empty={EMPTY}
          listTestId="ml-test-objects"
        />
      </div>
      {local && local.details.length > 0 ? (
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-5 gap-y-1.5 text-sm">
          {local.details.map((d) => (
            <div key={d.label} className="contents">
              <dt className="text-ink-muted">{d.label}</dt>
              <dd>{d.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {facts.length > 0 ? (
        <table className="w-full text-xs" data-testid="ml-test-facts">
          <caption className="text-left text-sm font-bold">Werte</caption>
          <tbody>
            {facts.map(([k, v]) => (
              <tr key={k} className="border-b border-line">
                <th scope="row" className="font-mono py-1 text-left font-normal text-ink-muted">
                  {k}
                </th>
                <td className="py-1 text-right tabular">{factValue(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {durations ? (
        <p className="text-xs text-ink-muted tabular" data-testid="ml-test-durations">
          Dauer: {durations}
        </p>
      ) : null}
      {external?.usage ? (
        <p className="text-xs text-ink-muted tabular">
          KI-Dienst: {external.usage.input_tokens + external.usage.output_tokens} Tokens ·{' '}
          {usdText(external.usage.cost_usd)}
        </p>
      ) : null}
    </div>
  );
}

export function TestImageCard() {
  const status = useAnalysisStatus();
  const llm = useLlm();
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [target, setTarget] = useState<string>(ALL);
  const [external, setExternal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TestImageResult | null>(null);
  // the tested image, shown under its frames (an object URL; the old one is let go)
  const [preview, setPreview] = useState<string | null>(null);

  const analyzers = (status.data?.analyzers ?? []).filter((a) => a.available);
  const titles = new Map(analyzers.map((a) => [a.name, a.title]));
  const blocked = externalBlocked(llm.data);
  const options = [
    { id: ALL, label: 'Ganze Pipeline' },
    ...analyzers.map((a) => ({ id: a.name, label: a.title })),
  ];

  const pick = (files: FileList | null) => {
    const f = files?.[0] ?? null;
    if (f && !ACCEPT.includes(f.type)) {
      setFileError('Bitte ein JPEG- oder PNG-Bild.');
      return;
    }
    setFileError(null);
    setFile(f);
  };

  const run = async () => {
    if (!file) {
      setFileError('Bitte erst ein Bild wählen.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const out = await runTestImage(file, target === ALL ? null : [target], external && !blocked);
      setResult(out);
      setPreview((old) => {
        if (old) URL.revokeObjectURL(old);
        return URL.createObjectURL(file);
      });
    } catch (err) {
      setError(testErrorText(err));
      setResult(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card
      id="testbild"
      title="Testbild"
      icon={FlaskConical}
      intro="Probier ein Bild aus und sieh, was die Analyse daraus macht. Das Testbild wird nicht gespeichert."
    >
      <div className="grid gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <FileTrigger acceptedFileTypes={ACCEPT} onSelect={pick}>
            <Button size="sm" variant="secondary" icon={ImageUp} data-testid="ml-test-file">
              Bild wählen
            </Button>
          </FileTrigger>
          <span className="min-w-0 truncate text-sm text-ink-muted" data-testid="ml-test-filename">
            {file ? `${file.name} (${formatBytes(file.size)})` : 'Kein Bild gewählt'}
          </span>
        </div>
        {fileError ? (
          <p role="alert" className="text-sm text-danger">
            {fileError}
          </p>
        ) : null}
        <Select
          label="Was soll laufen?"
          size="sm"
          options={options}
          value={target}
          onChange={setTarget}
          data-testid="ml-test-target"
        />
        <Checkbox
          isSelected={external && !blocked}
          isDisabled={blocked !== null}
          onChange={setExternal}
          data-testid="ml-test-external"
        >
          Auch an Claude schicken (kostet)
        </Checkbox>
        {blocked ? <p className="-mt-2 text-xs text-ink-muted">{blocked}</p> : null}
        <Button
          size="sm"
          variant="primary"
          icon={Play}
          isPending={busy}
          onPress={() => void run()}
          className="justify-self-start"
          data-testid="ml-test-run"
        >
          Testen
        </Button>
        {error ? (
          <p role="alert" className="text-sm text-danger" data-testid="ml-test-error">
            {error}
          </p>
        ) : null}
      </div>
      {result ? <Result result={result} preview={preview} titles={titles} /> : null}
    </Card>
  );
}
