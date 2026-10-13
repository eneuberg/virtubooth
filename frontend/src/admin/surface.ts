import { useEffect } from 'react';
import type { SurfaceTone } from '@/ui/Surface';

const THEME_COLOR: Record<SurfaceTone, string> = { dark: '#2b0f0c', light: '#f4f6f8' };

/**
 * Sets the page surface for an admin area: live (and login) on dark Rotlicht so the
 * host is not blinded at the party, manage and the user page on the light Leuchttisch.
 * Also updates <meta name="theme-color">. OWNER: wave 2 "AD".
 */
export function useDocumentSurface(tone: SurfaceTone): void {
  useEffect(() => {
    document.documentElement.dataset['surface'] = tone;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLOR[tone]);
  }, [tone]);
}
