import { defineExtension } from '@/sdk/extension';

/** Fotobox: selfie with filters and countdown. OWNER: wave 2 "AC". */
export default defineExtension({ id: 'booth', load: () => import('./BoothPage') });
