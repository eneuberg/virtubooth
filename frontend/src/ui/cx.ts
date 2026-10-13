import { cnMerge, createTV, type TWMergeConfig } from 'tailwind-variants';

/**
 * tailwind-merge must know the custom theme scales in app.css, or it treats
 * `text-dots-sm` as a colour and drops `text-ink` next to it (or the other way round).
 */
const twMergeConfig: TWMergeConfig = {
  extend: {
    theme: {
      text: ['xs', 'sm', 'md', 'lg', 'xl', '2xl', '3xl', 'dots-sm', 'dots-md', 'dots-xl'],
      radius: ['hole', 'small', 'control', 'full'],
      shadow: ['float'],
      'font-weight': ['normal', 'semibold', 'bold'],
    },
  },
};

/** Variant-aware class builder (tailwind-variants), aware of our tokens. */
export const tv = createTV({ twMergeConfig });

/** Joins class names and resolves Tailwind conflicts (later wins). */
export function cx(...classes: Array<string | false | null | undefined>): string {
  return cnMerge(...classes)({ twMergeConfig }) ?? '';
}

export type { VariantProps } from 'tailwind-variants';
