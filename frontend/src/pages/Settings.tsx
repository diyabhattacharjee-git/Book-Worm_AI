import { Camera, ShieldAlert } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { Field, Modal, Notice, PageHeader } from '../components/ui'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { api } from '../services/api'
import type { User } from '../types'

export default function Settings() {
  const { user, setUser, logout } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const u = user!
  const [profile, setProfile] = useState({ username: u.username ?? '', display_name: u.display_name, bio: u.bio ?? '', location_city: u.location_city ?? '', location_public: u.location_public, allow_inquiries: u.allow_inquiries, contact_note: u.contact_note ?? '' })
  const [pw, setPw] = useState({ current_password: '', new_password: '' })
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deletePw, setDeletePw] = useState('')
  const [deleteName, setDeleteName] = useState('')

  async function saveProfile(e: FormEvent) {
    e.preventDefault()
    try {
      setUser(await api.patch<User>('/api/users/me', { ...profile, username: profile.username.trim().toLowerCase() || undefined, bio: profile.bio || null, location_city: profile.location_city || null, contact_note: profile.contact_note || null }))
      toast.success('Profile saved.')
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  async function avatar(file: File | undefined) {
    if (!file) return
    try {
      setUser(await api.upload<User>('/api/users/me/avatar', file))
      toast.success('Profile photo updated.')
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  async function changePassword(e: FormEvent) {
    e.preventDefault()
    try {
      await api.post('/api/users/me/password', pw)
      setPw({ current_password: '', new_password: '' })
      toast.success('Password changed. Other sessions were signed out.')
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  async function privacy(action: 'reset' | 'history' | 'everywhere') {
    const prompts = {
      reset: 'Reset learned preferences? Views, saves, dismissals, searches and onboarding answers will be removed. Ratings and your shelf stay.',
      history: 'Delete your reading history? Your bookshelf, interactions, searches and assistant chats will be permanently removed.',
      everywhere: 'Sign out of every device, including this one?',
    }
    if (!confirm(prompts[action])) return
    try {
      if (action === 'reset') { await api.post('/api/users/me/reset-recommendations'); toast.success('Learned preferences reset.') }
      if (action === 'history') { await api.del('/api/users/me/reading-history'); toast.success('Reading history deleted.') }
      if (action === 'everywhere') { await api.post('/api/auth/logout?everywhere=true'); await logout(); navigate('/login') }
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  async function deleteAccount() {
    try {
      await api.del('/api/users/me', u.has_password ? { password: deletePw } : { confirm_username: deleteName })
      setUser(null)
      toast.info('Your account and its data have been deleted.')
      navigate('/')
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <PageHeader eyebrow="Account" title="Profile & settings" />

      <form onSubmit={saveProfile} className="card space-y-4 p-6">
        <h2 className="text-xl font-semibold">Public profile</h2>
        <div className="flex items-center gap-4">
          {u.avatar_url ? <img src={u.avatar_url} alt="Your profile" className="h-16 w-16 rounded-full object-cover" /> : <span className="flex h-16 w-16 items-center justify-center rounded-full bg-gold-soft text-2xl text-gold-dark">{u.display_name[0]}</span>}
          <label className="btn-outline btn-sm cursor-pointer"><Camera className="h-4 w-4" aria-hidden />Change photo
            <input type="file" accept="image/jpeg,image/png,image/webp" className="sr-only" onChange={(e) => avatar(e.target.files?.[0])} />
          </label>
          {u.avatar_url && <button type="button" className="btn-ghost btn-sm" onClick={async () => setUser(await api.del<User>('/api/users/me/avatar'))}>Remove</button>}
        </div>
        <Field label="Username" htmlFor="un" hint="Used to sign in. Letters, numbers, dots and underscores.">
          <input id="un" className="input" maxLength={30} value={profile.username} onChange={(e) => setProfile({ ...profile, username: e.target.value })} />
        </Field>
        <Field label="Display name" htmlFor="dn"><input id="dn" className="input" maxLength={60} value={profile.display_name} onChange={(e) => setProfile({ ...profile, display_name: e.target.value })} /></Field>
        <Field label="Bio" htmlFor="bio"><textarea id="bio" className="input" rows={3} maxLength={500} value={profile.bio} onChange={(e) => setProfile({ ...profile, bio: e.target.value })} /></Field>
        <Field label="Approximate location" htmlFor="loc" hint="City or area only. Used as the default for new listings.">
          <input id="loc" className="input" maxLength={80} value={profile.location_city} onChange={(e) => setProfile({ ...profile, location_city: e.target.value })} />
        </Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={profile.location_public} onChange={(e) => setProfile({ ...profile, location_public: e.target.checked })} />Show my city on my public seller profile</label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={profile.allow_inquiries} onChange={(e) => setProfile({ ...profile, allow_inquiries: e.target.checked })} />Allow buyers to message me</label>
        <Field label="Private contact note" htmlFor="cn" hint="Never shown publicly. Keep it as a reminder of what you’re happy to share when replying to buyers.">
          <input id="cn" className="input" maxLength={200} value={profile.contact_note} onChange={(e) => setProfile({ ...profile, contact_note: e.target.value })} />
        </Field>
        <p className="text-sm text-muted">Email: {u.email}{u.email_verified ? ' (verified)' : ''} — never shown to other users</p>
        <button className="btn-primary">Save profile</button>
      </form>

      <section className="card p-6">
        <h2 className="text-xl font-semibold">Reading preferences</h2>
        <p className="mt-1 text-sm text-muted">{u.preferences.favorite_genres.length ? `Favourite genres: ${u.preferences.favorite_genres.join(', ')}.` : 'You haven’t set any preferences.'}</p>
        <Link to="/for-you?onboarding=1" className="btn-outline mt-3">Edit preferences</Link>
      </section>

      {!u.has_password ? (
        <section className="card p-6">
          <h2 className="text-xl font-semibold">Password</h2>
          <p className="mt-1 text-sm text-muted">You sign in with Google or an email code. Add a password to also sign in with your username or email.</p>
          <Link to="/forgot-password?mode=set" className="btn-outline mt-3">Set a password</Link>
        </section>
      ) : (
      <form onSubmit={changePassword} className="card space-y-4 p-6">
        <h2 className="text-xl font-semibold">Password</h2>
        <Field label="Current password" htmlFor="cp"><input id="cp" type="password" autoComplete="current-password" className="input" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} /></Field>
        <Field label="New password" htmlFor="np" hint="At least 8 characters, mixing letters with numbers or symbols."><input id="np" type="password" autoComplete="new-password" className="input" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></Field>
        <button className="btn-primary" disabled={!pw.current_password || pw.new_password.length < 8}>Change password</button>
        <Link to="/forgot-password" className="link ml-3 text-sm">Forgot your current password?</Link>
      </form>
      )}

      <section className="card space-y-4 p-6">
        <h2 className="text-xl font-semibold">Privacy & data</h2>
        <p className="text-sm text-muted">Recommendations use your ratings, shelf, saves, dismissals and recent searches. We never infer sensitive personal attributes from what you read.</p>
        <div className="flex flex-wrap gap-2">
          <button className="btn-outline" onClick={() => privacy('reset')}>Reset learned preferences</button>
          <button className="btn-outline" onClick={() => privacy('history')}>Delete reading history</button>
          <button className="btn-outline" onClick={() => privacy('everywhere')}>Sign out everywhere</button>
        </div>
      </section>

      <section className="rounded-2xl border border-rust/30 bg-rust-soft/50 p-6">
        <h2 className="flex items-center gap-2 text-xl font-semibold text-rust"><ShieldAlert className="h-5 w-5" aria-hidden />Delete account</h2>
        <p className="mt-1 text-sm text-ink-soft">Permanently deletes your account, listings and photos, reviews, shelves, plans, conversations and messages. Reports you filed are kept without your name.</p>
        <button className="btn-danger mt-3" onClick={() => setDeleteOpen(true)}>Delete my account</button>
      </section>

      <Modal open={deleteOpen} onClose={() => setDeleteOpen(false)} title="Delete your account?"
        footer={<><button className="btn-ghost" onClick={() => setDeleteOpen(false)}>Cancel</button><button className="btn-danger" disabled={u.has_password ? !deletePw : deleteName !== u.username} onClick={deleteAccount}>Delete permanently</button></>}>
        <Notice tone="warn">This can’t be undone.</Notice>
        <div className="mt-3">{u.has_password
          ? <Field label="Confirm with your password" htmlFor="dpw"><input id="dpw" type="password" className="input" value={deletePw} onChange={(e) => setDeletePw(e.target.value)} /></Field>
          : <Field label={`Type your username (${u.username}) to confirm`} htmlFor="dun"><input id="dun" className="input" value={deleteName} onChange={(e) => setDeleteName(e.target.value)} /></Field>}</div>
      </Modal>
    </div>
  )
}
