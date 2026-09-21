import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Shared list state for the list modules.
 *
 * mode="cursor" (measurement list / query page)
 * ----------------------------------------------
 * The backend pages with a keyset cursor (the sort value + unique id of a
 * boundary row), so concurrent inserts/deletes cannot shift rows between
 * pages the way OFFSET does. The client additionally caches every page it
 * has already visited: pressing "previous page" renders the cached page
 * instantly and verbatim — rows already seen never move, even while
 * someone else is recording or deleting data at the same time.
 *
 * mode="offset" (stations / exceedances)
 * --------------------------------------
 * Plain numbered pages for endpoints that still return page/pages.
 *
 * `fetcher` receives the request params and returns the API payload.
 */
export function useListQuery(
  fetcher,
  initialFilters = {},
  { pageSize = 20, sort = 'measured_at', order = 'desc', mode = 'offset' } = {}
) {
  const [filters, setFiltersState] = useState(initialFilters)
  const [sortState, setSortState] = useState({ sort, order })
  const [size, setSizeState] = useState(pageSize)
  const [index, setIndex] = useState(0) // cursor: position in the visited stack
  const [views, setViews] = useState([]) // cursor: [{ params, payload }]
  const [pageNo, setPageNo] = useState(1) // offset: current page number
  const [data, setData] = useState(null) // offset: latest payload
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const runRef = useRef(0)
  const filtersRef = useRef(filters)
  const sizeRef = useRef(size)
  const sortRef = useRef(sortState)

  useEffect(() => {
    filtersRef.current = filters
  }, [filters])
  useEffect(() => {
    sizeRef.current = size
  }, [size])
  useEffect(() => {
    sortRef.current = sortState
  }, [sortState])

  const fetchPayload = useCallback(
    async (params) => {
      const run = ++runRef.current
      setLoading(true)
      setError(null)
      let payload
      try {
        payload = await fetcher(params)
      } catch (err) {
        if (run === runRef.current) {
          setError(err)
          setLoading(false)
        }
        throw err
      }
      if (run === runRef.current) setLoading(false)
      return payload
    },
    [fetcher]
  )

  // ---------------- offset mode ----------------
  const loadOffsetPage = useCallback(
    (page, overrideFilters) => {
      const effective = overrideFilters ?? filtersRef.current
      return fetchPayload({ ...effective, page, page_size: sizeRef.current })
        .then((payload) => {
          setData(payload)
          setPageNo(page)
        })
        .catch(() => {})
    },
    [fetchPayload]
  )

  // ---------------- cursor mode ----------------
  const restartCursor = useCallback(
    (base) => {
      const params = { ...base, dir: 'first' }
      return fetchPayload(params)
        .then((payload) => {
          setViews([{ params, payload }])
          setIndex(0)
        })
        .catch(() => {})
    },
    [fetchPayload]
  )

  useEffect(() => {
    if (mode === 'cursor') {
      restartCursor({ ...initialFilters, sort, order, page_size: pageSize })
    } else {
      loadOffsetPage(1, initialFilters)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const cursorNext = useCallback(async () => {
    const current = views[index]
    if (!current || loading) return
    if (views[index + 1]) {
      setIndex(index + 1) // render the already-visited cache verbatim
      return
    }
    if (!current.payload.next_cursor) return
    const params = {
      ...filtersRef.current,
      ...sortRef.current,
      page_size: sizeRef.current,
      dir: 'next',
      cursor: current.payload.next_cursor
    }
    try {
      const payload = await fetchPayload(params)
      setViews((prev) => [...prev.slice(0, index + 1), { params, payload }])
      setIndex(index + 1)
    } catch {
      /* keep the current page */
    }
  }, [views, index, loading, fetchPayload])

  const cursorPrevCached = useCallback(() => {
    setIndex((value) => Math.max(value - 1, 0))
  }, [])

  const cursorPrevRemote = useCallback(async () => {
    const current = views[index]
    if (!current || loading || !current.payload.prev_cursor) return
    const params = {
      ...filtersRef.current,
      ...sortRef.current,
      page_size: sizeRef.current,
      dir: 'prev',
      cursor: current.payload.prev_cursor
    }
    try {
      const payload = await fetchPayload(params)
      setViews((prev) => [{ params, payload }, ...prev])
    } catch {
      /* stay put */
    }
  }, [views, index, loading, fetchPayload])

  const cursorLast = useCallback(async () => {
    const params = { ...filtersRef.current, ...sortRef.current, page_size: sizeRef.current, dir: 'last' }
    try {
      const payload = await fetchPayload(params)
      setViews([{ params, payload }])
      setIndex(0)
    } catch {
      /* stay put */
    }
  }, [fetchPayload])

  // ---------------- shared controls ----------------
  const setFilters = useCallback(
    (next) => {
      const resolved = typeof next === 'function' ? next(filtersRef.current) : next
      setFiltersState(resolved)
      if (mode === 'cursor') {
        return restartCursor({
          ...resolved, ...sortRef.current, page_size: sizeRef.current
        })
      }
      return loadOffsetPage(1, resolved)
    },
    [mode, restartCursor, loadOffsetPage]
  )

  const reload = useCallback(() => {
    if (mode === 'cursor') {
      return restartCursor({
        ...filtersRef.current,
        ...sortRef.current,
        page_size: sizeRef.current
      })
    }
    return loadOffsetPage(pageNo)
  }, [mode, pageNo, restartCursor, loadOffsetPage])

  const setPageSize = useCallback(
    (nextSize) => {
      setSizeState(nextSize)
      if (mode === 'cursor') {
        return restartCursor({
          ...filtersRef.current,
          ...sortRef.current,
          page_size: nextSize
        })
      }
      return fetchPayload({ ...filtersRef.current, page: 1, page_size: nextSize })
        .then((payload) => {
          setData(payload)
          setPageNo(1)
        })
        .catch(() => {})
    },
    [mode, restartCursor, fetchPayload]
  )

  // Switching the sort dimension resets to page 1 with a fresh total.
  // Clicking the active dimension again toggles asc/desc.
  const setSort = useCallback(
    (nextSort) => {
      const current = sortRef.current
      const next = {
        sort: nextSort,
        order: current.sort === nextSort && current.order === 'desc' ? 'asc' : 'desc'
      }
      setSortState(next)
      if (mode === 'cursor') {
        return restartCursor({
          ...filtersRef.current,
          ...next,
          page_size: sizeRef.current
        })
      }
      return Promise.resolve()
    },
    [mode, restartCursor]
  )

  // ---------------- derived view ----------------
  const payload = mode === 'cursor' ? views[index]?.payload : data
  const cursorPages = payload
    ? Math.max(Math.ceil(payload.total / (payload.page_size || size)), 1)
    : 1
  const hasCachedPrev = mode === 'cursor' && index > 0

  return {
    items: payload?.items ?? [],
    data: payload ?? null,
    total: payload?.total ?? 0,
    pages: mode === 'cursor' ? cursorPages : payload?.pages ?? 1,
    summary: payload?.summary ?? null,
    filters,
    setFilters,
    sort: sortState.sort,
    order: sortState.order,
    setSort,
    mode,
    page: mode === 'cursor' ? index + 1 : pageNo,
    hasPrev:
      mode === 'cursor' ? hasCachedPrev || Boolean(payload?.has_prev) : pageNo > 1,
    hasNext:
      mode === 'cursor'
        ? Boolean(payload?.has_next) || views.length > index + 1
        : pageNo < (payload?.pages ?? 1),
    goFirst: mode === 'cursor' ? reload : () => loadOffsetPage(1),
    goPrev:
      mode === 'cursor'
        ? hasCachedPrev
          ? cursorPrevCached
          : cursorPrevRemote
        : () => loadOffsetPage(pageNo - 1),
    goNext: mode === 'cursor' ? cursorNext : () => loadOffsetPage(pageNo + 1),
    goLast:
      mode === 'cursor'
        ? cursorLast
        : () => loadOffsetPage(payload?.pages ?? 1),
    setPage: loadOffsetPage, // offset-mode numbered navigation
    pageSize: size,
    setPageSize,
    loading,
    error,
    reload
  }
}
