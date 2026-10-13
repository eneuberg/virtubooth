/**
 * Help from the "?" on Start, and "Was passiert mit meinen Fotos?" from its footer
 * (the same sheet, that section open): the join texts read-only, the camera
 * permission, in-app browsers. Test id `help`.
 */
import { inAppBrowserName, isIOS } from '@/sdk/platform';
import { acceptedJoinText } from '@/sdk/session';
import { HelpDisclosure } from '@/ui/HelpDisclosure';
import { Sheet } from '@/ui/Sheet';
import { inAppAdvice, joinTextFor } from './copy';

export type HelpTopic = 'photos' | 'camera' | 'browser';

export interface HelpSheetProps {
  /** null: closed */
  topic: HelpTopic | 'all' | null;
  onClose: () => void;
  instagramAccount: string;
}

function cameraHelp(): string {
  return isIOS()
    ? 'Erlaube der Seite die Kamera: Tippe in der Adressleiste auf „aA“, dann auf „Website-Einstellungen“ und stell die Kamera auf „Erlauben“. Danach die Seite neu laden.'
    : 'Erlaube der Seite die Kamera: Tippe links in der Adressleiste auf das Schloss oder die Einstellungen, dann auf „Berechtigungen“ und erlaube die Kamera. Danach die Seite neu laden.';
}

export function HelpSheet({ topic, onClose, instagramAccount }: HelpSheetProps) {
  const paragraphs = joinTextFor(acceptedJoinText(), instagramAccount);
  const advice = inAppAdvice(inAppBrowserName());
  return (
    <Sheet
      isOpen={topic !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={topic === 'photos' ? 'Was passiert mit meinen Fotos?' : 'Hilfe'}
      size="md"
      data-testid="help"
    >
      {topic === 'photos' ? (
        <div className="grid gap-3">
          {paragraphs.map((p) => (
            <p key={p}>{p}</p>
          ))}
        </div>
      ) : (
        <div className="grid">
          <HelpDisclosure variant="section" summary="Was passiert mit meinen Fotos?" headingLevel={3}>
            {paragraphs.map((p) => (
              <p key={p}>{p}</p>
            ))}
          </HelpDisclosure>
          <HelpDisclosure
            variant="section"
            summary="Die Kamera startet nicht"
            headingLevel={3}
            defaultExpanded={topic === 'camera'}
          >
            <p>{cameraHelp()}</p>
          </HelpDisclosure>
          <HelpDisclosure
            variant="section"
            summary="Link in Instagram oder WhatsApp geöffnet?"
            headingLevel={3}
            defaultExpanded={topic === 'browser'}
          >
            <p>
              Die Browser in diesen Apps lassen die Kamera oft nicht zu. Öffne stattdessen die Kamera-App
              deines Handys und scanne den QR-Code damit: Dann öffnet sich die Seite im richtigen Browser.
            </p>
            {inAppBrowserName() ? <p className="text-ink-muted">{advice.text}</p> : null}
          </HelpDisclosure>
          <HelpDisclosure variant="section" summary="Warum heiße ich so?" headingLevel={3}>
            <p>
              Den Namen hat die Seite zufällig für dich ausgesucht. So bleibst du anonym. Tipp oben auf deinen
              Namen, um deinen Instagram-Namen einzutragen oder zu ändern.
            </p>
          </HelpDisclosure>
        </div>
      )}
    </Sheet>
  );
}
