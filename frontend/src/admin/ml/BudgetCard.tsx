/**
 * "Budget": what the external AI cost so far (party and today) against the limits, by
 * kind (Erkennung, Eigenschaft …, Urteil …, Test), and the limits themselves. At a
 * limit every external call stops: „Budget erreicht – externe KI pausiert“.
 */
import { useQueryClient } from '@tanstack/react-query';
import { OctagonPause, Save, Wallet } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { formatNumber } from '@/lib/format';
import { Button } from '@/ui/Button';
import { cx } from '@/ui/cx';
import { TextField } from '@/ui/TextField';
import { showToast } from '@/ui/Toast';
import { errorText } from '../common/usePhotoActions';
import { numberText } from '../wall/categories/spec';
import { Card } from '../wall/fields';
import { wk } from '../wall/keys';
import { saveLlmConfig } from './api';
import { fill, parseLimit } from './forms';
import { usageKindText, usdText } from './text';
import type { LlmBudget, LlmStatus } from './types';

function Meter({
  label,
  used,
  limit,
  format,
  testid,
}: {
  label: string;
  used: number;
  limit: number | null;
  format: (n: number) => string;
  testid: string;
}) {
  const f = fill(used, limit);
  const text = limit === null ? `${format(used)} · ohne Limit` : `${format(used)} von ${format(limit)}`;
  return (
    <div className="grid gap-1" data-testid={testid}>
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="font-semibold">{label}</span>
        <span className="text-ink-muted tabular">{text}</span>
      </div>
      <div aria-hidden="true" className="h-2 overflow-hidden rounded-full bg-surface-sunk">
        {f === null ? null : (
          <div
            className={cx(
              'h-full rounded-full',
              f >= 1 ? 'bg-danger-fill' : f >= 0.8 ? 'bg-accent' : 'bg-ink',
            )}
            style={{ width: `${(f * 100).toFixed(1)}%` }}
          />
        )}
      </div>
    </div>
  );
}

const calls = (n: number) => `${formatNumber(n)} ${n === 1 ? 'Aufruf' : 'Aufrufe'}`;

type LimitKey = keyof LlmBudget;
const limitText = (n: number | null) => (n === null ? '' : numberText(n));
const LIMIT_FIELDS: Array<{ key: LimitKey; label: string; money: boolean }> = [
  { key: 'party_usd', label: 'Party gesamt (USD)', money: true },
  { key: 'party_calls', label: 'Party gesamt (Aufrufe)', money: false },
  { key: 'daily_usd', label: 'Pro Tag (USD)', money: true },
  { key: 'daily_calls', label: 'Pro Tag (Aufrufe)', money: false },
];

function Limits({ status }: { status: LlmStatus }) {
  const qc = useQueryClient();
  const budget = status.config.budget;
  const initial = (): Record<LimitKey, string> => ({
    party_usd: limitText(budget.party_usd),
    party_calls: limitText(budget.party_calls),
    daily_usd: limitText(budget.daily_usd),
    daily_calls: limitText(budget.daily_calls),
  });
  const [texts, setTexts] = useState<Record<LimitKey, string>>(initial);
  const [errors, setErrors] = useState<Partial<Record<LimitKey, string>>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const next: LlmBudget = { ...budget };
    const errs: Partial<Record<LimitKey, string>> = {};
    for (const f of LIMIT_FIELDS) {
      const v = parseLimit(texts[f.key], f.money);
      if (v === 'bad')
        errs[f.key] = f.money ? 'Bitte einen Betrag, z. B. 5 oder 2,50.' : 'Bitte eine ganze Zahl.';
      else next[f.key] = v;
    }
    setErrors(errs);
    setFormError(null);
    if (Object.keys(errs).length > 0) return;
    setBusy(true);
    try {
      qc.setQueryData(wk.llm, await saveLlmConfig({ ...status.config, budget: next }));
      showToast({ message: 'Limits gespeichert.', tone: 'success' });
    } catch (err) {
      setFormError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      noValidate
      onSubmit={(e) => void submit(e)}
      className="grid gap-3 border-t border-line pt-3"
      data-testid="ml-limits"
    >
      <p className="text-sm font-semibold">Limits (leer = ohne Limit)</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {LIMIT_FIELDS.map((f) => (
          <TextField
            key={f.key}
            label={f.label}
            size="sm"
            inputMode={f.money ? 'decimal' : 'numeric'}
            value={texts[f.key]}
            onChange={(v) => {
              setTexts((t) => ({ ...t, [f.key]: v }));
              setErrors((x) => ({ ...x, [f.key]: undefined }));
            }}
            errorMessage={errors[f.key] ?? null}
          />
        ))}
      </div>
      {formError ? (
        <p role="alert" className="text-sm text-danger">
          {formError}
        </p>
      ) : null}
      <Button
        type="submit"
        size="sm"
        variant="secondary"
        icon={Save}
        isPending={busy}
        className="justify-self-start"
      >
        Limits speichern
      </Button>
    </form>
  );
}

