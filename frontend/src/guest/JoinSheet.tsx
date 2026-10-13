/**
 * The join sheet: the server's join texts (ConsentInfo), an optional Instagram name,
 * and ONE button. There is no "no": this is not a registration, and declining means
 * not using the site, so the sheet cannot be dismissed (no close button, Esc and the
 * scrim do nothing). Focus starts on the dialog, not the field, so a phone keyboard
 * does not cover the text.
 *
 * Names stay blocker-neutral: test id `join` on the scrim (`vb-scrim`), `vb-sheet` on
 * the dialog; nothing in here may be called consent, cookie, banner, modal, popup, …
 */
import { useId, useRef, useState, type FormEvent } from 'react';
import { isApiError } from '@/api/errors';
import { msg, quoted } from '@/lib/messages.de';
import { HandleField } from '@/sdk/components/HandleField';
import { shortName } from '@/sdk/identity';
import { joinParty, sessionStore, type JoinInfo } from '@/sdk/session';
import { Button } from '@/ui/Button';
import { HelpDisclosure } from '@/ui/HelpDisclosure';
import { Sheet } from '@/ui/Sheet';
import { showToast } from '@/ui/Toast';
import { splitParagraphs, splitPrompt, tidy } from './copy';

export interface JoinSheetProps {
  join: JoinInfo;
  /** the activity the guest is on its way to ("Beer Cam"), from the URL */
  destination?: string | null;
}

const OUTDATED = 'Die Hinweise haben sich gerade geändert. Lies sie kurz, dann tippe nochmal auf den Knopf.';

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
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
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
      await joinParty({ instagram: instagram || null });
      welcomeBack();
    } catch (err) {
      if (isApiError(err) && err.code === 'invalid_instagram') {
        setFieldError(err.message);
        inputRef.current?.focus();
      } else if (isApiError(err) && err.code === 'consent_outdated') {
        setFormError(OUTDATED);
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
          {formError ? (
            <p role="alert" className="text-sm font-semibold text-danger">
              {formError}
            </p>
          ) : destination ? (
            <p className="text-center text-xs text-ink-muted">
              Gleich geht’s zur <span translate="no">{destination}</span>.
            </p>
          ) : null}
          <Button type="submit" form={formId} variant="primary" size="lg" block isPending={pending}>
            {tidy(join.accept_label)}
          </Button>
        </div>
      }
    >
      <form id={formId} onSubmit={(event) => void submit(event)} noValidate className="grid gap-4">
        {lead.map((p) => (
          <p key={p} className="text-md">
            {p}
          </p>
        ))}
        {more.length ? (
          <HelpDisclosure summary="Mehr dazu" headingLevel={false}>
            {more.map((p) => (
              <p key={p}>{p}</p>
            ))}
          </HelpDisclosure>
        ) : null}
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
      </form>
    </Sheet>
  );
}
