import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AdminPhoto } from '@/api/types';
import { UiProvider } from '@/ui/UiProvider';
import { HideToggle } from '../common/HideToggle';
import { must } from '../testing';
import { ContactSheet } from './ContactSheet';

function photo(n: number, over: Partial<AdminPhoto> = {}): AdminPhoto {
  const id = `photo000${n}`;
  return {
    id,
    extension: 'booth',
    seq: n,
    created_at: `2026-10-13T20:0${n}:00.000+00:00`,
    width: 1080,
    height: 1440,
    bytes: 1,
    meta: {},
    hidden: false,
    hidden_at: null,
    hidden_reason: null,
    deleted: false,
    url: `/media/${id}`,
    thumb_url: `/media/${id}?thumb=1`,
    user: {
      id: 1,
      name: 'Ente',
      instagram: null,
      banned: false,
      auto_banned: false,
      uploads_paused: false,
      is_host: false,
    },
    ...over,
  };
}

const PHOTOS = [photo(3), photo(2, { hidden: true, hidden_reason: 'admin' }), photo(1)];

function renderSheet(selected: ReadonlySet<string> = new Set()) {
  const props = {
    onSelectionChange: vi.fn<(ids: Set<string>) => void>(),
    onOpen: vi.fn<(photo: AdminPhoto) => void>(),
    onToggleHidden: vi.fn<(photo: AdminPhoto) => void>(),
    onDelete: vi.fn<(photos: AdminPhoto[]) => void>(),
  };
  render(
    <UiProvider>
      <ContactSheet photos={PHOTOS} selected={selected} currentId={null} {...props} />
    </UiProvider>,
  );
  return props;
}

describe('ContactSheet', () => {
  it('is a grid of frames with the grease X on hidden ones', () => {
    renderSheet();
    const grid = screen.getByRole('grid', { name: 'Kontaktbogen' });
    const rows = within(grid).getAllByRole('row');
    expect(rows).toHaveLength(3);
    expect(rows[1]?.getAttribute('data-hidden')).toBe('true');
    expect(rows[1]?.textContent).toContain('Ausgeblendet');
    expect(rows[0]?.textContent).toContain('Foto 0003');
  });

  it('selects with the checkbox', () => {
    const props = renderSheet();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Auswählen Foto\u00a00002' }));
    expect(props.onSelectionChange).toHaveBeenCalledWith(new Set(['photo0002']));
  });

  it('X hides the focused frame, Entf deletes the selection (after asking)', () => {
    const props = renderSheet(new Set(['photo0001', 'photo0003']));
    const rows = screen.getAllByRole('row');
    fireEvent.keyDown(must(rows[1]), { key: 'x' });
    expect(props.onToggleHidden).toHaveBeenCalledWith(PHOTOS[1]);
    fireEvent.keyDown(must(rows[1]), { key: 'Delete' });
    expect(props.onDelete).toHaveBeenCalledWith([PHOTOS[0], PHOTOS[2]]);
  });
});

describe('HideToggle', () => {
  it('names what pressing does and shows the state', () => {
    const onToggle = vi.fn<() => void>();
    const { rerender } = render(<HideToggle photo={must(PHOTOS[0])} onToggle={onToggle} />);
    const button = screen.getByRole('button', { name: 'Foto 0003 ausblenden' });
    expect(button.getAttribute('data-action')).toBe('hide');
    fireEvent.click(button);
    expect(onToggle).toHaveBeenCalled();
    rerender(<HideToggle photo={must(PHOTOS[1])} onToggle={onToggle} />);
    expect(screen.getByRole('button', { name: 'Foto 0002 einblenden' }).getAttribute('data-action')).toBe(
      'unhide',
    );
  });
});
