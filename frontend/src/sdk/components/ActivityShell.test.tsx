import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { UiProvider } from '@/ui/UiProvider';
import { ActivityShell } from './ActivityShell';

describe('ActivityShell', () => {
  it('lays out the slots of a camera page', () => {
    render(
      <ActivityShell
        heading="Beer Cam"
        title={<span>Beer Cam ▾</span>}
        topRight={<span data-testid="pass">Ente</span>}
        stageTestId="frame"
        stage={<div data-testid="stage-content" />}
        filmEdge={<div data-testid="film" />}
        hint={<p>Halte die Flasche in den Umriss.</p>}
        controls={
          <>
            <button type="button">links</button>
            <button type="button">Auslöser</button>
            <button type="button">rechts</button>
          </>
        }
        rootProps={{ 'data-testid': 'root', 'data-state': 'camera' }}
      />,
      { wrapper: UiProvider },
    );
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Beer Cam');
    expect(screen.getByTestId('back').getAttribute('href')).toBe('/');
    expect(screen.getByTestId('back').getAttribute('aria-label')).toBe('Zurück zum Start');
    expect(screen.getByTestId('frame').contains(screen.getByTestId('stage-content'))).toBe(true);
    expect(screen.getByTestId('root').dataset['state']).toBe('camera');
    expect(screen.getByTestId('root').dataset['surface']).toBe('dark');
    expect(screen.getAllByTestId('film')).toHaveLength(1); // one film edge, never a copy
    expect(screen.getByText('Halte die Flasche in den Umriss.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Auslöser' })).toBeTruthy();
    // the single toast slot belongs to the shell
    expect(document.querySelectorAll('[role="region"]').length).toBeLessThanOrEqual(1);
  });

  it('leaves out an empty hint', () => {
    render(<ActivityShell heading="Fotobox" title="Fotobox" stage={null} controls={<span />} />, {
      wrapper: UiProvider,
    });
    expect(screen.queryByTestId('hint-row')).toBeNull();
  });
});
