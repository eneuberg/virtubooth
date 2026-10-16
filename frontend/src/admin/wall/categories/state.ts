/**
 * A category's state in words (the card, the Live screen's opened category): why the
 * app switched it off (lifecycle.REASON_TEXT), whether the banner may switch it back on,
 * and the link into its editor.
 */
import type { CategoryItem, OffReason } from '../types';

/** Why the app switched a category off. */
export function offReasonText(reason: OffReason, detail: string | null): string {
  const name = `„${detail ?? '?'}“`;
  switch (reason) {
    case 'ai_off':
      return 'Externe KI ist aus.';
    case 'property_trashed':
      return `Die Eigenschaft ${name} liegt im Papierkorb.`;
    case 'property_missing':
      return `Die Eigenschaft ${name} gibt es nicht.`;
    default:
      return `Die Eigenschaft ${name} war bei der Umstellung inaktiv.`;
  }
}

/** Switched off by the app, and nothing stops it any more: the banner offers it (§8.1). */
export const canComeBack = (c: CategoryItem) => !c.enabled && c.off_reason !== null && c.locked === null;

/** „an“, „aus“, „gesperrt: …“, „automatisch aus: …“ */
export function categoryState(item: CategoryItem): { text: string; tone: 'on' | 'off' | 'locked' } {
  if (item.enabled) return { text: 'an', tone: 'on' };
  if (item.locked) return { text: `gesperrt: ${item.locked.message}`, tone: 'locked' };
  if (item.off_reason)
    return { text: `automatisch aus: ${offReasonText(item.off_reason, item.off_detail)}`, tone: 'off' };
  return { text: 'aus', tone: 'off' };
}

/** The Live screen's link into the editor (CategoriesCard opens `?category=`). */
export function editorHref(id: string): string {
  return `/manage?tab=livewall&category=${encodeURIComponent(id)}`;
}
