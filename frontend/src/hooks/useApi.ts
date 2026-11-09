import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { ApiError, api, qs, type Query } from '../services/api'
import { getEntry, refetch, setQueryData, startFetch, subscribe } from '../services/queryCache'

/** How long a response counts as fresh. Mutations invalidate entries sooner, so these only cap staleness. */
export const TTL = { short: 30_000, medium: 120_000, long: 600_000, hour: 3_600_000 } as const

export interface ApiState<T> {
  data: T | null
  error: ApiError | null
  /** True only when there is nothing to show yet; background refreshes keep the current view on screen. */
  loading: boolean
  refreshing: boolean
  reload: () => void
  setData: (updater: T | null | ((prev: T | null) => T | null)) => void
}

interface GetOptions {
  ttl?: number
  enabled?: boolean
  /** Set for responses that differ per signed-in user, so one reader's data is never shown to another. */
  userId?: number | null
  /** Keep showing the previous result while the next one loads (pagination, filters). */
  keepPrevious?: boolean
  /** Hold the request but report "loading", e.g. until we know who is signed in. */
  paused?: boolean
}

export function queryKey(path: string, params?: Query, userId?: number | null): string {
  return `${userId ? `u${userId}:` : ''}${path}${params ? qs(params) : ''}`
}

const NO_KEY = '__none__'

/** Cached, de-duplicated GET. It only runs when its URL changes or the cached value goes out of date. */
export function useGet<T>(path: string | null, params?: Query, options: GetOptions = {}): ApiState<T> {
  const { ttl = TTL.medium, enabled = true, userId, keepPrevious = false, paused = false } = options
  const active = path !== null && enabled && !paused
  const key = active ? queryKey(path, params, userId) : null
  const storeKey = key ?? NO_KEY

  const latest = useRef({ path, params })
  useEffect(() => { latest.current = { path, params } })

  const subscribeToEntry = useCallback((listener: () => void) => subscribe(storeKey, listener), [storeKey])
  const version = useSyncExternalStore(subscribeToEntry, () => getEntry(storeKey).version)
  const entry = getEntry(storeKey)
  const generation = entry.generation

  useEffect(() => {
    if (!key) return
    const current = getEntry(key)
    if (current.data !== undefined && Date.now() < current.expiresAt) return
    return startFetch(key, (signal) => api.get<T>(latest.current.path as string, latest.current.params, { signal }), ttl)
  }, [key, generation, ttl])

  const [previous, setPrevious] = useState<T | null>(null)
  const data = key ? (entry.data as T | undefined) : undefined
  useEffect(() => {
    if (keepPrevious && data !== undefined) setPrevious(data)
  }, [data, keepPrevious])

  const reload = useCallback(() => { if (key) refetch(key) }, [key])
  const setData = useCallback((updater: T | null | ((prev: T | null) => T | null)) => {
    if (key) setQueryData<T | null>(key, (prev) => (typeof updater === 'function' ? (updater as (p: T | null) => T | null)(prev ?? null) : updater))
  }, [key])

  void version
  if (!key) return { data: null, error: null, loading: paused, refreshing: false, reload, setData }
  const shown = data !== undefined ? data : keepPrevious ? previous : null
  return {
    data: shown,
    error: data === undefined ? entry.error : null,
    loading: shown === null && entry.error === null,
    refreshing: entry.inFlight !== null && shown !== null,
    reload,
    setData,
  }
}

/** For requests that aren't a single GET. Runs when `deps` change, ignores stale responses and keeps data across reloads. */
export function useApi<T>(loader: () => Promise<T>, deps: unknown[], enabled = true): ApiState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState(enabled)
  const [refreshing, setRefreshing] = useState(false)
  const [tick, setTick] = useState(0)
  const seq = useRef(0)
  const lastDeps = useRef<string | null>(null)
  const running = useRef<string | null>(null)
  const loaderRef = useRef(loader)
  useEffect(() => { loaderRef.current = loader })

  const depsKey = JSON.stringify(deps)
  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      return
    }
    const runKey = `${depsKey}#${tick}`
    if (running.current === runKey) return // StrictMode re-ran this effect; the request is already out
    running.current = runKey
    const id = ++seq.current
    const sameRequest = lastDeps.current === depsKey
    lastDeps.current = depsKey
    if (sameRequest) setRefreshing(true)
    else {
      setData(null)
      setLoading(true)
    }
    setError(null)
    loaderRef.current()
      .then((d) => { if (id === seq.current) setData(d) })
      .catch((e: unknown) => { if (id === seq.current) setError(e instanceof ApiError ? e : new ApiError(0, String(e))) })
      .finally(() => {
        if (id === seq.current) {
          running.current = null
          setLoading(false)
          setRefreshing(false)
        }
      })
  }, [depsKey, tick, enabled])

  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { data, error, loading, refreshing, reload, setData }
}

export function useDebounced<T>(value: T, ms = 350): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms)
    return () => window.clearTimeout(t)
  }, [value, ms])
  return v
}
