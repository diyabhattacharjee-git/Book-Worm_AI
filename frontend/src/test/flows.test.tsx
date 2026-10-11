import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../contexts/AuthContext'
import { ToastProvider } from '../contexts/ToastContext'
import Login, { safeNext } from '../pages/Login'
import { api, ApiError } from '../services/api'
import { money } from '../utils/format'

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('format helpers', () => {
  it('formats rupees without decimals and other currencies precisely', () => {
    expect(money(1400, 'INR')).toBe('₹1,400')
    expect(money(12.5, 'USD')).toBe('$12.50')
    expect(money(null, 'INR')).toBe('Unknown')
  })
})

describe('safeNext', () => {
  it('blocks open redirects', () => {
    expect(safeNext('/shelf')).toBe('/shelf')
    expect(safeNext('//evil.example')).toBe('/for-you')
    expect(safeNext('https://evil.example')).toBe('/for-you')
    expect(safeNext(null)).toBe('/for-you')
  })
})

describe('api client', () => {
  afterEach(() => vi.restoreAllMocks())

  it('sends the CSRF header and credentials on writes', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(200, { ok: true }))
    await api.post('/api/x', { a: 1 })
    const [, init] = spy.mock.calls[0]
    expect((init!.headers as Record<string, string>)['X-Requested-With']).toBe('XMLHttpRequest')
    expect(init!.credentials).toBe('include')
  })

  it('turns validation errors into readable ApiErrors', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(422, { detail: 'Validation failed', errors: [{ field: 'price_amount', message: 'must be > 0' }] }))
    const err = (await api.post("/api/x").catch((e: unknown) => e)) as ApiError
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(422)
    expect(err.fieldErrors[0].field).toBe('price_amount')
  })

  it('reports an unreachable backend clearly', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(api.get('/api/health')).rejects.toThrow(/reach the server/)
  })
})

describe('login flow', () => {
  beforeEach(() => vi.restoreAllMocks())

  function renderLogin() {
    const router = createMemoryRouter([
      { path: '/login', element: <Login /> },
      { path: '/shelf', element: <p>Shelf page</p> },
    ], { initialEntries: ['/login?next=/shelf'] })
    render(<ToastProvider><AuthProvider><RouterProvider router={router} /></AuthProvider></ToastProvider>)
  }

  it('shows the server error on wrong credentials', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith('/api/auth/session')) return json(200, { user: null })
      if (url.endsWith('/api/auth/config')) return json(200, { google_client_id: null })
      return json(401, { detail: 'Incorrect username/email or password' })
    })
    renderLogin()
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Username or email'), 'a@b.com')
    await user.type(screen.getByLabelText('Password'), 'nope-1234')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect username/email or password')
  })

  it('redirects to the requested page after logging in', async () => {
    const me = { id: 1, email: 'a@b.com', display_name: 'Ana', role: 'user', preferences: {} }
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith('/api/auth/session')) return json(200, { user: null })
      if (url.endsWith('/api/auth/config')) return json(200, { google_client_id: null })
      return json(200, me)
    })
    renderLogin()
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Username or email'), 'a@b.com')
    await user.type(screen.getByLabelText('Password'), 'right-pass-1')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(screen.getByText('Shelf page')).toBeInTheDocument())
  })
})
