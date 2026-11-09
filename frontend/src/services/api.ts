// Thin fetch wrapper: same-origin cookies, CSRF header, typed errors.

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''

const UNREACHABLE = 'Can’t reach the server. Check your connection and try again.'

export class ApiError extends Error {
  status: number
  fieldErrors: { field: string; message: string }[]
  data: unknown
  /** Seconds the server asked us to wait, when it said so. */
  retryAfter: number | null

  constructor(status: number, message: string, fieldErrors: { field: string; message: string }[] = [], data?: unknown, retryAfter: number | null = null) {
    super(message)
    this.status = status
    this.fieldErrors = fieldErrors
    this.data = data
    this.retryAfter = retryAfter
  }
}

export type Query = Record<string, string | number | boolean | null | undefined>

export function qs(params: Query): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

function defaultMessage(status: number): string {
  if (status === 429) return 'Too many requests. Please wait a moment.'
  if (status >= 500) return 'Something went wrong on our side. Please try again.'
  return `Request failed (${status})`
}

async function parseError(res: Response): Promise<ApiError> {
  let data: unknown = null
  try {
    data = await res.json()
  } catch {
    /* non-JSON error */
  }
  const body = (data ?? {}) as { detail?: unknown; errors?: { field: string; message: string }[] }
  let message = defaultMessage(res.status)
  const errors = [...(body.errors ?? [])]
  if (typeof body.detail === 'string') message = body.detail
  else if (body.detail && typeof body.detail === 'object' && 'message' in body.detail) {
    const detail = body.detail as { message: string; field?: string }
    message = String(detail.message)
    if (detail.field) errors.push({ field: detail.field, message })
  }
  if (body.errors?.length) message = body.errors.map((e) => (e.field ? `${e.field}: ${e.message}` : e.message)).join(' · ')
  const retryAfter = Number(res.headers.get('retry-after')) || null
  return new ApiError(res.status, message, errors, data, retryAfter)
}

export async function request<T>(method: string, path: string, body?: unknown, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { 'X-Requested-With': 'XMLHttpRequest' }
  let payload: BodyInit | undefined
  if (body instanceof FormData) payload = body
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, { method, headers, body: payload, credentials: 'include', ...init })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw new ApiError(0, UNREACHABLE)
  }
  if (!res.ok) throw await parseError(res)
  if (res.status === 204) return undefined as T
  const ct = res.headers.get('content-type') ?? ''
  return (ct.includes('application/json') ? res.json() : res.text()) as Promise<T>
}

export const api = {
  get: <T>(path: string, params?: Query, init?: RequestInit) => request<T>('GET', path + (params ? qs(params) : ''), undefined, init),
  post: <T>(path: string, body?: unknown, init?: RequestInit) => request<T>('POST', path, body ?? {}, init),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body ?? {}),
  del: <T>(path: string, body?: unknown) => request<T>('DELETE', path, body),
  upload: <T>(path: string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<T>('POST', path, fd)
  },
}

/** POST and read an NDJSON stream, calling onEvent for each line as it arrives. */
export async function streamNdjson(path: string, body: unknown, onEvent: (e: unknown) => void, signal?: AbortSignal) {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify(body),
      credentials: 'include',
      signal,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') return
    throw new ApiError(0, UNREACHABLE)
  }
  if (!res.ok || !res.body) throw await parseError(res)
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let idx
      while ((idx = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, idx).trim()
        buffer = buffer.slice(idx + 1)
        if (line) onEvent(JSON.parse(line))
      }
    }
  } catch (e) {
    if ((e as Error).name === 'AbortError') return
    throw e
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer))
}
