import { EmptyState, Loading } from './Feedback.jsx'

/**
 * Generic table: columns = [{ key, title, width, align, className, render(row) }]
 * Supports optional row selection, used by the exceedance work bench.
 *
 * 加载态策略: 首次加载 (无旧数据) 显示行内 Loading; 翻页/刷新时保留上一页
 * 内容并在表格上覆盖半透明加载层, 表头与首列不卸载、不跳动不错位。
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
  caption
}) {
  const hasRows = rows.length > 0
  if (loading && !hasRows) return <Loading />

  const keys = rows.map((row) => row[rowKey]).filter((key) => key !== null && key !== undefined)
  const allSelected = selectable && keys.length > 0 && keys.every((key) => selectedIds.includes(key))

  return (
    <>
      <div className={`table-wrap table-wrap--loading ${loading ? 'is-loading' : ''}`}>
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
              {columns.map((column) => (
                <th key={column.key} style={column.width ? { width: column.width } : undefined}
                    className={column.align === 'right' ? 'text-right' : ''}>
                  {column.title}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => {
              const key = row[rowKey] ?? `snapshot-row-${index}`
              const selected = selectedIds.includes(row[rowKey])
              return (
                <tr
                  key={key}
                  className={`${onRowClick ? 'clickable' : ''} ${selected ? 'selected' : ''} ${
                    row.snapshot_deleted ? 'row-deleted' : ''
                  } ${rowClassName ? rowClassName(row) : ''}`}
                  onClick={onRowClick && !row.snapshot_deleted ? () => onRowClick(row) : undefined}
                >
                  {selectable && !row.snapshot_deleted ? (
                    <td onClick={(event) => event.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selected}
                        onChange={() => onToggleRow?.(row[rowKey])}
                        aria-label={`选择 ${row[rowKey]}`}
                      />
                    </td>
                  ) : selectable ? (
                    <td />
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
          </tbody>
        </table>
        {loading ? <div className="table-loading-mask" aria-live="polite"><Loading text="加载中..." /></div> : null}
      </div>
      {!hasRows ? <EmptyState text={emptyText} icon={emptyIcon} /> : null}
      {caption ? <div className="table-caption">{caption}</div> : null}
    </>
  )
}
