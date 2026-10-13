/**
 * Keeps the admin's query cache live through the event stream (stream.ts). Mount once
 * per signed-in page (AdminFrame); the login page does without.
 */
import { useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { openAdminEvents } from '@/api/events';
import { goLogin } from '../lib/nav';
import { fetchSession } from './api';
import { useConnection } from './connection';
import { onCursor, streamCursor } from './cursor';
import { startAdminEvents } from './stream';

export function useAdminEvents(): void {
  const qc = useQueryClient();
  useEffect(
    () =>
      startAdminEvents(qc, {
        open: openAdminEvents,
        checkSession: fetchSession,
        onLoggedOut: goLogin,
        setStatus: (status) => useConnection.getState().setStatus(status),
        cursor: streamCursor,
        onCursor,
      }),
    [qc],
  );
}
