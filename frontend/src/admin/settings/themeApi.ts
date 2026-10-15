/**
 * Allgemeines → Erscheinungsbild: the theme of the guest UI and the Live Wall
 * (`/api/admin/theme`). Each write puts the server's answer into the cache.
 */
import { useQuery, type QueryClient } from '@tanstack/react-query';
import { api } from '@/api/client';
import type { AdminThemeOut } from '@/api/types';
import type { ThemeColors, ThemeStyle } from '@/styles/theme';
import { call } from '../store/api';

export type { AdminTheme, AdminThemeOut, ThemePreset } from '@/api/types';

/** under ['admin', …]: a `stream.resync` refetches it too */
export const themeKey = ['admin', 'theme'] as const;

export function useAdminTheme() {
  return useQuery({ queryKey: themeKey, queryFn: () => call(api.GET('/api/admin/theme')) });
}

export type ThemeChoice = 'neon_nacht' | 'klassisch' | 'rummel' | 'custom';

/** Save a preset (colors null) or own colours, and the style. 400 `invalid_theme` names
 * the pair. */
export async function saveTheme(
  qc: QueryClient,
  preset: ThemeChoice,
  colors: ThemeColors | null,
  style: ThemeStyle,
): Promise<AdminThemeOut> {
  const res = await call(api.PUT('/api/admin/theme', { body: { preset, colors, style } }));
  qc.setQueryData(themeKey, res);
  return res;
}

/** Back to the default („Neon Nacht“, style „Verspielt“). */
export async function resetTheme(qc: QueryClient): Promise<AdminThemeOut> {
  const res = await call(api.DELETE('/api/admin/theme'));
  qc.setQueryData(themeKey, res);
  return res;
}
