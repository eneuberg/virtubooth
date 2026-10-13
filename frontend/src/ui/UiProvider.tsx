import type { ReactNode } from 'react';
import { I18nProvider, RouterProvider } from 'react-aria-components';

export interface UiProviderProps {
  children: ReactNode;
  /**
   * Client-side navigation for React Aria links (SidebarNav, BottomBar, LinkButton).
   * Pass wouter's navigate; without it links do full page loads.
   */
  navigate?: (path: string) => void;
  /** maps a router path to a real href (wouter base, e.g. "/admin") */
  useHref?: (href: string) => string;
}

/**
 * Wrap every app root in this. The build keeps only React Aria's de-DE strings
 * (@react-aria/optimize-locales-plugin), so the locale must be pinned: on an
 * English phone React Aria would otherwise look up en-US strings that are not there.
 */
export function UiProvider({ children, navigate, useHref }: UiProviderProps) {
  const content = <I18nProvider locale="de-DE">{children}</I18nProvider>;
  if (!navigate) return content;
  return (
    <RouterProvider navigate={navigate} {...(useHref ? { useHref } : {})}>
      {content}
    </RouterProvider>
  );
}
