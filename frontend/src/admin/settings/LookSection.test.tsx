import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { NEON_NACHT } from '@/styles/theme';
import { UiProvider } from '@/ui/UiProvider';
import { json, stubApi, testClient, type Route } from '../testing';
import { LookSection } from './LookSection';
import type { AdminThemeOut } from './themeApi';

const THEME: AdminThemeOut = {
  theme: {
    preset: 'neon_nacht',
    colors: NEON_NACHT,
    style: 'goofy',
    on_primary: '#000000',
    on_accent: '#1b1b1a',
    primary_ink: '#cc4ffe',
    rev: 0,
    custom: false,
    updated_at: null,
    by: null,
  },
  presets: [{ id: 'neon_nacht', label: 'Neon Nacht', colors: NEON_NACHT, style: 'goofy' }],
};

function renderSection(theme: Route) {
  stubApi({ 'GET /api/admin/theme': theme });
  render(
    <QueryClientProvider client={testClient()}>
      <UiProvider>
        <LookSection />
      </UiProvider>
    </QueryClientProvider>,
  );
}

describe('Erscheinungsbild (its own section)', () => {
  it('shows the theme card under its own heading', async () => {
    renderSection(() => THEME);
    expect(screen.getByRole('heading', { level: 1, name: 'Erscheinungsbild' })).toBeTruthy();
    expect(await screen.findByTestId('settings-theme')).toBeTruthy();
    expect(screen.getByRole('heading', { level: 2, name: 'Farben und Stil' })).toBeTruthy();
    expect(screen.getByRole('radio', { name: 'Neon Nacht' })).toHaveProperty('checked', true);
  });

  it('offers a retry when the theme cannot be loaded', async () => {
    renderSection(() => json(500, { error: 'internal', message: 'Kaputt.' }));
    expect(await screen.findByText('Das Erscheinungsbild ist gerade nicht erreichbar')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Erneut laden' })).toBeTruthy();
  });
});
