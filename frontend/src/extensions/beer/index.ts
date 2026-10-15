import { defineExtension } from '@/sdk/extension';

/** Beer Cam: photograph your drink inside the outline; counts towards a million. OWNER: wave 2 "AC". */
export default defineExtension({
  id: 'beer',
  load: () => import('./BeerPage'),
  card: () => import('./BeerCard'),
  emoji: '🍺',
});
