/** Query keys of the poster section (under ['admin', …], so a stream resync refetches them). */
export const posterKey = ['admin', 'poster'] as const;
export const posterPdfKey = (sha: string) => ['admin', 'poster', 'pdf', sha] as const;
