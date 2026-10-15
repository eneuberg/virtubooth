import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { AdminPhoto } from '@/api/types';
import { useAdminShowFilter } from '@/lib/photoFilter';
import { UiProvider } from '@/ui/UiProvider';
import { ContactSheet } from '../manage/ContactSheet';
import { FilterToggle } from './FilterToggle';

function photo(n: number, raw: boolean, meta: AdminPhoto['meta'] = { filter: 'thermal' }): AdminPhoto {
  const id = `photo000${n}`;
  return {
    id,
    extension: 'booth',
    seq: n,
    created_at: '2026-10-13T20:00:00.000+00:00',
    width: 1080,
    height: 1440,
    bytes: 1,
    meta,
    hidden: false,
    hidden_at: null,
    hidden_reason: null,
    deleted: false,
    url: `/media/${id}`,
    thumb_url: `/media/${id}?thumb=1`,
    raw_url: raw ? `/media/${id}?variant=raw` : null,
    raw_thumb_url: raw ? `/media/${id}?variant=raw&thumb=1` : null,
    user: {
      id: 1,
      name: 'Ente',
      instagram: null,
      banned: false,
      auto_banned: false,
      uploads_paused: false,
      is_host: false,
    },
  };
}

const noop = () => undefined;
const srcs = () => [...document.querySelectorAll('img')].map((img) => img.getAttribute('src'));

afterEach(() => {
  act(() => useAdminShowFilter.getState().setShow(true));
  localStorage.clear();
});

describe('„Filter zeigen“ in the admin', () => {
  it('is on by default; off shows the originals in the contact sheet, remembered', () => {
    const photos = [photo(2, true), photo(1, false)];
    render(
      <UiProvider>
        <FilterToggle />
        <ContactSheet
          photos={photos}
          selected={new Set()}
          currentId={null}
          onSelectionChange={noop}
          onOpen={noop}
          onToggleHidden={noop}
          onDelete={noop}
        />
      </UiProvider>,
    );
    expect(srcs()).toEqual(['/media/photo0002?thumb=1', '/media/photo0001?thumb=1']);
    const toggle = screen.getByRole('switch', { name: 'Filter zeigen' });
    expect(toggle).toHaveProperty('checked', true);
    fireEvent.click(toggle);
    // the photo without an original keeps its one file
    expect(srcs()).toEqual(['/media/photo0002?variant=raw&thumb=1', '/media/photo0001?thumb=1']);
    expect(localStorage.getItem('vb.admin.photos.filter')).toBe('off');
  });

  it('a photo without an original: disabled, with the reason', () => {
    render(
      <UiProvider>
        <FilterToggle photo={photo(1, false)} />
      </UiProvider>,
    );
    const toggle = screen.getByRole('switch', { name: /Filter zeigen/ });
    expect(toggle).toHaveProperty('disabled', true);
    expect(toggle).toHaveProperty('checked', true);
    expect(screen.getByText(/vor dem Update aufgenommen/)).toBeTruthy();
  });
});
