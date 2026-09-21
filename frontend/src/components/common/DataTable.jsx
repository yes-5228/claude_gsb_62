import { EmptyState, Loading } from './Feedback.jsx'

/**
 * Generic table: columns = [{ key, title, width, align, className,
 * sortable, sortKey, render(row) }]
 * Supports optional row selection, used by the exceedance work bench.
 * Pass `sort` + `order` + `onSort(sortKey)` to make columns with
 * `sortable` (or a `sortKey`) clickable; the active column shows an
 * arrow so the current ordering always stays visible.
 */
export default function DataTable({
  columns,
  rows = [],
  rowKey = 'id',
  loading = false,
  emptyText = '暂无数据',
  emptyIcon = '📭',
  selectable = false,
  selectedIds = [],
  onToggleRow,
  onToggleAll,
  onRowClick,
  rowClassName,
  caption,
  sort = null,
  order = null,
  onSort = null,
  skeletonRows = 8
}) {
  // Keep the table mounted (and its column widths stable) while the next
  // page loads; overlay a faint mask instead of swapping in a spinner.
  const showOverlay = loading && rows.length > 0

  const keys = rows.map((row) => row[rowKey])
  const allSelected =
    selectable && keys.length > 0 && keys.every((key) => selectedIds.includes(key))

  const renderHeaderCell = (column) => {
    const active = column.sortKey && sort === column.sortKey
    const sortable = Boolean(column.sortKey)
    const arrow = active ? (order === 'asc' ? '▲' : '▼') : ''
    const content = (
      <span className={sortable ? 'sort-label' : undefined}>
        {column.title}
        {sortable ? <span className={`sort-arrow${active ? ' active' : ''}`}>{arrow || '↕'}</span> : null}
      </span>
    )
    return (
      <th
        key={column.key}
        style={column.width ? { width: column.width } : undefined}
        className={column.align === 'right' ? 'text-right' : ''}
      >
        {sortable ? (
          <button
            type="button"
            className={`sort-button${active ? ' active' : ''}`}
            onClick={() => onSort?.(column.sortKey)}
            aria-label={`按${column.title}排序`}
          >
            {content}
          </button>
        ) : (
          content
        )}
      </th>
    )
  }

  return (
    <>
      <div className={`table-wrap${showOverlay ? ' loading' : ''}`}>
        <table className="data-table">
          <thead>
            <tr>
              {selectable ? (
                <th style={{ width: 44 }}>
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={() => onToggleAll?.(keys)}
                    aria-label="全选"
                  />
                </th>
              ) : null}
              {columns.map(renderHeaderCell)}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const key = row[rowKey]
              const selected = selectedIds.includes(key)
              return (
                <tr
                  key={key}
                  className={`${onRowClick ? 'clickable' : ''} ${selected ? 'selected' : ''} ${
                    rowClassName ? rowClassName(row) : ''
                  }`}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                >
                  {selectable ? (
                    <td onClick={(event) => event.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selected}
                        onChange={() => onToggleRow?.(key)}
                        aria-label={`选择 ${key}`}
                      />
                    </td>
                  ) : null}
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      className={`${column.align === 'right' ? 'text-right' : ''} ${
                        column.className || ''
                      }`}
                    >
                      {column.render ? column.render(row) : row[column.key] ?? '-'}
                    </td>
                  ))}
                </tr>
              )
            })}
            {/* Reserve the same number of rows during the first load so the
                table height and column widths do not jump when data lands. */}
            {loading && rows.length === 0
              ? Array.from({ length: skeletonRows }).map((_, rowIndex) => (
                  <tr key={`skeleton-${rowIndex}`} className="skeleton-row" aria-hidden="true">
                    {selectable ? <td /> : null}
                    {columns.map((column) => (
                      <td
                        key={column.key}
                        className={column.align === 'right' ? 'text-right' : ''}
                      >
                        <span className="skeleton-line" />
                      </td>
                    ))}
                  </tr>
                ))
              : null}
          </tbody>
        </table>
        {showOverlay ? (
          <div className="table-loading-mask">
            <span className="spinner" />
            <span>加载中…</span>
          </div>
        ) : null}
      </div>
      {!loading && rows.length === 0 ? <EmptyState text={emptyText} icon={emptyIcon} /> : null}
      {caption ? <div className="table-caption">{caption}</div> : null}
    </>
  )
}
