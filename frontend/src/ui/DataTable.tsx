import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react';
import type { ReactNode } from 'react';
import {
  Cell,
  Column,
  Row,
  Table,
  TableBody,
  TableHeader,
  type Key,
  type SortDescriptor,
} from 'react-aria-components';
import { cx } from './cx';

export interface DataColumn<T> {
  id: string;
  label: string;
  render: (row: T) => ReactNode;
  /** the column that names the row for screen readers (exactly one) */
  isRowHeader?: boolean;
  allowsSorting?: boolean;
  /** numbers and times: end-aligned, tabular */
  align?: 'start' | 'end';
  /** Tailwind width class for the column, e.g. "w-24" */
  width?: string;
  /** hide on narrow screens */
  hideBelow?: 'sm' | 'md' | 'lg';
}

export interface DataTableProps<T> {
  'aria-label': string;
  columns: ReadonlyArray<DataColumn<T>>;
  rows: ReadonlyArray<T>;
  getRowId: (row: T) => Key;
  sortDescriptor?: SortDescriptor;
  onSortChange?: (descriptor: SortDescriptor) => void;
  /** row → detail page (Gäste → user page) */
  onRowAction?: (id: Key) => void;
  /** shown when there are no rows and nothing is loading */
  emptyState?: ReactNode;
  isLoading?: boolean;
  /**
   * The table scrolls inside this height so the header can stick
   * (sticky needs a bounded scroll box). Pass "max-h-none" to let the page scroll.
   */
  maxHeightClass?: string;
  className?: string;
}

const HIDE = { sm: 'max-sm:hidden', md: 'max-md:hidden', lg: 'max-lg:hidden' } as const;

/**
 * Sortable data table (Gäste, Sperren, Protokoll). Sticky header, tabular figures,
 * horizontal scroll with an edge shadow on phones, optional row links.
 */
export function DataTable<T>({
  columns,
  rows,
  getRowId,
  sortDescriptor,
  onSortChange,
  onRowAction,
  emptyState,
  isLoading = false,
  maxHeightClass = 'max-h-[75dvh]',
  className,
  ...rest
}: DataTableProps<T>) {
  const skeleton = isLoading && rows.length === 0;
  return (
    <div
      aria-busy={isLoading || undefined}
      className={cx(
        'overflow-auto overscroll-x-contain rounded-control border border-line bg-surface-raised scroll-shadows-x',
        maxHeightClass,
        className,
      )}
    >
      <Table
        aria-label={rest['aria-label']}
        {...(sortDescriptor ? { sortDescriptor } : {})}
        {...(onSortChange ? { onSortChange } : {})}
        {...(onRowAction ? { onRowAction } : {})}
        className="w-full border-separate border-spacing-0 text-sm tabular"
      >
        <TableHeader className="sticky top-0 z-(--z-sticky) bg-surface-raised">
          {columns.map((col) => (
            <Column
              key={col.id}
              id={col.id}
              isRowHeader={col.isRowHeader ?? false}
              allowsSorting={col.allowsSorting ?? false}
              className={cx(
                'h-11 border-b border-line px-3 text-xs font-semibold whitespace-nowrap text-ink-muted outline-none',
                'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus',
                col.align === 'end' ? 'text-right' : 'text-left',
                col.allowsSorting && 'cursor-pointer hover:text-ink',
                col.width,
                col.hideBelow && HIDE[col.hideBelow],
              )}
            >
              {({ sortDirection, allowsSorting }) => (
                <span
                  className={cx('inline-flex items-center gap-1', col.align === 'end' && 'flex-row-reverse')}
                >
                  {col.label}
                  {allowsSorting ? (
                    sortDirection === 'ascending' ? (
                      <ArrowUp aria-hidden="true" className="size-3.5 text-ink" strokeWidth={2.5} />
                    ) : sortDirection === 'descending' ? (
                      <ArrowDown aria-hidden="true" className="size-3.5 text-ink" strokeWidth={2.5} />
                    ) : (
                      <ChevronsUpDown aria-hidden="true" className="size-3.5 opacity-60" strokeWidth={2.25} />
                    )
                  ) : null}
                </span>
              )}
            </Column>
          ))}
        </TableHeader>
        <TableBody
          className="align-middle"
          renderEmptyState={() =>
            skeleton ? (
              <span className="grid gap-3 p-4" aria-hidden="true">
                {[0, 1, 2, 3, 4].map((i) => (
                  <span key={i} className="block h-5 animate-shimmer rounded-small bg-surface-sunk" />
                ))}
              </span>
            ) : (
              (emptyState ?? <p className="p-6 text-ink-muted">Keine Einträge.</p>)
            )
          }
        >
          {rows.map((row) => {
            const id = getRowId(row);
            return (
              <Row
                key={String(id)}
                id={id}
                className={cx(
                  'outline-none focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus',
                  onRowAction && 'cursor-pointer hover:bg-surface-hover',
                )}
              >
                {columns.map((col) => (
                  <Cell
                    key={col.id}
                    className={cx(
                      'h-12 border-b border-line px-3 align-middle whitespace-nowrap',
                      col.align === 'end' ? 'text-right' : 'text-left',
                      col.hideBelow && HIDE[col.hideBelow],
                    )}
                  >
                    {col.render(row)}
                  </Cell>
                ))}
              </Row>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
