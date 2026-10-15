/**
 * Shared layout of the admin sections with many cards (Live-Wall, ML-Pipeline). The
 * section is the size container (`@container`): its width already excludes the sidebar.
 * One column of readable width (48rem) up to 66rem of section, then two independent
 * stacks (each ~32rem), so a card is never squeezed next to the sidebar.
 */
export const ADMIN_COLUMNS =
  'grid max-w-3xl items-start gap-x-10 gap-y-8 @[66rem]:max-w-none @[66rem]:grid-cols-2';
