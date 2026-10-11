import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../services/api'

export interface ApiState<T> {
  data: T | null
  error: ApiError | null
  loading: boolean
  reload: () => void
  setData: (updater: T | null | ((prev: T | null) => T | null)) => void
}

/** Run an async loader whenever `deps` change; ignores stale responses. */
export function useApi<T>(loader: () => Promise<T>, deps: unknown[], enabled = true): ApiState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState(enabled)
  const [tick, setTick] = useState(0)
  const seq = useRef(0)
  const loaderRef = useRef(loader)
  loaderRef.current = loader

  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      return
    }
    const id = ++seq.current
    setLoading(true)
    setError(null)
    loaderRef.current()
      .then((d) => {
        if (id === seq.current) setData(d)
      })
      .catch((e: unknown) => {
        if (id === seq.current) setError(e instanceof ApiError ? e : new ApiError(0, String(e)))
      })
      .finally(() => {
        if (id === seq.current) setLoading(false)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick, enabled])

  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { data, error, loading, reload, setData }
}

export function useDebounced<T>(value: T, ms = 350): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms)
    return () => window.clearTimeout(t)
  }, [value, ms])
  return v
}