export function BudgetCard({ status }: { status: LlmStatus }) {
  const { usage } = status;
  const b = usage.budget;
  return (
    <Card
      id="budget"
      title="Budget"
      icon={Wallet}
      intro="Geschätzte Kosten nach der Preisliste des Modells. Abgerechnet wird beim KI-Dienst in US-Dollar."
    >
      {usage.blocked ? (
        <div
          className="flex items-start gap-2 rounded-control border border-danger px-3 py-2 text-sm text-danger"
          data-testid="ml-budget-blocked"
        >
          <OctagonPause aria-hidden="true" className="mt-0.5 size-4 shrink-0" strokeWidth={2.25} />
          <div>
            <p className="font-semibold">Budget erreicht – externe KI pausiert</p>
            {usage.reason ? <p>{usage.reason}</p> : null}
          </div>
        </div>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2">
        <Meter
          label="Party: Kosten"
          used={usage.party.cost_usd}
          limit={b.party_usd}
          format={usdText}
          testid="ml-meter-party-usd"
        />
        <Meter
          label="Party: Aufrufe"
          used={usage.party.calls}
          limit={b.party_calls}
          format={calls}
          testid="ml-meter-party-calls"
        />
        <Meter
          label="Heute: Kosten"
          used={usage.today.cost_usd}
          limit={b.daily_usd}
          format={usdText}
          testid="ml-meter-today-usd"
        />
        <Meter
          label="Heute: Aufrufe"
          used={usage.today.calls}
          limit={b.daily_calls}
          format={calls}
          testid="ml-meter-today-calls"
        />
      </div>
      <p className="text-xs text-ink-muted tabular">
        Party: {formatNumber(usage.party.input_tokens)} Tokens rein, {formatNumber(usage.party.output_tokens)}{' '}
        raus
      </p>
      {usage.by_kind.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[22rem] text-sm" data-testid="ml-usage-table">
            <caption className="sr-only">Kosten nach Art</caption>
            <thead>
              <tr className="border-b border-line text-left text-ink-muted">
                <th scope="col" className="py-1.5 font-semibold">
                  Wofür
                </th>
                <th scope="col" className="py-1.5 text-right font-semibold">
                  Aufrufe
                </th>
                <th scope="col" className="py-1.5 text-right font-semibold">
                  Tokens
                </th>
                <th scope="col" className="py-1.5 text-right font-semibold">
                  Kosten
                </th>
              </tr>
            </thead>
            <tbody>
              {usage.by_kind.map((row) => (
                <tr key={`${row.kind}:${row.ref ?? ''}`} className="border-b border-line">
                  <th scope="row" className="py-1.5 text-left font-normal">
                    {usageKindText(row)}
                  </th>
                  <td className="py-1.5 text-right tabular">{formatNumber(row.calls)}</td>
                  <td className="py-1.5 text-right tabular">{formatNumber(row.tokens)}</td>
                  <td className="py-1.5 text-right tabular">{usdText(row.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-sm text-ink-muted">Noch nichts verbraucht.</p>
      )}
      <Limits key={status.config.rev} status={status} />
    </Card>
  );
}
