import { PAGE_SIZE_OPTIONS } from '../../constants/index.js'

/**
 * Pager bar.
 *
 * Two navigation shapes are supported:
 * - numbered (offset endpoints): pass `onPageChange(page)`; disabled
 *   states are derived from `page`/`pages`.
 * - cursor (measurement/query lists): pass `hasPrev`/`hasNext` and the
 *   `onFirst/onPrev/onNext/onLast` callbacks. Buttons then reflect what
 *   the keyset backend actually reaches, so they can never request a
 *   non-existent page.
 */
export default function Pagination({
  page,
  pages,
  total,
  pageSize,
  onPageChange,
  onPageSizeChange,
  hasPrev,
  hasNext,
  onFirst,
  onPrev,
  onNext,
  onLast,
  loading = false
}) {
  const safePages = Math.max(pages || 1, 1)
  const canPrev = hasPrev ?? page > 1
  const canNext = hasNext ?? page < safePages

  const first = onFirst ?? (() => onPageChange?.(1))
  const prev = onPrev ?? (() => onPageChange?.(page - 1))
  const next = onNext ?? (() => onPageChange?.(page + 1))
  const last = onLast ?? (() => onPageChange?.(safePages))

  return (
    <div className="pager">
      <div className="pager-info" aria-live="polite">
        共 <span className="strong">{total}</span> 条记录 · 第 {page}/{safePages} 页
      </div>
      <div className="pager-controls">
        <select
          className="select"
          value={pageSize}
          onChange={(event) => onPageSizeChange?.(Number(event.target.value))}
          aria-label="每页条数"
        >
          {PAGE_SIZE_OPTIONS.map((size) => (
            <option key={size} value={size}>
              每页 {size} 条
            </option>
          ))}
        </select>
        <button type="button" className="btn btn-sm" disabled={loading || !canPrev} onClick={first}>
          首页
        </button>
        <button type="button" className="btn btn-sm" disabled={loading || !canPrev} onClick={prev}>
          上一页
        </button>
        <button type="button" className="btn btn-sm" disabled={loading || !canNext} onClick={next}>
          下一页
        </button>
        <button type="button" className="btn btn-sm" disabled={loading || !canNext} onClick={last}>
          末页
        </button>
      </div>
    </div>
  )
}
