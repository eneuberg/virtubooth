/**
 * "Externe KI": the external AI's master switch (off: nothing leaves the server),
 * provider, model and „Denkaufwand“ (one PUT /llm/config with just these), then the API
 * key of the provider picked here (one key per provider, switching keeps them; set /
 * replace / delete / test; it is never shown or prefilled, after saving only „gesetzt“). What the AI does lives with the features: „Objekte mit KI“ in Modelle,
 * „Eigenschaften abfragen“ in Eigenschaften, each with a red hint while this is off.
 */
import { useQueryClient } from '@tanstack/react-query';
import { KeyRound, Save, ShieldCheck, Sparkles, Trash2 } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { formatDateTime } from '@/lib/format';
import { Badge } from '@/ui/Badge';
import { Button } from '@/ui/Button';
import { cx } from '@/ui/cx';
import { ConfirmDialog } from '@/ui/ConfirmDialog';
import { Select } from '@/ui/Select';
import { Switch } from '@/ui/Switch';
import { TextField } from '@/ui/TextField';
import { showToast } from '@/ui/Toast';
import { errorText, showError } from '../common/usePhotoActions';
import { Card } from '../wall/fields';
import { wk } from '../wall/keys';
import { EXTERNAL_AI_CARD } from './ExternalAiHint';
import { clearLlmKey, saveLlmConfig, setLlmKey, testLlmKey } from './api';
import { EFFORT_LABELS, keyOf, keyStatusText } from './forms';
import { modelText } from './text';
import { EFFORTS, type Effort, type LlmConfig, type LlmKeyState, type LlmStatus } from './types';

/** The fields this card edits (the poll is the Eigenschaften card's, the budget the Budget card's). */
interface Fields {
  enabled: boolean;
  provider: string;
  model: string;
  effort: Effort;
}

function fieldsOf(c: LlmConfig): Fields {
  return { enabled: c.enabled, provider: c.provider, model: c.model, effort: c.effort };
}

const sameFields = (a: Fields, b: Fields) => JSON.stringify(a) === JSON.stringify(b);

/** The provider's name without the parenthesis: „Scaleway“, „Anthropic“. */
const shortTitle = (title: string) => title.split(' (')[0] ?? title;

