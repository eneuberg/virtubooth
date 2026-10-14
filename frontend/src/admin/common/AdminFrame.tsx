import type { ReactNode } from 'react';
import { ToastSlot } from '@/ui/Toast';
import { useAdminEvents } from '../store/useAdminEvents';
import { UploadControlsSheet } from '../uploads/UploadControlsSheet';

/**
 * Every signed-in admin page: the live event stream, the upload controls sheet and the
 * one toast slot (placed by the page: above the bottom bar, or bottom right on desktop).
 */
export function AdminFrame({ children, toastClassName }: { children: ReactNode; toastClassName?: string }) {
  useAdminEvents();
  return (
    <>
      {children}
      <UploadControlsSheet />
      <ToastSlot className={toastClassName} reserveRoom />
    </>
  );
}
