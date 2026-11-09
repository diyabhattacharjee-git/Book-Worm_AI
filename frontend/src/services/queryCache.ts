// Client-side server-state store: one entry per request, shared by every component that asks for it.
// A fresh entry costs no network call, identical in-flight requests share one fetch, and mutations
// update or invalidate entries so every mounted view stays in step.

import { ApiError } from './api'

type Listener = () => void
export type Fetcher<T> = (signal: AbortSignal) => Promise<T>

interface Entry {
  data: unknown
  error: ApiError | null
  expiresAt: number
  /** Bumped whenever anything about this entry changes. */
  version: number
  /** Bumped when the entry must be fetched again, which is what mounted hooks react to. */
  generation: number
  inFlight: { promise: Promise<unknown>; controller: AbortController; waiters: number } | null
  listeners: Set<Listener>
  touchedAt: number
}

const MAX_ENTRIES = 300
const entries = new Map<string, Entry>()

export function getEntry(key: string): Entry {
  let entry = entries.get(key)
  if (!entry) {
    entry = { data: undefined, error: null, expiresAt: 0, version: 0, generation: 0, inFlight: null, listeners: new Set(), touchedAt: Date.now() }
    entries.set(key, entry)
    evictIfNeeded()
  }
  return entry
}

function evictIfNeeded() {
  if (entries.size <= MAX_ENTRIES) return
  const idle = [...entries.entries()].filter(([, e]) => e.listeners.size === 0 && !e.inFlight).sort((a, b) => a[1].touchedAt - b[1].touchedAt)
  for (const [key] of idle.slice(0, entries.size - MAX_ENTRIES)) entries.delete(key)
}

function notify(entry: Entry) {
  entry.version += 1
  entry.touchedAt = Date.now()
  for (const listener of entry.listeners) listener()
}

export function subscribe(key: string, listener: Listener): () => void {
  const entry = getEntry(key)
  entry.listeners.add(listener)
  return () => entry.listeners.delete(listener)
}

function toApiError(e: unknown): ApiError {
  return e instanceof ApiError ? e : new ApiError(0, e instanceof Error ? e.message : String(e))
}

function isAbort(e: unknown): boolean {
  return e instanceof DOMException && e.name === 'AbortError'
}

/** Fetch `key` (joining a request already under way) and return a function that gives up interest in it. */
export function startFetch<T>(key: string, fetcher: Fetcher<T>, ttl: number): () => void {
  const entry = getEntry(key)
  if (!entry.inFlight) {
    const controller = new AbortController()
    entry.error = null
    const flight: NonNullable<Entry['inFlight']> = { promise: Promise.resolve(), controller, waiters: 0 }
    flight.promise = fetcher(controller.signal)
      .then((data) => {
        if (entry.inFlight !== flight) return // superseded by a reset
        entry.data = data
        entry.error = null
        entry.expiresAt = Date.now() + ttl
      })
      .catch((e: unknown) => {
        if (entry.inFlight === flight && !isAbort(e)) entry.error = toApiError(e)
      })
      .finally(() => {
        if (entry.inFlight !== flight) return
        entry.inFlight = null
        notify(entry)
      })
    entry.inFlight = flight
    notify(entry)
  }
  const flight = entry.inFlight!
  flight.waiters += 1
  let released = false
  return () => {
    if (released) return
    released = true
    flight.waiters -= 1
    // Deferred so a remount in the same tick (React StrictMode) keeps the request alive.
    window.setTimeout(() => {
      if (flight.waiters === 0 && entry.inFlight === flight) flight.controller.abort()
    }, 0)
  }
}

export function peek<T>(key: string): T | undefined {
  return entries.get(key)?.data as T | undefined
}

export function setQueryData<T>(key: string, updater: T | ((prev: T | undefined) => T)): void {
  const entry = getEntry(key)
  entry.data = typeof updater === 'function' ? (updater as (prev: T | undefined) => T)(entry.data as T | undefined) : updater
  entry.error = null
  notify(entry)
}

function bump(entry: Entry) {
  entry.expiresAt = 0
  entry.generation += 1
  notify(entry)
}

export function refetch(key: string): void {
  bump(getEntry(key))
}

/** Mark every entry whose key contains one of `fragments` out of date. Mounted views refetch; the rest do when next opened. */
export function invalidate(...fragments: string[]): void {
  for (const [key, entry] of entries) {
    if (fragments.some((f) => key.includes(f))) bump(entry)
  }
}

// Entries are reset in place, because mounted views are subscribed to them and must recover by refetching.
function reset(matches: (key: string) => boolean): void {
  for (const [key, entry] of entries) {
    if (!matches(key)) continue
    entry.inFlight?.controller.abort()
    entry.inFlight = null
    entry.data = undefined
    entry.error = null
    if (entry.listeners.size) bump(entry)
    else entries.delete(key)
  }
}

export function clearCache(): void {
  reset(() => true)
}

/** Forget everything tied to a signed-in account. Public data stays valid across a login or logout. */
export function clearUserData(): void {
  reset((key) => /^u\d+:/.test(key))
}

/**
 * Apply `updater` to the cached value at once, then run `request`.
 * If it fails the value is restored and refetched, and the error is rethrown for the caller to report.
 */
export async function optimistic<T, R>(key: string, updater: (prev: T) => T, request: () => Promise<R>): Promise<R> {
  const before = peek<T>(key)
  if (before !== undefined) setQueryData<T>(key, updater(before))
  try {
    return await request()
  } catch (e) {
    if (before !== undefined) setQueryData<T>(key, before)
    refetch(key)
    throw e
  }
}
