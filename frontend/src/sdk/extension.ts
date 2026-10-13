/**
 * The frontend side of an extension (an "activity" such as the Beer Cam).
 * OWNER: wave 2 "AC". Each folder src/extensions/<id>/ has an index.ts that default-
 * exports defineExtension({...}); src/extensions/registry.ts collects them at build
 * time. The server decides which are enabled (GET /api/extensions); the guest app
 * renders the intersection. A contract test (wave 2/3) asserts the ids match the
 * backend's extensions.
 *
 * An extension brings everything of its own: the page (`load`) and, optionally, the
 * live line on its strip on Start (`card`). Both load lazily, so the guest app's first
 * chunk only carries these small definitions.
 */
import type { ComponentType } from 'react';

export interface ExtensionPageProps {
  /** the extension id from the URL (/x/<id>/) */
  id: string;
}

export interface ExtensionCardProps {
  /** the extension id */
  id: string;
}

export interface ExtensionModule {
  /** ^[a-z][a-z0-9-]{1,30}$, equal to the backend extension id and the folder name */
  id: string;
  /** the page under /x/<id>/*, loaded lazily (one chunk per activity, ≤ 60 KB gzip) */
  load: () => Promise<{ default: ComponentType<ExtensionPageProps> }>;
  /**
   * The live line on the activity's strip on Start, under the title and tagline: a
   * counter, sample frames (a phrasing element: it sits inside the strip's link).
   * Loaded lazily, Start shows a placeholder line meanwhile. Without it the strip
   * shows the tagline only.
   */
  card?: () => Promise<{ default: ComponentType<ExtensionCardProps> }>;
}

export function defineExtension(module: ExtensionModule): ExtensionModule {
  return module;
}
