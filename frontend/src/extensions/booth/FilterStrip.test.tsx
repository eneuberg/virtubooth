import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Filter } from '@/sdk/camera/filters';
import { UiProvider } from '@/ui/UiProvider';
import { FilterStrip } from './FilterStrip';

const filter = (id: string, name: string, icon: string): Filter => ({ id, name, icon, glsl: '' });
const FILTERS = [
  filter('normal', 'Normal', '✨'),
  filter('bw', 'Schwarz-Weiß', '🖤'),
  filter('neon', 'Neon', '💜'),
];

describe('FilterStrip', () => {
  it('shows a swatch when it is there, a quiet placeholder while it is made, the icon when it failed', () => {
    render(
      <UiProvider>
        <FilterStrip
          filters={FILTERS}
          selectedId="normal"
          onSelect={() => undefined}
          swatches={
            new Map<string, string | null>([
              ['normal', 'blob:normal'],
              ['bw', null],
            ])
          }
        />
      </UiProvider>,
    );
    expect(screen.getByTestId('filter-normal').querySelector('img')?.getAttribute('src')).toBe('blob:normal');
    expect(screen.getByTestId('filter-bw').textContent).toContain('🖤');
    const pending = screen.getByTestId('filter-neon');
    // no emoji while the swatch is being made
    expect(pending.textContent).toBe('Neon');
    expect(pending.querySelector('[data-testid=filter-swatch-pending]')).not.toBeNull();
  });
});
