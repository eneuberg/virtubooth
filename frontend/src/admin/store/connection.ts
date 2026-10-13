/**
 * The admin's realtime connection, for the ConnectionIndicator in every header.
 * Written by useAdminEvents only.
 */
import { create } from 'zustand';
import type { ConnectionStatus } from '@/ui/ConnectionIndicator';

interface ConnectionStore {
  status: ConnectionStatus;
  setStatus: (status: ConnectionStatus) => void;
}

export const useConnection = create<ConnectionStore>((set) => ({
  status: 'connecting',
  setStatus: (status) => set({ status }),
}));
