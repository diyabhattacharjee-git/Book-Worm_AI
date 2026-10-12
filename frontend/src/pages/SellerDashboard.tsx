import { Eye, MessageCircle, Package, Store } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { ConditionBadge, StatusBadge } from '../components/marketplace'
import { EmptyState, ErrorState, Notice, PageHeader, Spinner, Tabs } from '../components/ui'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import type { Inquiry, Listing } from '../types'
import { money, relativeTime } from '../utils/format'

interface Dashboard { listings: Listing[]; counts: Record<string, number>; total_views: number; open_inquiries: number; inquiries: Inquiry[]; disclaimer: string }

export default function SellerDashboard() {
  const { user } = useAuth()
  const toast = useToast()
  const dash = useApi(() => api.get<Dashboard>('/api/marketplace/seller-dashboard'), [])
  const [tab, setTab] = useState<'active' | 'inactive' | 'sold' | 'removed' | 'messages'>('active')

  async function act(id: number, path: string, msg: string) {
    try {
      await api.post(`/api/marketplace/listings/${id}/${path}`)
      toast.success(msg)
      dash.reload()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  if (dash.loading) return <Spinner />
  if (dash.error) return <ErrorState error={dash.error} onRetry={dash.reload} />
  const d = dash.data!
  const listings = d.listings.filter((l) => l.status === tab)

  return (
    <div>
      <PageHeader eyebrow="Seller dashboard" title="Your listings" actions={<><Link to={`/sellers/${user!.id}`} className="btn-outline">Public profile</Link><Link to="/sell" className="btn-forest"><Store className="h-4 w-4" aria-hidden />New listing</Link></>}>
        Manage your copies, reply to buyers and mark books as sold.
      </PageHeader>
      <div className="grid gap-4 sm:grid-cols-4">
        <Stat icon={Package} label="Active" value={d.counts.active ?? 0} />
        <Stat icon={Package} label="Sold" value={d.counts.sold ?? 0} />
        <Stat icon={Eye} label="Total views" value={d.total_views} />
        <Stat icon={MessageCircle} label="Unanswered messages" value={d.open_inquiries} />
      </div>
      <div className="mt-8">
        <Tabs label="Listing status" value={tab} onChange={setTab} tabs={[
          { value: 'active', label: 'Active', count: d.counts.active ?? 0 }, { value: 'inactive', label: 'Inactive', count: d.counts.inactive ?? 0 },
          { value: 'sold', label: 'Sold', count: d.counts.sold ?? 0 }, { value: 'removed', label: 'Removed', count: d.counts.removed ?? 0 },
          { value: 'messages', label: 'Messages', count: d.inquiries.length },
        ]} />
        <div className="mt-6">
          {tab === 'messages' ? <Messages inquiries={d.inquiries} onReplied={dash.reload} /> : listings.length === 0 ? (
            <EmptyState title={tab === 'active' ? 'No active listings' : `No ${tab} listings`} action={tab === 'active' ? <Link to="/sell" className="btn-forest">List a book</Link> : undefined}>
              {tab === 'active' ? 'Have a book you’ve finished? List it in under a minute.' : 'Nothing here yet.'}
            </EmptyState>
          ) : (
            <ul className="divide-y divide-line rounded-xl border border-line bg-paper">
              {listings.map((l) => (
                <li key={l.id} className="flex flex-wrap items-center gap-4 p-4">
                  <div className="h-16 w-12 shrink-0 overflow-hidden rounded bg-parchment">{(l.images[0]?.url ?? l.cover_url) && <img src={l.images[0]?.url ?? l.cover_url!} alt="" className="h-full w-full object-cover" />}</div>
                  <div className="min-w-0 flex-1">
                    <Link to={`/marketplace/listings/${l.id}`} className="font-semibold hover:text-forest">{l.title}</Link>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                      <ConditionBadge condition={l.condition} /><StatusBadge status={l.status} />
                      <span>{money(l.price_amount, l.currency)}</span><span>· {l.view_count ?? 0} views · {l.inquiry_count ?? 0} messages · saved by {l.favorite_count ?? 0}</span>
                      <span>· listed {relativeTime(l.created_at)}</span>{l.images.length === 0 && <span className="text-gold-dark">· no photos</span>}
                    </div>
                    {l.moderation_note && <p className="mt-1 text-xs text-rust">Moderator note: {l.moderation_note}</p>}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {l.status === 'active' && <><Link to={`/sell/${l.id}/edit`} className="btn-outline btn-sm">Edit</Link>
                      <button className="btn-forest btn-sm" onClick={() => act(l.id, 'mark-sold', 'Marked as sold.')}>Mark sold</button>
                      <button className="btn-ghost btn-sm" onClick={() => act(l.id, 'deactivate', 'Listing hidden.')}>Deactivate</button></>}
                    {(l.status === 'inactive' || l.status === 'sold') && <button className="btn-outline btn-sm" onClick={() => act(l.id, 'reactivate', 'Listing reactivated.')}>Reactivate</button>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <div className="mt-8"><Notice tone="info">{d.disclaimer}</Notice></div>
    </div>
  )
}

function Stat({ icon: Icon, label, value }: { icon: typeof Eye; label: string; value: number }) {
  return (
    <div className="card p-4">
      <Icon className="h-5 w-5 text-gold-dark" aria-hidden />
      <p className="mt-2 text-2xl font-semibold">{value}</p>
      <p className="text-sm text-muted">{label}</p>
    </div>
  )
}

export function Messages({ inquiries, onReplied }: { inquiries: Inquiry[]; onReplied: () => void }) {
  const toast = useToast()
  const [drafts, setDrafts] = useState<Record<number, string>>({})
  async function reply(q: Inquiry, close = false) {
    const text = (drafts[q.id] ?? '').trim()
    if (!text) return
    try {
      await api.post(`/api/marketplace/inquiries/${q.id}/reply`, { reply: text, close })
      toast.success('Reply sent. Only this buyer can see it.')
      setDrafts({ ...drafts, [q.id]: '' })
      onReplied()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }
  if (!inquiries.length) return <EmptyState title="No messages yet">When buyers message you about a listing, they’ll appear here.</EmptyState>
  return (
    <ul className="space-y-4">
      {inquiries.map((q) => (
        <li key={q.id} className="card p-4 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p><strong>{q.role === 'seller' ? q.buyer.display_name : q.seller.display_name}</strong> about <Link to={`/marketplace/listings/${q.listing_id}`} className="link">{q.listing_title}</Link></p>
            <span className="text-xs text-muted">{relativeTime(q.created_at)} · {q.status}</span>
          </div>
          <p className="mt-2 rounded-lg bg-parchment px-3 py-2">{q.message}</p>
          {q.seller_reply && <p className="mt-2 rounded-lg border border-forest/30 bg-forest-soft px-3 py-2"><span className="text-xs text-muted">{q.role === 'seller' ? 'Your reply' : 'Seller replied'} · {relativeTime(q.replied_at)}</span><br />{q.seller_reply}</p>}
          {q.role === 'seller' && q.status !== 'closed' && (
            <div className="mt-3 space-y-2">
              <label htmlFor={`r-${q.id}`} className="sr-only">Reply</label>
              <textarea id={`r-${q.id}`} className="input" rows={2} maxLength={1500} placeholder="Reply privately. Share contact details only if you want to." value={drafts[q.id] ?? ''} onChange={(e) => setDrafts({ ...drafts, [q.id]: e.target.value })} />
              <div className="flex gap-2"><button className="btn-primary btn-sm" onClick={() => reply(q)}>Send reply</button><button className="btn-ghost btn-sm" onClick={() => reply(q, true)}>Reply & close</button></div>
            </div>
          )}
        </li>
      ))}
    </ul>
  )
}
