/**
 * The join sheet: the server's join texts (ConsentInfo), an optional Instagram name,
 * and ONE button. There is no "no": this is not a registration, and declining means
 * not using the site, so the sheet cannot be dismissed (no close button, Esc and the
 * scrim do nothing). Focus starts on the dialog, not the field, so a phone keyboard
 * does not cover the text.
 *
 * Names stay blocker-neutral: test id `join` on the scrim (`vb-scrim`), `vb-sheet` on
 * the dialog; nothing in here may be called consent, cookie, banner, modal, popup, …
 *
 * While the host stopped joining („Anmeldung stoppen“), the button gives way to a calm
 * "try again soon" (JoinClosed); the session re-checks by itself and the button returns.
 */
import { useId, useRef, useState, type FormEvent } from 'react';
import { isApiError } from '@/api/errors';
import { msg, quoted } from '@/lib/messages.de';
import { HandleField } from '@/sdk/components/HandleField';
import { ANALYSIS_OPT_OUT, EXTERNAL_AI_OPT_OUT, shortName } from '@/sdk/identity';
import { joinParty, refreshSession, sessionStore, useJoinClosed, type JoinInfo } from '@/sdk/session';
import { Button } from '@/ui/Button';
import { HelpDisclosure } from '@/ui/HelpDisclosure';
import { Sheet } from '@/ui/Sheet';
import { Switch } from '@/ui/Switch';
import { showToast } from '@/ui/Toast';
import { splitParagraphs, splitPrompt, tidy } from './copy';

export interface JoinSheetProps {
  join: JoinInfo;
  /** the activity the guest is on its way to ("Beer Cam"), from the URL; shown quoted, so any title fits */
  destination?: string | null;
}

const OUTDATED = 'Die Hinweise haben sich gerade geändert. Lies sie kurz, dann tippe nochmal auf den Knopf.';
/** The host's overview counts scans (a random id per browser, see api.md §7): said under „Mehr dazu“. */
export const SCAN_COUNT_NOTE =
  'Außerdem zählt die Seite anonym, wie viele Geräte den QR-Code geöffnet haben – nur für die Übersicht der Gastgeber.';

/** After joining in a second tab: say who you are (and that the other tab's handle counts). */
function welcomeBack(): void {
  const outcome = sessionStore.getState().outcome;
  if (!outcome?.alreadyJoined) return;
  const insta = outcome.user.instagram ? ` (@${outcome.user.instagram})` : '';
  const hint = outcome.instagramKept ? ' Tipp auf deinen Namen, um Instagram zu ändern.' : '';
  showToast(
    {
      tone: 'info',
      message: `Du bist schon dabei als ${quoted(shortName(outcome.user.name))}${insta}.${hint}`,
    },
    { timeout: 7000 },
  );
}

export function JoinSheet({ join, destination }: JoinSheetProps) {
  const formId = useId();
  const [instagram, setInstagram] = useState('');
  const [analysisOptOut, setAnalysisOptOut] = useState(false);
  const [aiOptOut, setAiOptOut] = useState(false);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const closed = useJoinClosed();
  const inputRef = useRef<HTMLInputElement>(null);

  const { lead, more } = splitParagraphs(join.paragraphs);
  const prompt = splitPrompt(join.instagram_prompt);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setFieldError(null);
    setFormError(null);
    try {
      await joinParty({
        instagram: instagram || null,
        analysisOptOut: join.analysis && analysisOptOut,
        aiOptOut: join.external_ai && aiOptOut,
      });
      welcomeBack();
    } catch (err) {
      if (isApiError(err) && err.code === 'invalid_instagram') {
        setFieldError(err.message);
        inputRef.current?.focus();
      } else if (isApiError(err) && err.code === 'consent_outdated') {
        setFormError(OUTDATED);
      } else if (isApiError(err) && err.code === 'join_closed') {
        // the session is "closed" now: JoinClosed says it calmly
      } else {
        setFormError(isApiError(err) ? err.message : msg.generic);
      }
      setPending(false);
    }
  };

  return (
    <Sheet
      isOpen
      isDismissable={false}
      title={tidy(join.title)}
      titleSize="xl"
      data-testid="join"
      footer={
        <div className="grid gap-2">
          {closed ? (
            <JoinClosed />
          ) : formError ? (
            <p role="alert" className="text-sm font-semibold text-danger">
              {formError}
            </p>
          ) : destination ? (
            <p className="text-center text-xs text-ink-muted">
              Danach öffnet sich <span translate="no">{quoted(destination)}</span>.
            </p>
          ) : null}
          {closed ? null : (
            <Button type="submit" form={formId} variant="primary" size="lg" block isPending={pending}>
              {tidy(join.accept_label)}
            </Button>
          )}
        </div>
      }
    >
      <form id={formId} onSubmit={(event) => void submit(event)} noValidate className="grid gap-4">
        {lead.map((p) => (
          <p key={p} className="text-md">
            {p}
          </p>
        ))}
        <HelpDisclosure summary="Mehr dazu" headingLevel={false}>
          {more.map((p) => (
            <p key={p}>{p}</p>
          ))}
          <p>{SCAN_COUNT_NOTE}</p>
          {join.analysis ? (
            <Switch
              isSelected={analysisOptOut}
              onChange={setAnalysisOptOut}
              description={ANALYSIS_OPT_OUT.help}
              data-testid="analysis-opt-out"
            >
              {ANALYSIS_OPT_OUT.label}
            </Switch>
          ) : null}
        </HelpDisclosure>
        <HandleField
          label={prompt.label}
          description={prompt.help}
          value={instagram}
          onChange={(value) => {
            setInstagram(value);
            setFieldError(null);
          }}
          errorMessage={fieldError}
          inputRef={inputRef}
          className="mt-1"
        />
        {join.external_ai ? (
          <Switch
            isSelected={aiOptOut}
            onChange={setAiOptOut}
            description={EXTERNAL_AI_OPT_OUT.help}
            data-testid="ai-opt-out"
          >
            {EXTERNAL_AI_OPT_OUT.label}
          </Switch>
        ) : null}
      </form>
    </Sheet>
  );
}

/** Joining is stopped for a moment: say so calmly, offer a manual re-check. */
function JoinClosed() {
  const [checking, setChecking] = useState(false);
  const recheck = async () => {
    setChecking(true);
    try {
      await refreshSession();
    } finally {
      setChecking(false);
    }
  };
  return (
    <div className="grid gap-3">
      <output data-testid="join-closed" className="grid gap-1 text-center">
        <span className="text-md font-semibold">Gerade kann niemand neu beitreten.</span>
        <span className="text-sm text-ink-muted">
          Versuch es gleich noch mal. Sobald es wieder geht, erscheint der Knopf von selbst.
        </span>
      </output>
      <Button
        variant="secondary"
        size="lg"
        block
        isPending={checking}
        pendingLabel="Prüft…"
        onPress={() => void recheck()}
        data-testid="join-recheck"
      >
        Nochmal versuchen
      </Button>
    </div>
  );
}
