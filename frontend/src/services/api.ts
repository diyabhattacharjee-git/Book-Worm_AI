// Thin fetch wrapper: same-origin cookies, CSRF header, typed errors.

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''

export class ApiError extends Error {
  status: number
  fieldErrors: { field: string; message: string }[]
  data: unknown

  constructor(status: number, message: string, fieldErrors: { field: string; message: string }[] = [], data?: unknown) {
    super(message)
    this.status = status
    this.fieldErrors = fieldErrors
    this.data = data
  }
}

type Query = Record<string, string | number | boolean | null | undefined>

export function qs(params: Query): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

async function parseError(res: Response): Promise<ApiError> {
  let data: unknown = null
  try {
    data = await res.json()
  } catch {
    /* non-JSON error */
  }
  const body = (data ?? {}) as { detail?: unknown; errors?: { field: string; message: string }[] }
  let message = res.status === 429 ? 'Too many requests. Please wait a moment.' : `Request failed (${res.status})`
  if (typeof body.detail === 'string') message = body.detail
  else if (body.detail && typeof body.detail === 'object' && 'message' in body.detail) {
    message = String((body.detail as { message: string }).message)
  }
  if (body.errors?.length) message = body.errors.map((e) => (e.field ? `${e.field}: ${e.message}` : e.message)).join(' · ')
  return new ApiError(res.status, message, body.errors ?? [], data)
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
  } catch {
    throw new ApiError(0, 'Can’t reach the server. Is the backend running?')
  }
  if (!res.ok) throw await parseError(res)
  if (res.status === 204) return undefined as T
  const ct = res.headers.get('content-type') ?? ''
  return (ct.includes('application/json') ? res.json() : res.text()) as Promise<T>
}

export const api = {
  get: <T>(path: string, params?: Query) => request<T>('GET', path + (params ? qs(params) : '')),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
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
    throw new ApiError(0, 'Can’t reach the server. Is the backend running?')
  }
  if (!res.ok || !res.body) throw await parseError(res)
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
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
  if (buffer.trim()) onEvent(JSON.parse(buffer))
}
