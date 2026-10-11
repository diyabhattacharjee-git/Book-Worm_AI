import { Mail } from 'lucide-react'
import { useCallback, useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router'
import { CodeInput, GoogleButton, ResendCode } from '../components/auth'
import { Field } from '../components/ui'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { api } from '../services/api'
import type { User } from '../types'

export function safeNext(next: string | null): string {
  // Only allow same-site relative paths (prevents open redirects).
  return next && next.startsWith('/') && !next.startsWith('//') ? next : '/for-you'
}

type Mode = 'password' | 'code-email' | 'code-enter'

export default function Login() {
  const { user, login, setUser } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [mode, setMode] = useState<Mode>('password')
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const next = safeNext(params.get('next'))

  const done = useCallback((u: User) => {
    toast.success(`Welcome back, ${u.display_name}!`)
    navigate(next, { replace: true })
  }, [navigate, next, toast])

  if (user) return <Navigate to={next} replace />

  async function run(fn: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const submitPassword = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => done(await login(identifier.trim(), password)))
  }
  const sendCode = () => run(async () => {
    await api.post('/api/auth/login/code/start', { email: email.trim() })
    setMode('code-enter')
  })
  const submitCode = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      const u = await api.post<User>('/api/auth/login/code/verify', { email: email.trim(), code })
      setUser(u)
      done(u)
    })
  }

  return (
    <div className="mx-auto max-w-md">
      <div className="card p-8">
        <h1 className="text-3xl font-semibold">Welcome back</h1>
        <p className="mt-1 mb-6 text-sm text-muted">Sign in to see your shelf, recommendations and listings.</p>

        <GoogleButton onSignedIn={done} />

        {mode === 'password' && (
          <form onSubmit={submitPassword} className="space-y-4" noValidate>
            <Field label="Username or email" htmlFor="identifier">
              <input id="identifier" autoComplete="username" required className="input" value={identifier} onChange={(e) => setIdentifier(e.target.value)} />
            </Field>
            <Field label="Password" htmlFor="password">
              <input id="password" type="password" autoComplete="current-password" required className="input" value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
            <div className="flex justify-end"><Link to="/forgot-password" className="link text-sm">Forgot password?</Link></div>
            {error && <p role="alert" className="rounded-lg bg-rust-soft px-3 py-2 text-sm text-rust">{error}</p>}
            <button className="btn-primary w-full py-2.5" disabled={busy || !identifier || !password}>{busy ? 'Signing in…' : 'Sign in'}</button>
            <button type="button" className="btn-outline w-full" onClick={() => { setMode('code-email'); setError(null) }}>
              <Mail className="h-4 w-4" aria-hidden />Email me a sign-in code instead
            </button>
          </form>
        )}

        {mode === 'code-email' && (
          <form onSubmit={(e) => { e.preventDefault(); void sendCode() }} className="space-y-4" noValidate>
            <Field label="Email" htmlFor="code-email" hint="We’ll email you a 6-digit code to sign in without a password.">
              <input id="code-email" type="email" autoComplete="email" className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            {error && <p role="alert" className="rounded-lg bg-rust-soft px-3 py-2 text-sm text-rust">{error}</p>}
            <button className="btn-primary w-full py-2.5" disabled={busy || !/^\S+@\S+\.\S+$/.test(email)}>{busy ? 'Sending…' : 'Send code'}</button>
            <button type="button" className="btn-ghost w-full" onClick={() => setMode('password')}>Use my password instead</button>
          </form>
        )}

        {mode === 'code-enter' && (
          <form onSubmit={submitCode} className="space-y-4" noValidate>
            <p className="text-sm text-ink-soft">If <strong>{email}</strong> has an account, a 6-digit code is on its way. It expires in 10 minutes.</p>
            <Field label="Sign-in code" htmlFor="login-code"><CodeInput id="login-code" value={code} onChange={setCode} /></Field>
            {error && <p role="alert" className="rounded-lg bg-rust-soft px-3 py-2 text-sm text-rust">{error}</p>}
            <button className="btn-primary w-full py-2.5" disabled={busy || code.length !== 6}>{busy ? 'Checking…' : 'Sign in'}</button>
            <div className="flex items-center justify-between">
              <button type="button" className="link text-sm" onClick={() => { setMode('code-email'); setCode('') }}>Use a different email</button>
              <ResendCode onResend={() => api.post('/api/auth/login/code/start', { email: email.trim() })} />
            </div>
          </form>
        )}

        <p className="mt-6 text-center text-sm text-muted">New here? <Link to={`/register${params.get('next') ? `?next=${encodeURIComponent(next)}` : ''}`} className="link">Create an account</Link></p>
      </div>
    </div>
  )
}
