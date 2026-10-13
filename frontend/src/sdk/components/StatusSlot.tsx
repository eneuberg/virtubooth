/**
 * The one place for exceptional guest states (UX audit §5): "Hochladen pausiert",
 * "Hochladen kurz angehalten", "Offline", "1 Foto wartet". Never a floating chip.
 * Rendered inside/next to the guest pass; tap explains (sheet). OWNER: wave 2 "GP".
 */

export interface StatusSlotProps {
  className?: string;
}

export function StatusSlot({ className }: StatusSlotProps) {
  // TODO(wave 2, GP): session (paused/stopped/banned), navigator.onLine, useOutbox().pending
  void className;
  return null;
}
