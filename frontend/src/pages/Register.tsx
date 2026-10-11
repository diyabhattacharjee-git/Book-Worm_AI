import { Check } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router'
import { CodeInput, GoogleButton, ResendCode } from '../components/auth'
import { Field } from '../components/ui'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { useDebounced } from '../hooks/useApi'
import { ApiError, api } from '../services/api'
import type { User } from '../types'
import { safeNext } from './Login'

type Step = 'email' | 'code' | 'details'
const STEPS: [Step, string][] = [['email', 'Email'], ['code', 'Verify'], ['details', 'Account']]

export default function Register() {
  const { user, setUser } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [step, setStep] = useState<Step>('email')
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [token, setToken] = useState('')
  const [form, setForm] = useState({ username: '', display_name: '', password: '', confirm: '' })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [usernameState, setUsernameState] = useState<{ ok: boolean; msg: string } | null>(null)
  const next = safeNext(params.get('next'))
  const dUsername = useDebounced(form.username, 400)

  const welcome = useCallback((u: User, isNew = true) => {
    toast.success(isNew ? `Welcome to BookWorm, ${u.display_name}!` : `Welcome back, ${u.display_name}!`)
    navigate(params.get('next') ? next : '/for-you?onboarding=1', { replace: true })
  }, [navigate, next, params, toast])

  useEffect(() => {
    if (step !== 'details' || dUsername.length < 3) { setUsernameState(null); return }
    let live = true
    api.get<{ available: boolean; reason: string | null }>('/api/auth/username-available', { username: dUsername })
      .then((r) => { if (live) setUsernameState({ ok: r.available, msg: r.available ? 'Available' : (r.reason ?? 'Not available') }) })
      .catch(() => undefined)
    return () => { live = false }
  }, [dUsername, step])

  if (user) return <Navigate to={next} replace />

  async function run(fn: () => Promise<void>) {
    setBusy(true)
    setErrors({})
    try {
      await fn()
    } catch (err) {
      if (err instanceof ApiError && err.fieldErrors.length) setErrors(Object.fromEntries(err.fieldErrors.map((f) => [f.field || 'form', f.message])))
      else setErrors({ form: (err as Error).message })
    } finally {
      setBusy(false)
    }
  }

  const sendCode = (e?: FormEvent) => {
    e?.preventDefault()
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) { setErrors({ email: 'Enter a valid email address.' }); return }
    void run(async () => {
      await api.post('/api/auth/signup/start', { email: email.trim() })
      setStep('code')
    })
  }

  const verify = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      const r = await api.post<{ verification_token: string }>('/api/auth/signup/verify', { email: email.trim(), code })
      setToken(r.verification_token)
      setStep('details')
    })
  }

  function validate(): Record<string, string> {
    const e: Record<string, string> = {}
    if (!/^[a-z0-9][a-z0-9._]{1,28}[a-z0-9]$/.test(form.username.trim().toLowerCase())) e.username = '3–30 characters: letters, numbers, dots or underscores.'
    if (form.display_name.trim().length < 2) e.display_name = 'Enter at least 2 characters.'
    if (form.password.length < 8) e.password = 'Use at least 8 characters.'
    else if (/^\d+$/.test(form.password) || /^[a-zA-Z]+$/.test(form.password)) e.password = 'Mix letters with numbers or symbols.'
    if (form.confirm !== form.password) e.confirm = 'Passwords don’t match.'
    return e
  }

  const complete = (ev: FormEvent) => {
    ev.preventDefault()
    const e = validate()
    if (Object.keys(e).length) { setErrors(e); return }
    void run(async () => {
      const u = await api.post<User>('/api/auth/signup/complete', {
        verification_token: token, username: form.username.trim().toLowerCase(), display_name: form.display_name.trim(), password: form.password,
      })
      setUser(u)
      welcome(u)
    })
  }

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value })
  const stepIndex = STEPS.findIndex(([s]) => s === step)

  return (
    <div className="mx-auto max-w-md">
      <div className="card p-8">
        <h1 className="text-3xl font-semibold">Create your account</h1>
        <p className="mt-1 text-sm text-muted">One free account to read, review, buy and sell.</p>

        <ol className="mt-5 mb-6 flex items-center gap-2 text-xs" aria-label="Sign-up progress">
          {STEPS.map(([s, label], i) => (
            <li key={s} className="flex flex-1 items-center gap-2" aria-current={s === step ? 'step' : undefined}>
              <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold ${i < stepIndex ? 'border-forest bg-forest text-paper' : i === stepIndex ? 'border-ink bg-ink text-paper' : 'border-line text-muted'}`}>
                {i < stepIndex ? <Check className="h-3 w-3" aria-hidden /> : i + 1}
              </span>
              <span className={i === stepIndex ? 'font-medium text-ink' : 'text-muted'}>{label}</span>
              {i < STEPS.length - 1 && <span className="h-px flex-1 bg-line" />}
            </li>
          ))}
        </ol>

        {step === 'email' && (
          <>
            <GoogleButton onSignedIn={(u) => welcome(u, false)} />
            <form onSubmit={sendCode} className="space-y-4" noValidate>
              <Field label="Email" htmlFor="email" error={errors.email} hint="We’ll send a 6-digit code to verify it. Never shown publicly.">
                <input id="email" type="email" autoComplete="email" className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
              </Field>
              {errors.form && <p role="alert" className="rounded-lg bg-rust-soft px-3 py-2 text-sm text-rust">{errors.form}</p>}
              <button className="btn-primary w-full py-2.5" disabled={busy}>{busy ? 'Sending code…' : 'Send verification code'}</button>
            </form>
          </>
        )}

        {step === 'code' && (
          <form onSubmit={verify} className="space-y-4" noValidate>
            <p className="text-sm text-ink-soft">We sent a 6-digit code to <strong>{email}</strong>. It expires in 10 minutes. Check your spam folder if you don’t see it.</p>
            <Field label="Verification code" htmlFor="signup-code" error={errors.code}><CodeInput id="signup-code" value={code} onChange={setCode} /></Field>
            {errors.form && <p role="alert" className="rounded-lg bg-rust-soft px-3 py-2 text-sm text-rust">{errors.form}</p>}
            <button className="btn-primary w-full py-2.5" disabled={busy || code.length !== 6}>{busy ? 'Verifying…' : 'Verify email'}</button>
            <div className="flex items-center justify-between">
              <button type="button" className="link text-sm" onClick={() => { setStep('email'); setCode('') }}>Change email</button>
              <ResendCode onResend={async () => { await api.post('/api/auth/signup/start', { email: email.trim() }); toast.info('A new code is on its way.') }} />
            </div>
          </form>
        )}

        {step === 'details' && (
          <form onSubmit={complete} className="space-y-4" noValidate>
            <p className="rounded-lg bg-forest-soft px-3 py-2 text-sm text-forest-dark"><Check className="mr-1 inline h-4 w-4" aria-hidden />{email} verified. Now choose how you’ll sign in.</p>
            <Field label="Username" htmlFor="username" error={errors.username}
              hint={usernameState ? <span className={usernameState.ok ? 'text-forest' : 'text-rust'}>{usernameState.msg}</span> : 'You’ll use this (or your email) to sign in.'}>
              <input id="username" autoComplete="username" className="input" value={form.username} onChange={set('username')} maxLength={30} />
            </Field>
            <Field label="Display name" htmlFor="name" error={errors.display_name} hint="Shown on your reviews and listings.">
              <input id="name" autoComplete="nickname" className="input" value={form.display_name} onChange={set('display_name')} maxLength={60} />
            </Field>
            <Field label="Password" htmlFor="password" error={errors.password} hint="At least 8 characters, mixing letters with numbers or symbols.">
              <input id="password" type="password" autoComplete="new-password" className="input" value={form.password} onChange={set('password')} />
            </Field>
            <Field label="Confirm password" htmlFor="confirm" error={errors.confirm}>
              <input id="confirm" type="password" autoComplete="new-password" className="input" value={form.confirm} onChange={set('confirm')} />
            </Field>
            {errors.form && <p role="alert" className="rounded-lg bg-rust-soft px-3 py-2 text-sm text-rust">{errors.form}</p>}
            <button className="btn-primary w-full py-2.5" disabled={busy || usernameState?.ok === false}>{busy ? 'Creating account…' : 'Create account'}</button>
          </form>
        )}

        <p className="mt-6 text-center text-sm text-muted">Already have an account? <Link to="/login" className="link">Sign in</Link></p>
      </div>
    </div>
  )
}
