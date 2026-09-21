import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Shared list state: filters + sort + pagination + request lifecycle.
 *
 * 稳定性约定 (与后端 services/snapshot_service.py 配合):
 * - 首屏 / 改筛选 / 改排序 / 手动刷新: 回到第一页并重新建立结果集快照;
 * - 仅翻页 / 改每页条数: 沿用同一份 snapshot_token, 他人新增或删除记录
 *   不会让已经看过的页整页位移、重复或遗漏;
 * - 快照过期 (410) 时静默丢弃旧令牌, 回到第一页重建快照。
 *
 * `fetcher` receives { ...filters, sort, order, page, page_size, snapshot_token }
 * and must return the API payload.
 */
export function useListQuery(
  fetcher,
  initialFilters = {},
  {
    pageSize = 20,
    enabled = true,
    initialSort = 'measured_at',
    initialOrder = 'desc'
  } = {}
) {
  const [filters, setFilters] = useState(initialFilters)
  const [sort, setSortState] = useState(initialSort)
  const [order, setOrder] = useState(initialOrder)
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(pageSize)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(enabled)
  const [error, setError] = useState(null)
  const requestId = useRef(0)
  const snapshotTokenRef = useRef(null)

  const runRequest = useCallback(
    async (current, params, allowRetry) => {
      try {
        const payload = await fetcher(params)
        if (current !== requestId.current) return
        if (payload.snapshot_token) snapshotTokenRef.current = payload.snapshot_token
        setData(payload)
        setError(null)
      } catch (err) {
        if (current !== requestId.current) return
        const expired = err?.code === 'SNAPSHOT_EXPIRED' || err?.status === 410
        if (expired && allowRetry && params.snapshot_token) {
          // 快照已过期: 丢弃旧令牌, 回到第一页按最新数据重建
          snapshotTokenRef.current = null
          setPage(1)
          const retryId = ++requestId.current
          const { snapshot_token: _ignored, ...freshParams } = params
          await runRequest(retryId, { ...freshParams, page: 1 }, false)
          return
        }
        setError(err)
        setData(null)
      } finally {
        if (current === requestId.current) setLoading(false)
      }
    },
    [fetcher]
  )

  const load = useCallback(
    ({ resetPage = false } = {}) => {
      const nextPage = resetPage ? 1 : page
      if (resetPage) {
        setPage(1)
        snapshotTokenRef.current = null
      }
      const current = ++requestId.current
      setLoading(true)
      setError(null)
      const token = snapshotTokenRef.current
      return runRequest(
        current,
        {
          ...filters,
          sort,
          order,
          page: nextPage,
          page_size: size,
          ...(token ? { snapshot_token: token } : {})
        },
        true
      )
    },
    [filters, sort, order, page, size, runRequest]
  )

  useEffect(() => {
    if (enabled) load()
  }, [enabled, load])

  const applyFilters = useCallback((next) => {
    setPage(1)
    snapshotTokenRef.current = null
    setFilters(typeof next === 'function' ? next : next)
  }, [])

  const changeSort = useCallback((nextSort, nextOrder) => {
    setPage(1)
    snapshotTokenRef.current = null
    setSortState(nextSort)
    setOrder(nextOrder || 'desc')
  }, [])

  const changePageSize = useCallback((nextSize) => {
    // 回到第一页但沿用同一份快照, 不必重建结果集
    setPage(1)
    setSize(nextSize)
  }, [])

  const refresh = useCallback(() => load({ resetPage: true }), [load])

  return {
    items: data?.items ?? [],
    data,
    total: data?.total ?? 0,
    pages: data?.pages ?? 0,
    summary: data?.summary ?? null,
    filters,
    setFilters: applyFilters,
    sort,
    order,
    setSort: changeSort,
    page,
    setPage,
    pageSize: size,
    setPageSize: changePageSize,
    loading,
    error,
    reload: load,
    refresh,
    snapshotCreatedAt: data?.snapshot_created_at ?? null
  }
}
