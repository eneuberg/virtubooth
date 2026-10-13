/**
 * Full-screen states of the camera pages: the camera doesn't work, the device is
 * banned, the page couldn't start. OWNER: wave 2 "AC". One wording everywhere
 * (UX audit §3.1 "Notices"): titles name the problem, buttons say "Seite neu laden"
 * and "Zum Start", never "Ups".
 */
import { Ban, CameraOff, CircleAlert, WifiOff } from 'lucide-react';
import { fatalCopy, isApiError } from '@/api/errors';
import { msg, t } from '@/lib/messages.de';
import { Button, LinkButton } from '@/ui/Button';
import { Notice } from '@/ui/Notice';
import { CAMERA_ERROR_TITLE, cameraErrorMessage } from './errors';

function reload(): void {
  location.reload();
}

function Actions({ reloadFirst = true }: { reloadFirst?: boolean }) {
  return (
    <>
      {reloadFirst ? (
        <Button variant="primary" size="lg" block onPress={reload} data-testid="reload">
          {t.reloadPage}
        </Button>
      ) : null}
      <LinkButton
        href="/"
        variant={reloadFirst ? 'secondary' : 'primary'}
        size="lg"
        block
        data-testid="to-start"
      >
        {t.toStart}
      </LinkButton>
    </>
  );
}

/** getUserMedia failed: what happened and how to allow the camera. */
export function CameraErrorScreen({ error }: { error: unknown }) {
  return (
    <Notice icon={CameraOff} title={CAMERA_ERROR_TITLE} data-testid="camera-error" actions={<Actions />}>
      <p>{cameraErrorMessage(error)}</p>
    </Notice>
  );
}

/** The device is banned: no camera, a way back to the start. */
export function BannedScreen() {
  return (
    <Notice icon={Ban} title={msg.bannedTitle} data-testid="banned" actions={<Actions reloadFirst={false} />}>
      <p>{msg.bannedText}</p>
    </Notice>
  );
}

/** The page could not start (identify or the filter list failed): never an endless spinner. */
export function FatalScreen({ error, fallback }: { error: unknown; fallback: string }) {
  const copy =
    isApiError(error) || (error instanceof Error && error.name === 'CameraError')
      ? fatalCopy(error)
      : { title: msg.failedTitle, text: fallback };
  const offline = isApiError(error) && error.code === 'network';
  return (
    <Notice
      icon={offline ? WifiOff : CircleAlert}
      title={copy.title}
      data-testid="fatal"
      actions={<Actions />}
    >
      <p>{copy.text}</p>
    </Notice>
  );
}