function KeyBlock({ status, provider, model }: { status: LlmStatus; provider: string; model: string }) {
  const qc = useQueryClient();
  const key = keyOf(status, provider);
  const title = status.providers.find((p) => p.id === provider)?.title ?? provider;
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'save' | 'test' | null>(null);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [clearError, setClearError] = useState<string | null>(null);
  const open = !key.set || editing;

  const store = (state: LlmKeyState) =>
    qc.setQueryData<LlmStatus>(wk.llm, (old) =>
      old
        ? {
            ...old,
            key: state.provider === old.config.provider ? state : old.key,
            keys: [...old.keys.filter((k) => k.provider !== state.provider), state],
          }
        : old,
    );

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const k = value.trim();
    if (!k || /\s/.test(k) || k.length > 400) {
      setError('Bitte den Schlüssel ohne Leerzeichen einfügen (höchstens 400 Zeichen).');
      return;
    }
    setBusy('save');
    setError(null);
    setResult(null);
    try {
      store(await setLlmKey(provider, k));
      setValue('');
      setEditing(false);
      showToast({ message: 'API-Schlüssel gespeichert.', tone: 'success' });
      void qc.invalidateQueries({ queryKey: wk.llm });
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  };

  const test = async () => {
    setBusy('test');
    setResult(null);
    try {
      const out = await testLlmKey(provider, model);
      const message = out.message || (out.ok ? 'Der Schlüssel funktioniert.' : 'Fehlgeschlagen.');
      setResult({ ok: out.ok, message });
      showToast({ message, tone: out.ok ? 'success' : 'error' });
    } catch (err) {
      // key rejected, none stored: the server's German reason
      setResult({ ok: false, message: errorText(err) });
      showError(err);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="grid gap-2 border-t border-line pt-3" data-testid="ml-key">
      <p className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-semibold">
          API-Schlüssel <span className="font-normal text-ink-muted">für {shortTitle(title)}</span>
        </span>
        <Badge tone={key.set && key.valid ? 'ok' : 'mark'} icon={key.set ? ShieldCheck : undefined}>
          <span data-testid="ml-key-state">{keyStatusText(key)}</span>
        </Badge>
        {key.set && key.set_at ? (
          <span className="text-ink-muted">
            seit <time dateTime={key.set_at}>{formatDateTime(key.set_at)}</time>
          </span>
        ) : null}
      </p>
      {open ? (
        <form
          noValidate
          onSubmit={(e) => void submit(e)}
          className="grid gap-2 @md:grid-cols-[minmax(0,1fr)_auto] @md:items-start"
          autoComplete="off"
        >
          <TextField
            label={key.set ? 'Neuer API-Schlüssel' : 'API-Schlüssel'}
            // the status line above already says „API-Schlüssel“
            hideLabel={!key.set}
            type="password"
            autoComplete="new-password"
            spellCheck="false"
            size="sm"
            value={value}
            onChange={(v) => {
              setValue(v);
              setError(null);
            }}
            errorMessage={error}
            description="Wird verschlüsselt gespeichert und nie wieder angezeigt."
            data-testid="ml-key-input"
          />
          {/* level with the input: below the label when it is shown */}
          <div className={cx('flex flex-wrap gap-2', key.set && '@md:mt-6.5')}>
            <Button
              type="submit"
              size="sm"
              variant="secondary"
              isPending={busy === 'save'}
              data-testid="ml-key-save"
            >
              Speichern
            </Button>
            {key.set ? (
              <Button
                size="sm"
                variant="quiet"
                onPress={() => {
                  setEditing(false);
                  setValue('');
                  setError(null);
                }}
              >
                Abbrechen
              </Button>
            ) : null}
          </div>
        </form>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button
            size="xs"
            variant="secondary"
            icon={KeyRound}
            onPress={() => setEditing(true)}
            data-testid="ml-key-replace"
          >
            Schlüssel ersetzen
          </Button>
          <Button
            size="xs"
            variant="secondary"
            icon={ShieldCheck}
            isPending={busy === 'test'}
            onPress={() => void test()}
            data-testid="ml-key-test"
          >
            Testen
          </Button>
          <Button
            size="xs"
            variant="danger-outline"
            icon={Trash2}
            onPress={() => {
              setClearError(null);
              setConfirm(true);
            }}
            data-testid="ml-key-clear"
          >
            Schlüssel löschen…
          </Button>
        </div>
      )}
      {result ? (
        <p
          role={result.ok ? 'status' : 'alert'}
          className={cx('text-sm', result.ok ? 'text-ok' : 'text-danger')}
          data-testid="ml-key-test-result"
        >
          {result.message}
        </p>
      ) : null}
      <p className="text-xs text-ink-muted" data-testid="ml-key-overview">
        Jeder Anbieter hat seinen eigenen Schlüssel; beim Wechsel bleiben die anderen gespeichert.{' '}
        {status.providers.map((p, i) => {
          const k = keyOf(status, p.id);
          return (
            <span key={p.id} data-provider={p.id} data-set={k.set}>
              {i > 0 ? ' · ' : ''}
              {shortTitle(p.title)}: {k.set ? (k.valid ? 'gesetzt' : 'ungültig') : '–'}
            </span>
          );
        })}
      </p>
      <ConfirmDialog
        isOpen={confirm}
        onOpenChange={setConfirm}
        title={`API-Schlüssel für ${shortTitle(title)} löschen?`}
        confirmLabel="Schlüssel löschen"
        error={clearError}
        onConfirm={async () => {
          try {
            store(await clearLlmKey(provider));
            setResult(null);
            showToast({ message: `API-Schlüssel für ${shortTitle(title)} gelöscht.`, tone: 'success' });
            // „KI“ may have switched to „Lokal“ without this key
            void qc.invalidateQueries({ queryKey: wk.llm });
          } catch (err) {
            setClearError(errorText(err));
            throw err;
          }
        }}
        data-testid="confirm"
      >
        <p>
          Ohne Schlüssel schickt der Server nichts mehr an {shortTitle(title)}. Die Schlüssel anderer Anbieter
          bleiben.
        </p>
      </ConfirmDialog>
    </div>
  );
}

export function LlmCard({ status }: { status: LlmStatus }) {
  const qc = useQueryClient();
  const base = fieldsOf(status.config);
  const [edits, setEdits] = useState<Fields | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const f = edits ?? base;
  const dirty = edits !== null && !sameFields(edits, base);
  const set = (change: Partial<Fields>) => {
    setError(null);
    setEdits({ ...f, ...change });
  };

  const save = async () => {
    setBusy(true);
    try {
      const out = await saveLlmConfig({
        enabled: f.enabled,
        provider: f.provider,
        model: f.model,
        effort: f.effort,
      });
      qc.setQueryData(wk.llm, out);
      setEdits(null);
      showToast({ message: 'KI-Einstellungen gespeichert.', tone: 'success' });
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const provider = status.providers.find((p) => p.id === f.provider);
  // each provider has its own models (the server refuses a model of another one)
  const models = status.models.filter((m) => m.provider === f.provider);
  const pickProvider = (id: string) => {
    const keep = status.models.some((m) => m.provider === id && m.id === f.model);
    set({
      provider: id,
      model: keep ? f.model : (status.models.find((m) => m.provider === id)?.id ?? f.model),
    });
  };
  return (
    <Card
      id={EXTERNAL_AI_CARD}
      title="Externe KI"
      icon={Sparkles}
      intro="Optional: ein externer KI-Dienst erkennt Dinge auf den Fotos und bewertet Eigenschaften für die Live-Wall. Fotos von Gästen mit „Keine Weitergabe an externe KI“ gehen nie hinaus."
    >
      <Switch isSelected={f.enabled} onChange={(on) => set({ enabled: on })} data-testid="ml-llm-enabled">
        Externe KI verwenden
      </Switch>
      <p className="-mt-2 text-xs text-ink-muted">
        Aus: der Server schickt nichts an den KI-Dienst. Was die KI macht, schaltest du bei „Modelle“ (Objekte
        mit KI) und „Eigenschaften“ ein.
      </p>
      <div className="grid gap-3 @md:grid-cols-2">
        <Select
          label="Anbieter"
          size="sm"
          options={status.providers.map((p) => ({ id: p.id, label: p.title }))}
          value={f.provider}
          onChange={pickProvider}
          data-testid="ml-llm-provider"
        />
        <Select
          label="Modell"
          size="sm"
          options={models.map((m) => ({ id: m.id, label: modelText(m) }))}
          value={f.model}
          onChange={(model) => set({ model })}
          data-testid="ml-llm-model"
        />
      </div>
      {provider?.thinking ? (
        <div className="grid gap-1">
          <Select
            label="Denkaufwand"
            size="sm"
            options={EFFORTS.map((e) => ({ id: e, label: EFFORT_LABELS[e] }))}
            value={f.effort}
            onChange={(effort) => set({ effort })}
            className="max-w-xs"
            data-testid="ml-llm-effort"
          />
          <p className="text-xs text-ink-muted">
            Wie lange die KI vor der Antwort nachdenkt. Nachdenken wird als Ausgabe-Tokens berechnet: mehr
            Aufwand kostet mehr.
          </p>
        </div>
      ) : null}
      {provider && (provider.currency !== 'USD' || !provider.vision) ? (
        <ul className="grid gap-1 text-xs text-ink-muted" data-testid="ml-llm-provider-notes">
          {provider.currency === 'EUR' ? (
            <li>
              {provider.title.split(' (')[0]} rechnet in Euro ab; Kosten und Budget stehen hier in Dollar,
              umgerechnet mit 1 € = 1,10 $.
            </li>
          ) : null}
          {!provider.vision ? (
            <li>Kann keine Fotos ansehen: nur Eigenschaften, keine Objekterkennung.</li>
          ) : null}
        </ul>
      ) : null}
      {provider && !provider.available && provider.reason ? (
        <p className="text-sm text-danger">{provider.reason}</p>
      ) : null}
      {dirty ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="primary"
            icon={Save}
            isPending={busy}
            onPress={() => void save()}
            data-testid="ml-llm-save"
          >
            Speichern
          </Button>
          <Button size="sm" variant="quiet" onPress={() => setEdits(null)}>
            Verwerfen
          </Button>
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
      {/* the key of the provider picked above (also before saving the switch) */}
      <KeyBlock key={f.provider} status={status} provider={f.provider} model={f.model} />
    </Card>
  );
}
