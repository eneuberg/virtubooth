import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ApiError } from '@/api/errors';
import { msg } from '@/lib/messages.de';
import { UploadState, type UploadStateProps } from './UploadState';
import type { ShotStatus } from './useShot';

function shot(status: ShotStatus, error: ApiError | null = null, stored = true): UploadStateProps['shot'] {
  return { status, error, stored };
}

function offline(): ApiError {
  const err = new ApiError(0, 'network', msg.uploadOffline);
  err.offline = true;
  return err;
}

function view(props: Partial<UploadStateProps> & Pick<UploadStateProps, 'shot'>) {
  render(<UploadState waitSeconds={0} {...props} />);
  const region = screen.getByRole('status');
  return { region, title: screen.getByTestId('upload-title').textContent };
}

describe('UploadState: the result headline is the upload state', () => {
  it('says „Wird hochgeladen…“ in a polite live region while the upload runs', () => {
    const { region, title } = view({ shot: shot('uploading') });
    expect(title).toBe('Wird hochgeladen…');
    expect(region.dataset['state']).toBe('uploading');
    // <output> is a polite live region (role status); the state is words, not a colour
    expect(region.tagName).toBe('OUTPUT');
    expect(region.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true');
    expect(region.textContent).not.toMatch(/%/); // the percentage lives on the film edge
  });

  it('says „Hochgeladen“ with the line underneath once the server has it', () => {
    const { region, title } = view({ shot: shot('done'), done: 'Fertig, mehr musst du nicht tun.' });
    expect(title).toBe('Hochgeladen');
    expect(region.dataset['state']).toBe('done');
    expect(region.textContent).toContain('Fertig, mehr musst du nicht tun.');
  });

  it('keeps an offline photo and says it is sent later', () => {
    const { region, title } = view({ shot: shot('waiting', offline()) });
    expect(title).toBe('Noch nicht hochgeladen');
    expect(region.textContent).toContain('Keine Verbindung.');
    expect(region.textContent).toContain('Es wird gesendet, sobald es geht.');
    expect(region.textContent).not.toContain('Seite offen');
  });

  it('asks to keep the page open when the photo is only in memory', () => {
    const { region } = view({ shot: shot('waiting', offline(), false) });
    expect(region.textContent).toContain('Lass die Seite offen, bis es hochgeladen ist.');
  });

  it('counts down a rate limit', () => {
    const { region } = view({
      shot: shot('waiting', new ApiError(429, 'rate_limited', 'x')),
      waitSeconds: 4,
    });
    expect(region.textContent).toContain('Zu viele Fotos auf einmal. In 4 s nochmal.');
  });

  it('passes the server’s words on for a full disk (storage_full waits in the outbox)', () => {
    const err = new ApiError(503, 'storage_full', 'Der Speicher der Party ist voll.');
    const { region, title } = view({ shot: shot('waiting', err) });
    expect(title).toBe('Noch nicht hochgeladen');
    expect(region.textContent).toContain(
      'Der Speicher der Party ist voll. Es wird gesendet, sobald es geht.',
    );
  });

  it('holds a photo while uploads are paused, in the Beer Cam’s words', () => {
    const { region, title } = view({
      shot: shot('held', new ApiError(403, 'uploads_paused', 'x')),
      verb: 'gezählt',
    });
    expect(title).toBe('Noch nicht hochgeladen');
    expect(region.dataset['state']).toBe('held');
    expect(region.textContent).toContain(msg.pausedText);
    expect(region.textContent).toContain('Es wird gezählt, sobald du wieder hochladen kannst.');
  });

  it('holds a photo over the photo limit', () => {
    const err = new ApiError(
      403,
      'photo_limit',
      'Du hast schon 200 Fotos. Lösch ein paar, dann geht’s weiter.',
    );
    const { region } = view({ shot: shot('held', err) });
    expect(region.textContent).toContain('Du hast schon 200 Fotos.');
    expect(region.textContent).toContain('sobald du wieder hochladen kannst');
  });

  it('says „Nicht hochgeladen“ for a refusal and that the photo can still be kept', () => {
    const err = new ApiError(422, 'invalid_image', 'Das Bild ist kaputt.');
    const { region, title } = view({ shot: shot('failed', err), failedHint: 'Herunterladen geht trotzdem.' });
    expect(title).toBe('Nicht hochgeladen');
    expect(region.dataset['state']).toBe('failed');
    expect(region.textContent).toContain('Das Bild ist kaputt. Herunterladen geht trotzdem.');
  });
});
