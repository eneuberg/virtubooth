import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { GuestPhoto } from '@/api/types';
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
});
