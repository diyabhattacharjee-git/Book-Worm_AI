import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../contexts/AuthContext'
import { ToastProvider } from '../contexts/ToastContext'
import Register from '../pages/Register'

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('sign-up with an emailed code', () => {
  afterEach(() => vi.restoreAllMocks())

  it('verifies the email code before letting the user set a password', async () => {
    const calls: { url: string; body: unknown }[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null })
      if (url.endsWith('/api/auth/session')) return json(200, { user: null })
      if (url.endsWith('/api/auth/config')) return json(200, { google_client_id: null })
      if (url.endsWith('/api/auth/signup/start')) return json(202, { detail: 'sent' })
      if (url.endsWith('/api/auth/signup/verify')) {
        const { code } = JSON.parse(String(init!.body))
        return code === '123456' ? json(200, { verification_token: 'tok-abcdefghijklmnopqrstuvwxyz' }) : json(400, { detail: 'That code is incorrect. 4 attempts left.' })
      }
      if (url.includes('/api/auth/username-available')) return json(200, { available: true, reason: null })
      if (url.endsWith('/api/auth/signup/complete')) return json(201, { id: 7, email: 'new@example.com', username: 'new.reader', display_name: 'New Reader', role: 'user', preferences: {} })
      return json(404, { detail: 'not mocked' })
    })
    const router = createMemoryRouter([
      { path: '/register', element: <Register /> },
      { path: '/for-you', element: <p>Recommendations page</p> },
    ], { initialEntries: ['/register'] })
    render(<ToastProvider><AuthProvider><RouterProvider router={router} /></AuthProvider></ToastProvider>)
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText('Email'), 'new@example.com')
    await user.click(screen.getByRole('button', { name: 'Send verification code' }))

    const codeBox = await screen.findByLabelText('Verification code')
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
    await user.type(codeBox, '999999')
    await user.click(screen.getByRole('button', { name: 'Verify email' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('incorrect')

    await user.clear(codeBox)
    await user.type(codeBox, '123456')
    await user.click(screen.getByRole('button', { name: 'Verify email' }))

    await user.type(await screen.findByLabelText('Username'), 'new.reader')
    await user.type(screen.getByLabelText('Display name'), 'New Reader')
    await user.type(screen.getByLabelText('Password'), 'g00d-Passw0rd')
    await user.type(screen.getByLabelText('Confirm password'), 'g00d-Passw0rd')
    await user.click(screen.getByRole('button', { name: 'Create account' }))

    await waitFor(() => expect(screen.getByText('Recommendations page')).toBeInTheDocument())
    const complete = calls.find((c) => c.url.endsWith('/api/auth/signup/complete'))!
    expect(complete.body).toMatchObject({ verification_token: 'tok-abcdefghijklmnopqrstuvwxyz', username: 'new.reader', password: 'g00d-Passw0rd' })
  })
})
