import { QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { NEON_NACHT, type ThemeColors } from '@/styles/theme';
import { clearToasts, ToastSlot } from '@/ui/Toast';
import { UiProvider } from '@/ui/UiProvider';
import { bodyField, json, stubApi, testClient, type Route } from '../testing';
import { ThemeCard } from './ThemeCard';
import { themeKey, type AdminThemeOut } from './themeApi';

const KLASSISCH: ThemeColors = {
  background: '#2b0f0c',
  surface: '#3b1712',
  depth: '#1c0806',
  primary: '#ffa630',
  secondary: '#fbefe9',
  tertiary: '#c9b8b0',
  accent: '#ff7a66',
  highlight: '#ffbb5c',
  hit: '#84d49b',
  text: '#fbefe9',
  text_muted: '#c9b8b0',
};

const RUMMEL: ThemeColors = { ...NEON_NACHT, background: '#15123d', primary: '#ffd23f' };

function out(
  preset: 'neon_nacht' | 'klassisch' | 'rummel' | 'custom',
  colors: ThemeColors,
  custom = false,
  style: 'elegant' | 'goofy' = 'elegant',
): AdminThemeOut {
  return {
    theme: {
      preset,
      colors,
      style,
      on_primary: '#000000',
      on_accent: '#1b1b1a',
      primary_ink: '#cc4ffe',
      rev: custom ? 1 : 0,
      custom,
      updated_at: custom ? '2026-10-15T20:00:00Z' : null,
      by: custom ? 'admin:1' : null,
    },
    presets: [
      { id: 'neon_nacht', label: 'Neon Nacht', colors: NEON_NACHT, style: 'elegant' },
      { id: 'klassisch', label: 'Klassisch', colors: KLASSISCH, style: 'elegant' },
      { id: 'rummel', label: 'Rummel', colors: RUMMEL, style: 'goofy' },
    ],
  };
}

function renderCard(routes: Record<string, Route> = {}, data: AdminThemeOut = out('neon_nacht', NEON_NACHT)) {
  const qc = testClient();
  qc.setQueryData(themeKey, data);
  const requests = stubApi(routes);
  const view = render(
    <QueryClientProvider client={qc}>
      <UiProvider>
        <ThemeCard data={data} />
        <ToastSlot />
      </UiProvider>
    </QueryClientProvider>,
  );
  return { qc, requests, view };
}

const preview = () => screen.getByTestId('theme-preview');
const previewVar = (name: string) => preview().style.getPropertyValue(name);
const save = () => screen.getByTestId('theme-save');
const styleRadio = (name: string) => within(screen.getByTestId('theme-style')).getByRole('radio', { name });

afterEach(() => {
  act(() => clearToasts());
});

describe('ThemeCard (Erscheinungsbild)', () => {
  it('shows the saved theme in the preview; nothing to save yet', () => {
    renderCard();
    expect(screen.getByRole('heading', { name: 'Erscheinungsbild' })).toBeTruthy();
    expect(previewVar('--t-background')).toBe('#1b1b1a');
    expect(previewVar('--t-on-primary')).toBe('#000000');
    expect(save().hasAttribute('disabled') || save().getAttribute('data-disabled') !== null).toBe(true);
    // never saved: nothing to reset
    expect(screen.queryByTestId('theme-reset')).toBeNull();
  });

  it('a preset previews at once and saves as the preset', async () => {
    const { requests } = renderCard({
      'PUT /api/admin/theme': () => out('klassisch', KLASSISCH, true),
    });
    fireEvent.click(within(screen.getByTestId('theme-preset')).getByText('Klassisch'));
    expect(previewVar('--t-background')).toBe('#2b0f0c');
    expect(previewVar('--t-primary-ink')).toBe('#ffa630');
    fireEvent.click(save());
    await waitFor(() => expect(requests).toHaveLength(1));
    expect(await bodyField(requests[0]!, 'preset')).toBe('klassisch');
    expect(await bodyField(requests[0]!, 'colors')).toBeNull();
    await screen.findByText('Erscheinungsbild gespeichert.');
  });

  it('„Rummel“ brings the goofy style; the style can be switched on its own', async () => {
    const { requests } = renderCard({
      'PUT /api/admin/theme': () => out('rummel', RUMMEL, true, 'goofy'),
    });
    expect(styleRadio('Ruhig')).toHaveProperty('checked', true);
    fireEvent.click(within(screen.getByTestId('theme-preset')).getByText('Rummel'));
    expect(styleRadio('Verspielt')).toHaveProperty('checked', true);
    fireEvent.click(save());
    await waitFor(() => expect(requests).toHaveLength(1));
    expect(await bodyField(requests[0]!, 'preset')).toBe('rummel');
    expect(await bodyField(requests[0]!, 'style')).toBe('goofy');
  });

  it('only the style changed: still something to save', () => {
    renderCard();
    fireEvent.click(within(screen.getByTestId('theme-style')).getByText('Verspielt'));
    expect(save().getAttribute('data-disabled')).toBeNull();
  });

  it('an edited colour becomes „Eigene“ and is saved with all colours', async () => {
    const { requests } = renderCard({
      'PUT /api/admin/theme': () => out('custom', { ...NEON_NACHT, primary: '#22c55e' }, true),
    });
    fireEvent.change(screen.getByLabelText('Hauptfarbe'), { target: { value: '#22C55E' } });
    expect(previewVar('--t-primary')).toBe('#22c55e');
    const selected = within(screen.getByTestId('theme-preset')).getByRole('radio', { name: 'Eigene' });
    expect(selected).toHaveProperty('checked', true);
    fireEvent.click(save());
    await waitFor(() => expect(requests).toHaveLength(1));
    expect(await bodyField(requests[0]!, 'preset')).toBe('custom');
    expect(await bodyField(requests[0]!, 'colors')).toMatchObject({ primary: '#22c55e' });
  });

  it('warns about unreadable text before the server does', () => {
    renderCard();
    fireEvent.change(screen.getByLabelText('Text'), { target: { value: '#4a4a4a' } });
    const warning = screen.getByTestId('theme-contrast');
    expect(warning.textContent).toContain('Text auf Hintergrund ist schlecht lesbar');
    expect(save().getAttribute('data-disabled')).not.toBeNull();
  });

  it('shows the server’s error and resets to the default', async () => {
    const { requests } = renderCard(
      {
        'PUT /api/admin/theme': () =>
          json(400, { error: 'invalid_theme', message: 'Text auf Fläche ist schlecht lesbar.' }),
        'DELETE /api/admin/theme': () => out('neon_nacht', NEON_NACHT),
      },
      out('klassisch', KLASSISCH, true),
    );
    fireEvent.click(within(screen.getByTestId('theme-preset')).getByText('Neon Nacht'));
    fireEvent.click(save());
    expect((await screen.findByTestId('theme-error')).textContent).toBe(
      'Text auf Fläche ist schlecht lesbar.',
    );
    fireEvent.click(screen.getByTestId('theme-reset'));
    await waitFor(() => expect(requests.map((r) => r.method)).toEqual(['PUT', 'DELETE']));
    await screen.findByText('Erscheinungsbild zurückgesetzt.');
  });
});
