import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StrictMode, useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useDebounced, useGet } from '../hooks/useApi'
import { ApiError } from '../services/api'
import { clearCache, clearUserData, invalidate, optimistic, peek, setQueryData } from '../services/queryCache'
import { isValidIsbn } from '../utils/validation'

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function mockFetch(body: unknown = { ok: 1 }) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async () => json(200, body))
}

function Reader({ path = '/api/x', label = 'value' }: { path?: string; label?: string }) {
  const q = useGet<{ ok: number }>(path)
  return <p>{q.loading ? 'loading' : `${label}:${q.data?.ok}`}</p>
}

beforeEach(() => {
  vi.restoreAllMocks()
  clearCache()
})

describe('useGet request behaviour', () => {
  it('sends one request for several components asking for the same thing', async () => {
    const spy = mockFetch()
    render(<><Reader label="a" /><Reader label="b" /><Reader label="c" /></>)
    await screen.findByText('c:1')
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('sends one request under StrictMode double-mounting', async () => {
    const spy = mockFetch()
    render(<StrictMode><Reader /></StrictMode>)
    await screen.findByText('value:1')
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('does not refetch when unrelated state changes', async () => {
    const spy = mockFetch()
    function Page() {
      const [n, setN] = useState(0)
      return <div><button onClick={() => setN(n + 1)}>tick {n}</button><Reader /></div>
    }
    render(<Page />)
    await screen.findByText('value:1')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button'))
    await user.click(screen.getByRole('button'))
    expect(screen.getByText('tick 2')).toBeInTheDocument()
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('serves a return visit from the cache', async () => {
    const spy = mockFetch()
    const first = render(<Reader />)
    await screen.findByText('value:1')
    first.unmount()
    render(<Reader />)
    expect(screen.getByText('value:1')).toBeInTheDocument()
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('refetches once after an invalidation and keeps the old value on screen meanwhile', async () => {
    let n = 0
    const spy = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => json(200, { ok: ++n }))
    render(<Reader />)
    await screen.findByText('value:1')
    act(() => invalidate('/api/x'))
    expect(screen.getByText('value:1')).toBeInTheDocument()
    await screen.findByText('value:2')
    expect(spy).toHaveBeenCalledTimes(2)
  })

  it('updates every mounted reader when the cached value changes', async () => {
    mockFetch()
    render(<><Reader label="a" /><Reader label="b" /></>)
    await screen.findByText('a:1')
    act(() => setQueryData('/api/x', { ok: 9 }))
    expect(screen.getByText('a:9')).toBeInTheDocument()
    expect(screen.getByText('b:9')).toBeInTheDocument()
  })

  it('cancels a request nobody is waiting for', async () => {
    let signal: AbortSignal | undefined
    vi.spyOn(globalThis, 'fetch').mockImplementation((_, init) => {
      signal = init?.signal ?? undefined
      return new Promise(() => undefined)
    })
    const view = render(<Reader />)
    view.unmount()
    await waitFor(() => expect(signal?.aborted).toBe(true))
  })

  it('does not retry on its own after an error', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => json(429, { detail: 'slow down' }))
    function Failing() {
      const q = useGet('/api/x')
      return <p>{q.error ? q.error.message : 'waiting'}</p>
    }
    render(<Failing />)
    await screen.findByText('slow down')
    await new Promise((r) => setTimeout(r, 30))
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('a mounted view recovers when its data is cleared mid-request', async () => {
    let n = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => json(200, { ok: ++n }))
    function Scoped() {
      const q = useGet<{ ok: number }>('/api/mine', undefined, { userId: 4 })
      return <p>{q.loading ? 'loading' : `mine:${q.data?.ok}`}</p>
    }
    render(<Scoped />)
    act(() => clearUserData())
    await screen.findByText(/mine:\d/)
  })

  it('keeps public data across a change of account', async () => {
    const spy = mockFetch()
    render(<Reader />)
    await screen.findByText('value:1')
    act(() => clearUserData())
    expect(screen.getByText('value:1')).toBeInTheDocument()
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('makes no request while disabled', async () => {
    const spy = mockFetch()
    function Off() {
      const q = useGet('/api/x', undefined, { enabled: false })
      return <p>{q.loading ? 'loading' : 'idle'}</p>
    }
    render(<Off />)
    expect(screen.getByText('idle')).toBeInTheDocument()
    expect(spy).not.toHaveBeenCalled()
  })

  it('debounces fast typing into one value', async () => {
    vi.useFakeTimers()
    function Box({ v }: { v: string }) {
      return <p>{useDebounced(v, 300)}</p>
    }
    const view = render(<Box v="a" />)
    view.rerender(<Box v="ab" />)
    act(() => { vi.advanceTimersByTime(100) })
    view.rerender(<Box v="abc" />)
    act(() => { vi.advanceTimersByTime(299) })
    expect(screen.getByText('a')).toBeInTheDocument()
    act(() => { vi.advanceTimersByTime(2) })
    expect(screen.getByText('abc')).toBeInTheDocument()
    vi.useRealTimers()
  })
})

describe('optimistic updates', () => {
  it('shows the change immediately and keeps it on success', async () => {
    setQueryData<number[]>('k', [1])
    let finish: () => void = () => undefined
    const pending = optimistic<number[], void>('k', (d) => [...d, 2], () => new Promise<void>((r) => { finish = r }))
    expect(peek('k')).toEqual([1, 2])
    finish()
    await pending
    expect(peek('k')).toEqual([1, 2])
  })

  it('rolls back and reports when the server refuses', async () => {
    setQueryData<number[]>('k', [1])
    await expect(optimistic<number[], void>('k', (d) => [...d, 2], () => Promise.reject(new ApiError(500, 'nope')))).rejects.toThrow('nope')
    expect(peek('k')).toEqual([1])
  })
})

describe('ISBN check digits', () => {
  it.each([['9780735211292', true], ['978-0-7352-1129-2', true], ['0306406152', true], ['080442957X', true], ['9780735211293', false], ['0306406153', false], ['12345', false], ['abcdefghij', false]])('%s is %s', (isbn, valid) => {
    expect(isValidIsbn(isbn)).toBe(valid)
  })
})
