/**
 * Build-time registry of the frontend extensions (stack.md "Frontend extensions").
 * Every src/extensions/<id>/index.ts default-exports defineExtension({ id, load }).
 * The server says which are enabled (GET /api/extensions); the guest app renders the
 * intersection. OWNER: wave 2 "AC".
 */
import type { ExtensionModule } from '@/sdk/extension';

const modules = import.meta.glob<{ default: ExtensionModule }>('./*/index.ts', { eager: true });

const byId = new Map<string, ExtensionModule>();
for (const [path, mod] of Object.entries(modules)) {
  const folder = /^\.\/([^/]+)\/index\.ts$/.exec(path)?.[1];
  if (folder !== mod.default.id) {
    throw new Error(`extension folder ${String(folder)} declares id ${mod.default.id}`);
  }
  byId.set(mod.default.id, mod.default);
}

export function listExtensions(): ExtensionModule[] {
  return [...byId.values()];
}

export function getExtension(id: string): ExtensionModule | undefined {
  return byId.get(id);
}
