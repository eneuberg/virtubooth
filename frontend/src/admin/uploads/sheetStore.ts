/** Whether the upload controls sheet is open (opened from the pill and the bottom bar). */
import { create } from 'zustand';

interface UploadSheetStore {
  isOpen: boolean;
  setOpen: (isOpen: boolean) => void;
}

export const useUploadSheet = create<UploadSheetStore>((set) => ({
  isOpen: false,
  setOpen: (isOpen) => set({ isOpen }),
}));

export function openUploadSheet(): void {
  useUploadSheet.getState().setOpen(true);
}
