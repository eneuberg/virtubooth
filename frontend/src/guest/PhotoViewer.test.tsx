import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { GuestPhoto } from '@/api/types';
import { useGuestShowFilter } from '@/lib/photoFilter';
import { UiProvider } from '@/ui/UiProvider';
import { PhotoViewer } from './PhotoViewer';

const share = vi.hoisted(() => ({
  saveImage: vi.fn<(blob: Blob, name: string) => Promise<'shared' | 'downloaded' | 'cancelled'>>(),
}));
vi.mock('@/sdk/share', () => ({
  canShareFiles: () => false,
  saveImage: share.saveImage,
  shareImage: vi.fn<() => Promise<'shared'>>(),
}));
const toast = vi.hoisted(() => vi.fn<(options: { tone: string; message: string }) => void>());
vi.mock('@/ui/Toast', () => ({ showToast: toast }));

const photo: GuestPhoto = {
  id: 'p1',
  extension: 'booth',
  seq: 7,
  created_at: '2026-10-13T20:00:00Z',
  width: 1080,
  height: 1440,
  url: '/media/p1',
  thumb_url: '/media/p1?thumb=1',
  raw_url: null,
  raw_thumb_url: null,
};

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <UiProvider>{children}</UiProvider>
    </QueryClientProvider>
  );
}

afterEach(() => {
  useGuestShowFilter.getState().setShow(true);
  localStorage.clear();
  vi.unstubAllGlobals();
  share.saveImage.mockReset();
  toast.mockReset();
});

describe('PhotoViewer', () => {
  it('offers „Herunterladen“ (not „Speichern“) and confirms a download with „Heruntergeladen“', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response(new Blob(['jpeg'], { type: 'image/jpeg' })))),
    );
    share.saveImage.mockResolvedValue('downloaded');
    render(<PhotoViewer photos={[photo]} index={0} onIndexChange={() => undefined} />, { wrapper });
    const button = await screen.findByRole('button', { name: 'Herunterladen' });
    expect(screen.queryByRole('button', { name: 'Speichern' })).toBeNull();
    await waitFor(() => expect(button.hasAttribute('data-pending')).toBe(false));
    fireEvent.click(button);
    await waitFor(() => expect(toast).toHaveBeenCalledWith({ tone: 'success', message: 'Heruntergeladen' }));
    expect(share.saveImage.mock.calls[0]?.[1]).toMatch(/\.jpg$/);
  });

  it('„Filter zeigen“ switches to the original, and „Herunterladen“ then saves that', async () => {
    const fetched: string[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        fetched.push(url);
        return Promise.resolve(new Response(new Blob(['jpeg'], { type: 'image/jpeg' })));
      }),
    );
    share.saveImage.mockResolvedValue('downloaded');
    const withRaw: GuestPhoto = {
      ...photo,
      raw_url: '/media/p1?variant=raw',
      raw_thumb_url: '/media/p1?variant=raw&thumb=1',
      meta: { filter: 'thermal', facing: 'user' },
    };
    render(<PhotoViewer photos={[withRaw]} index={0} onIndexChange={() => undefined} />, { wrapper });
    const img = await screen.findByTestId('photo-viewer-img');
    expect(img.getAttribute('src')).toBe('/media/p1');
    const toggle = screen.getByRole('switch', { name: /Filter zeigen/ });
    expect(toggle).toHaveProperty('checked', true);
    fireEvent.click(toggle);
    await waitFor(() =>
      expect(screen.getByTestId('photo-viewer-img').getAttribute('src')).toBe('/media/p1?variant=raw'),
    );
    expect(localStorage.getItem('vb.guest.photos.filter')).toBe('off');
    const button = screen.getByRole('button', { name: 'Herunterladen' });
    await waitFor(() => expect(button.hasAttribute('data-pending')).toBe(false));
    fireEvent.click(button);
    await waitFor(() => expect(share.saveImage).toHaveBeenCalled());
    expect(share.saveImage.mock.calls[0]?.[1]).toBe('booth-00007-original.jpg');
    expect(fetched).toContain('/media/p1?variant=raw');
  });

  it('shows the switch disabled, with the reason, for a photo without an original', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response(new Blob(['jpeg'], { type: 'image/jpeg' })))),
    );
    const old: GuestPhoto = { ...photo, meta: { filter: 'thermal', facing: 'user' } };
    render(<PhotoViewer photos={[old]} index={0} onIndexChange={() => undefined} />, { wrapper });
    const toggle = await screen.findByRole('switch', { name: /Filter zeigen/ });
    expect(toggle).toHaveProperty('disabled', true);
    expect(screen.getByText(/Kein Original ohne Filter gespeichert/)).toBeTruthy();
  });

  it('has no switch for photos without a filter choice (Beer Cam)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response(new Blob(['jpeg'], { type: 'image/jpeg' })))),
    );
    render(
      <PhotoViewer
        photos={[{ ...photo, extension: 'beer', meta: { vessel: 'cup' } }]}
        index={0}
        onIndexChange={() => undefined}
      />,
      {
        wrapper,
      },
    );
    await screen.findByTestId('photo-viewer-img');
    expect(screen.queryByRole('switch', { name: /Filter zeigen/ })).toBeNull();
  });
});
