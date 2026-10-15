import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ConsentInfo } from '@/api/types';
import { UiProvider } from '@/ui/UiProvider';
import { splitParagraphs, splitPrompt, tidy } from './copy';
import { JoinSheet, SCAN_COUNT_NOTE } from './JoinSheet';

vi.mock('@/sdk/device', () => ({
  getDeviceTraits: () => Promise.resolve({ hash: 'ab'.repeat(32), components: {} }),
}));

const join: ConsentInfo = {
  version: '1',
  title: 'Willkommen bei Lenas Geburtstag! 🎉',
  paragraphs: [
    "Kurz bevor's losgeht: Wenn du hier Fotos machst, speichern wir sie und dürfen sie auf Instagram (@lenas.party) posten.",
    'Damit wir Missbrauch verhindern können, erkennt die Seite dein Gerät wieder.',
    'Wenn du das nicht möchtest, nutze die Fotobox bitte nicht.',
  ],
  instagram_prompt: 'Dein Instagram (freiwillig). Dann markieren wir dich!',
  accept_label: "Alles klar, los geht's! 🍻",
  party_name: 'Lenas Geburtstag',
  instagram_account: '@lenas.party',
  analysis: false,
};

function renderSheet(destination: string | null = 'Beer Cam', texts: ConsentInfo = join) {
  render(
    <UiProvider>
      <JoinSheet join={texts} destination={destination} />
    </UiProvider>,
  );
  return screen.getByRole('dialog');
}

describe('JoinSheet', () => {
  it('has exactly one action, and no way to dismiss it', () => {
    const dialog = renderSheet();
    const buttons = within(dialog).getAllByRole('button');
    const actions = buttons.filter((b) => !b.hasAttribute('aria-expanded'));
    expect(actions).toHaveLength(1);
    expect(actions[0]?.getAttribute('type')).toBe('submit');
    expect(actions[0]?.textContent).toBe('Alles klar, los geht’s!');
    expect(within(dialog).queryByRole('button', { name: 'Schließen' })).toBeNull();
    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(screen.getByRole('dialog')).toBeTruthy();
  });

  it('shows the server texts typeset: no emoji, lead up front, details behind "Mehr dazu"', () => {
    const dialog = renderSheet();
    expect(within(dialog).getByRole('heading', { level: 2 }).textContent).toBe(
      'Willkommen bei Lenas Geburtstag!',
    );
    expect(dialog.textContent).toContain('Kurz bevor’s losgeht');
    expect(dialog.textContent).toContain('nutze die Fotobox bitte nicht');
    const more = within(dialog).getByRole('button', { name: 'Mehr dazu' });
    expect(more.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(more);
    expect(dialog.textContent).toContain(SCAN_COUNT_NOTE);
    expect(dialog.textContent).toContain('Danach öffnet sich „Beer Cam“.');
  });

  it('offers „Meine Fotos nicht automatisch auswerten“ under "Mehr dazu" only with the analysis', () => {
    const dialog = renderSheet(null, { ...join, analysis: true });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Mehr dazu' }));
    const optOut = within(dialog).getByRole('switch', { name: /Meine Fotos nicht automatisch auswerten/ });
    expect(optOut).toHaveProperty('checked', false);
    expect(dialog.querySelector('[data-testid=analysis-opt-out]')).toBeTruthy();
  });

  it('has no analysis switch without the analysis', () => {
    const dialog = renderSheet(null);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Mehr dazu' }));
    expect(within(dialog).queryByRole('switch')).toBeNull();
  });

  it('labels the field with the prompt and keeps the rest as help', () => {
    const dialog = renderSheet(null);
    const field = within(dialog).getByRole('textbox', { name: 'Dein Instagram (freiwillig)' });
    expect(field.getAttribute('maxlength')).toBe('30');
    expect(dialog.textContent).toContain('Dann markieren wir dich!');
    expect(dialog.textContent).not.toContain('Danach öffnet sich');
  });

  it('uses only blocker-neutral names', () => {
    renderSheet();
    const scrim = document.querySelector('[data-testid=join]');
    expect(scrim?.classList.contains('vb-scrim')).toBe(true);
    expect(scrim?.querySelector('.vb-sheet')).toBeTruthy();
    const names = [...(scrim?.querySelectorAll('*') ?? [])].flatMap((el) =>
      ['class', 'id', 'data-testid', 'aria-labelledby', 'for', 'name'].map((a) => el.getAttribute(a) ?? ''),
    );
    for (const word of [
      'consent',
      'cookie',
      'gdpr',
      'banner',
      'notice',
      'modal',
      'backdrop',
      'privacy',
      'popup',
    ]) {
      expect(names.filter((n) => n.toLowerCase().includes(word))).toEqual([]);
    }
  });
});

describe('copy', () => {
  it('tidy drops emoji and sets apostrophes', () => {
    expect(tidy("Alles klar, los geht's! 🍻")).toBe('Alles klar, los geht’s!');
    expect(tidy('Willkommen bei X! 🎉')).toBe('Willkommen bei X!');
    expect(tidy('Ein 👨‍👩‍👧 Test')).toBe('Ein Test');
  });

  it('splits paragraphs into lead and details', () => {
    expect(splitParagraphs(['a', 'b', 'c', 'd'])).toEqual({ lead: ['a', 'd'], more: ['b', 'c'] });
    expect(splitParagraphs(['a', 'b'])).toEqual({ lead: ['a', 'b'], more: [] });
  });

  it('splits the prompt into a label and help', () => {
    expect(splitPrompt('Instagram-Name (freiwillig). Dann können wir dich markieren.')).toEqual({
      label: 'Instagram-Name (freiwillig)',
      help: 'Dann können wir dich markieren.',
    });
    expect(splitPrompt('Instagram (freiwillig)')).toEqual({ label: 'Instagram (freiwillig)', help: null });
  });
});
