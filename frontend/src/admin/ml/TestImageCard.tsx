/**
 * "Testbild": run the pipeline (or one analyzer) on an image and see what comes out:
 * frames, objects, values, durations. Optionally also through the external AI (costs
 * money, counts against the budget). Nothing is stored as a party photo.
 */
import { FlaskConical, ImageUp, Play } from 'lucide-react';
import { useState } from 'react';
import { FileTrigger } from 'react-aria-components';
import { formatBytes } from '@/lib/format';
import { Badge } from '@/ui/Badge';
import { Button } from '@/ui/Button';
import { Checkbox } from '@/ui/Checkbox';
import { Select } from '@/ui/Select';
import { BoxLayer } from '../wall/AnalysisPanel';
import { Card } from '../wall/fields';
import { useAnalysisStatus } from '../wall/hooks';
import { factValue, objectBoxes, type FrameBox } from '../wall/text';
import { runTestImage } from './api';
import { useLlm } from './hooks';
import { externalBlocked, testErrorText } from './forms';
import { durationsText, scoreText, sourceText, usdText } from './text';
import type { TestImageResult, TestObject } from './types';

const ACCEPT = ['image/jpeg', 'image/png'];
const ALL = '__all__';


type Row = TestObject & { source: string };

const row = (o: TestObject, source: string): Row => ({
  label: o.label,
  label_de: o.label_de,
  score: o.score,
  box: o.box,
  source,
});

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
  const objects: Row[] = [
    ...(local?.objects ?? []).map((o) => row(o, 'local')),
    ...(external?.objects ?? []).map((o) => row(o, 'claude')),
  ];
  const frames: FrameBox[] = [
    ...(local?.boxes ?? []).filter((b) => b.kind !== 'object' && b.kind !== 'person'),
    ...objectBoxes(objects),
  ];
  const facts = Object.entries(local?.facts ?? {});
  const durations = local ? durationsText(local.durations_ms, titles) : '';
  return (
    <div className="grid gap-4" data-testid="ml-test-result">
      {preview ? (
        <div
          className="relative mx-auto w-full max-w-md overflow-hidden bg-surface-sunk"
          style={{ aspectRatio: `${result.width} / ${result.height}` }}
        >
          <img src={preview} alt="Testbild" className="size-full object-fill" />
          <BoxLayer boxes={frames} />
        </div>
      ) : null}
      {local?.error ? <p className="text-sm text-danger">{local.error}</p> : null}
      {external?.error ? <p className="text-sm text-danger">Claude: {external.error}</p> : null}
      <div className="grid gap-1.5">
        <h3 className="text-sm font-bold">Objekte</h3>
        {objects.length === 0 ? (
          <p className="text-sm text-ink-muted">Keine Objekte erkannt.</p>
        ) : (
          <ol className="grid border-t border-line text-sm" data-testid="ml-test-objects">
            {objects.map((o, i) => (
              // objects have no id; the order is the server's
              // oxlint-disable-next-line react/no-array-index-key
              <li key={i} className="flex items-center gap-2 border-b border-line py-1.5">
                <span className="min-w-0 flex-1 truncate font-semibold" title={o.label}>
                  {o.label_de}
                </span>
                <span className="tabular">{scoreText(o.score)}</span>
                <Badge tone={o.source === 'local' ? 'neutral' : 'new'}>{sourceText(o.source)}</Badge>
              </li>
            ))}
          </ol>
        )}
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
          Claude: {external.usage.input_tokens + external.usage.output_tokens} Tokens ·{' '}
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
