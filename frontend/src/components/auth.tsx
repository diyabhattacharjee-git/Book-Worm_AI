import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import type { User } from '../types'

interface GoogleIdApi {
  initialize: (opts: { client_id: string; callback: (r: { credential: string }) => void; ux_mode?: string }) => void
  renderButton: (el: HTMLElement, opts: Record<string, unknown>) => void
}
declare global {
  interface Window { google?: { accounts: { id: GoogleIdApi } } }
}

let gsiPromise: Promise<void> | null = null
function loadGsi(): Promise<void> {
  if (window.google?.accounts?.id) return Promise.resolve()
  gsiPromise ??= new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = 'https://accounts.google.com/gsi/client'
    s.async = true
    s.onload = () => resolve()
    s.onerror = () => { gsiPromise = null; reject(new Error('Could not load Google sign-in')) }
    document.head.appendChild(s)
  })
  return gsiPromise
}

/** “Continue with Google”. Renders nothing when Google sign-in isn't enabled on the server. */
export function GoogleButton({ onSignedIn }: { onSignedIn: (u: User) => void }) {
  const config = useApi(() => api.get<{ google_client_id: string | null }>('/api/auth/config'), [])
  const ref = useRef<HTMLDivElement>(null)
  const toast = useToast()
  const { setUser } = useAuth()
  const clientId = config.data?.google_client_id
  const onSignedInRef = useRef(onSignedIn)
  useEffect(() => { onSignedInRef.current = onSignedIn }, [onSignedIn])

  useEffect(() => {
    if (!clientId || !ref.current) return
    let cancelled = false
    loadGsi().then(() => {
      if (cancelled || !ref.current || !window.google) return
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: async ({ credential }) => {
          try {
            const u = await api.post<User>('/api/auth/google', { credential })
            setUser(u)
            onSignedInRef.current(u)
          } catch (e) {
            toast.error((e as Error).message)
          }
        },
      })
      window.google.accounts.id.renderButton(ref.current, {
        theme: 'outline', size: 'large', text: 'continue_with', shape: 'pill', width: Math.min(360, ref.current.offsetWidth || 320),
      })
    }).catch(() => toast.error('Google sign-in could not be loaded.'))
    return () => { cancelled = true }
  }, [clientId, setUser, toast])

  if (!clientId) return null
  return (
    <div>
      <div ref={ref} className="flex justify-center" />
      <div className="my-5 flex items-center gap-3 text-xs uppercase tracking-wide text-muted">
        <span className="h-px flex-1 bg-line" />or<span className="h-px flex-1 bg-line" />
      </div>
    </div>
  )
}

/** Six-digit one-time code input. */
export function CodeInput({ value, onChange, id = 'otp' }: { value: string; onChange: (v: string) => void; id?: string }) {
  return (
    <input id={id} inputMode="numeric" autoComplete="one-time-code" maxLength={6} pattern="\d{6}"
      className="input text-center font-mono text-2xl tracking-[0.5em]" placeholder="••••••"
      value={value} onChange={(e) => onChange(e.target.value.replace(/\D/g, '').slice(0, 6))} />
  )
}

/** Resend link with a cooldown that matches the server's limit. */
export function ResendCode({ onResend, seconds = 60 }: { onResend: () => Promise<void>; seconds?: number }) {
  const [left, setLeft] = useState(seconds)
  useEffect(() => {
    if (left <= 0) return
    const t = window.setTimeout(() => setLeft((l) => l - 1), 1000)
    return () => window.clearTimeout(t)
  }, [left])
  return left > 0
    ? <span className="text-sm text-muted">Resend code in {left}s</span>
    : <button type="button" className="link text-sm" onClick={async () => { await onResend(); setLeft(seconds) }}>Resend code</button>
}
