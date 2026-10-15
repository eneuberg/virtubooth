/** Query keys of the Live Wall admin, all under ['admin', 'wall', …] (a resync clears them too). */
export const wk = {
  all: ['admin', 'wall'] as const,
  config: ['admin', 'wall', 'config'] as const,
  categories: ['admin', 'wall', 'categories'] as const,
  analysis: ['admin', 'wall', 'analysis'] as const,
  values: ['admin', 'wall', 'values'] as const,
  llm: ['admin', 'wall', 'llm'] as const,
  properties: ['admin', 'wall', 'llm', 'properties'] as const,
  photoAnalysis: (id: string) => ['admin', 'wall', 'photo-analysis', id] as const,
};
