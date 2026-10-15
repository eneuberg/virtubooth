/**
 * How many of a tile's analysis chips fit the fixed chip area under a Live tile (pure;
 * chipFit.test.ts). The area holds a fixed number of rows, so toggling „Analyse zeigen“
 * or an analysis arriving never changes the tile's height; what does not fit ends in a
 * „+N“ chip (the full list is in the photo viewer).
 */

/** Rows the chips take when laid out like `flex-wrap` (each chip at most a row wide). */
export function chipRows(widths: readonly number[], rowWidth: number, gap: number): number {
  let rows = 0;
  let x = 0;
  for (const raw of widths) {
    const w = Math.min(raw, rowWidth);
    if (rows === 0 || x + gap + w > rowWidth) {
      rows += 1;
      x = w;
    } else {
      x += gap + w;
    }
  }
  return rows;
}

/**
 * The number of chips to show: all of them when they fit in `rows` rows, else the most
 * that fit together with the „+N“ chip (`moreWidth` wide) behind them. Before the area
 * has a width (not laid out yet) all chips count as fitting.
 */
export function fitChips(
  widths: readonly number[],
  rowWidth: number,
  gap: number,
  rows: number,
  moreWidth: number,
): number {
  if (!(rowWidth > 0) || chipRows(widths, rowWidth, gap) <= rows) return widths.length;
  for (let shown = widths.length - 1; shown > 0; shown -= 1) {
    if (chipRows([...widths.slice(0, shown), moreWidth], rowWidth, gap) <= rows) return shown;
  }
  return 0;
}
