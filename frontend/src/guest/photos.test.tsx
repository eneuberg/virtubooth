import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import type { GuestPhoto, MyPhotosResponse } from '@/api/types';
import type { OutboxEvent } from '@/sdk/outbox';
import { MY_PHOTOS_KEY, useMyPhotosSync } from './photos';

const listeners = vi.hoisted(() => new Set<(e: OutboxEvent) => void>());
vi.mock('@/sdk/outbox', () => ({
  subscribeOutboxEvents: (listener: (e: OutboxEvent) => void) => {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
}));

const photo = (id: string, seq: number): GuestPhoto => ({
  id,
  extension: 'beer',
  seq,
  created_at: '2026-10-13T20:00:00Z',
  width: 1080,
  height: 1440,
  url: `/media/${id}`,
  thumb_url: `/media/${id}?thumb=1`,
});

function sent(p: GuestPhoto): void {
  const event: OutboxEvent = {
    type: 'sent',
    item: {
      id: `shot-${p.id}`,
      ext: p.extension,
      meta: {},
      at: 0,
      blob: new Blob(),
      state: 'new',
      stored: true,
      resumed: false,
      error: null,
      waitUntil: 0,
    },
    result: { photo: p },
  };
  for (const listener of listeners) listener(event);
}

function setup(initial?: MyPhotosResponse) {
  const client = new QueryClient();
  if (initial) client.setQueryData(MY_PHOTOS_KEY, initial);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const hook = renderHook(() => useMyPhotosSync(), { wrapper });
  const ids = () => client.getQueryData<MyPhotosResponse>(MY_PHOTOS_KEY)?.photos.map((p) => p.id);
  return { client, hook, ids };
}

describe('"Deine Bilder" after a sent photo', () => {
  it('puts the new photo first and marks the list stale', () => {
    const { client, ids } = setup({ photos: [photo('old', 1)] });
    sent(photo('new', 2));
    expect(ids()).toEqual(['new', 'old']);
    expect(client.getQueryState(MY_PHOTOS_KEY)?.isInvalidated).toBe(true);
  });

  it('turns the empty list into one photo', () => {
    const { ids } = setup({ photos: [] });
    sent(photo('first', 1));
    expect(ids()).toEqual(['first']);
  });

  it('adds a photo only once', () => {
    const { ids } = setup({ photos: [photo('a', 1)] });
    sent(photo('a', 1));
    expect(ids()).toEqual(['a']);
  });

  it('leaves a list it never loaded to the first fetch', () => {
    const { ids } = setup();
    sent(photo('a', 1));
    expect(ids()).toBeUndefined();
  });

  it('stops listening when the app goes', () => {
    const { hook } = setup();
    expect(listeners.size).toBe(1);
    hook.unmount();
    expect(listeners.size).toBe(0);
  });
});
