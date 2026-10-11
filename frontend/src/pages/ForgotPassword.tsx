import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { CodeInput, ResendCode } from '../components/auth'
import { Field } from '../components/ui'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { api } from '../services/api'
import type { User } from '../types'

/** Reset a forgotten password, or set a first password on a Google-created account. */
export default function ForgotPassword() {
  const { user, setUser } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const setting = params.get('mode') === 'set'
  const [email, setEmail] = useState(user?.email ?? params.get('email') ?? '')
  const [sent, setSent] = useState(false)
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function run(fn: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try { await fn() } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  const send = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => { await api.post('/api/auth/password/forgot', { email: email.trim() }); setSent(true) })
  }

  const reset = (e: FormEvent) => {
    e.preventDefault()
    if (password.length < 8 || /^\d+$/.test(password) || /^[a-zA-Z]+$/.test(password)) { setError('Use at least 8 characters, mixing letters with numbers or symbols.'); return }
    if (password !== confirm) { setError('Passwords don’t match.'); return }
    void run(async () => {
      const u = await api.post<User>('/api/auth/password/reset', { email: email.trim(), code, new_password: password })
      setUser(u)
      toast.success(setting ? 'Password set. You can now sign in with it.' : 'Password changed. Other devices were signed out.')
      navigate(setting ? '/settings' : '/for-you', { replace: true })
    })
  }

  return (
    <div className="mx-auto max-w-md">
      <div className="card p-8">
        <h1 className="text-3xl font-semibold">{setting ? 'Set a password' : 'Reset your password'}</h1>
        <p className="mt-1 mb-6 text-sm text-muted">We’ll email you a 6-digit code to confirm it’s you.</p>
        {!sent ? (
          <form onSubmit={send} className="space-y-4" noValidate>
            <Field label="Email" htmlFor="fp-email">
              <input id="fp-email" type="email" autoComplete="email" className="input" value={email} onChange={(e) => setEmail(e.target.value)} readOnly={!!user} />
            </Field>
            {error && <p role="alert" className="rounded-lg bg-rust-soft px-3 py-2 text-sm text-rust">{error}</p>}
            <button className="btn-primary w-full py-2.5" disabled={busy || !/^\S+@\S+\.\S+$/.test(email)}>{busy ? 'Sending…' : 'Send code'}</button>
          </form>
        ) : (
          <form onSubmit={reset} className="space-y-4" noValidate>
            <p className="text-sm text-ink-soft">If <strong>{email}</strong> has an account, a code is on its way. It expires in 10 minutes.</p>
            <Field label="Code" htmlFor="fp-code"><CodeInput id="fp-code" value={code} onChange={setCode} /></Field>
            <Field label="New password" htmlFor="fp-pw" hint="At least 8 characters, mixing letters with numbers or symbols.">
              <input id="fp-pw" type="password" autoComplete="new-password" className="input" value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
            <Field label="Confirm new password" htmlFor="fp-pw2">
              <input id="fp-pw2" type="password" autoComplete="new-password" className="input" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            </Field>
            {error && <p role="alert" className="rounded-lg bg-rust-soft px-3 py-2 text-sm text-rust">{error}</p>}
            <button className="btn-primary w-full py-2.5" disabled={busy || code.length !== 6 || !password}>{busy ? 'Saving…' : setting ? 'Set password' : 'Change password'}</button>
            <div className="flex justify-end"><ResendCode onResend={() => api.post('/api/auth/password/forgot', { email: email.trim() })} /></div>
          </form>
        )}
        {!user && <p className="mt-6 text-center text-sm text-muted">Remembered it? <Link to="/login" className="link">Sign in</Link></p>}
      </div>
    </div>
  )
}
