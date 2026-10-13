/**
 * `data-*` attributes (test ids, states) that a component hands to its root element,
 * so callers don't need a wrapper element just to carry them.
 */
export type DataAttributes = { [key: `data-${string}`]: string | number | boolean | undefined };

/** The `data-*` entries of `props` (anything else is dropped). */
export function dataAttributes(props: object): DataAttributes {
  const out: DataAttributes = {};
  for (const [key, value] of Object.entries(props)) {
    if (
      key.startsWith('data-') &&
      (value === undefined || ['string', 'number', 'boolean'].includes(typeof value))
    ) {
      // oxlint-disable-next-line typescript/no-unsafe-type-assertion -- the key starts with data-, the value type is checked
      out[key as `data-${string}`] = value as string | number | boolean | undefined;
    }
  }
  return out;
}
