import { Eye, MessageCircle, Package, Store } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { EbaySellerPanel, useEbayStatus } from '../components/ebay'
import { ConditionBadge, StatusBadge } from '../components/marketplace'
import { Badge, CharCounter, EmptyState, ErrorState, ListSkeleton, Notice, PageHeader, Tabs } from '../components/ui'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { TTL, queryKey, useGet } from '../hooks/useApi'
import { api } from '../services/api'
import { invalidate, optimistic } from '../services/queryCache'
import type { Inquiry, Listing } from '../types'
import { money, relativeTime } from '../utils/format'

interface Dashboard { listings: Listing[]; counts: Record<string, number>; total_views: number; open_inquiries: number; inquiries: Inquiry[]; disclaimer: string }
type Tab = 'active' | 'inactive' | 'sold' | 'removed' | 'messages' | 'ebay'
type ListingStatus = Listing['status']

export const DASHBOARD = '/api/marketplace/seller-dashboard'
const REPLY_MAX = 1500
const EBAY_RESULTS: Record<string, [string, 'success' | 'error' | 'info']> = {
  connected: ['Your eBay account is connected.', 'success'],
  denied: ['eBay connection was cancelled.', 'info'],
  failed: ['eBay couldn’t complete the connection. Please try again.', 'error'],
}

export default function SellerDashboard() {
  const { user } = useAuth()
  const toast = useToast()
  const dash = useGet<Dashboard>(DASHBOARD, undefined, { userId: user?.id, ttl: TTL.short })
  const ebay = useEbayStatus()
  const [params, setParams] = useSearchParams()
  const [tab, setTab] = useState<Tab>(params.get('tab') === 'ebay' ? 'ebay' : 'active')
  const [pending, setPending] = useState<Set<number>>(new Set())
  const key = queryKey(DASHBOARD, undefined, user?.id)

  useEffect(() => {
    const result = params.get('ebay')
    if (!result) return
    const message = EBAY_RESULTS[result]
    if (message) toast[message[1]](message[0])
    invalidate('/api/ebay/status')
    const next = new URLSearchParams(params)
    next.delete('ebay')
    next.delete('tab')
    setParams(next, { replace: true })
  }, [params, setParams, toast])

  async function act(l: Listing, path: string, status: ListingStatus, msg: string) {
    if (pending.has(l.id)) return
    setPending((p) => new Set(p).add(l.id))
    const previous = l.status
    try {
      await optimistic<Dashboard, Listing>(key, (d) => ({
        ...d,
        listings: d.listings.map((x) => (x.id === l.id ? { ...x, status } : x)),
        counts: { ...d.counts, [previous]: Math.max(0, (d.counts[previous] ?? 0) - 1), [status]: (d.counts[status] ?? 0) + 1 },
      }), () => api.post<Listing>(`/api/marketplace/listings/${l.id}/${path}`))
      toast.success(msg)
      invalidate('/api/marketplace/listings', '/api/ebay/status')
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setPending((p) => {
        const next = new Set(p)
        next.delete(l.id)
        return next
      })
    }
  }

  if (dash.loading) return <div><PageHeader eyebrow="Seller dashboard" title="Your listings" /><ListSkeleton rows={4} /></div>
  if (dash.error || !dash.data) return <ErrorState error={dash.error} onRetry={dash.reload} />
  const d = dash.data
  const listings = d.listings.filter((l) => l.status === tab)
  const showEbay = !!ebay.data?.market_check
  const publications = new Map((ebay.data?.publications ?? []).map((p) => [p.listing_id, p]))

  return (
    <div>
      <PageHeader eyebrow="Seller dashboard" title="Your listings" actions={<><Link to={`/sellers/${user!.id}`} className="btn-outline">Public profile</Link><Link to="/sell" className="btn-forest"><Store className="h-4 w-4" aria-hidden />New listing</Link></>}>
        Manage your copies, reply to buyers and mark books as sold.
      </PageHeader>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
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
          ...(showEbay ? [{ value: 'ebay' as Tab, label: 'eBay' }] : []),
        ]} />
        <div className="mt-6">
          {tab === 'ebay' ? <EbaySellerPanel listings={d.listings} />
            : tab === 'messages' ? <Messages inquiries={d.inquiries} onReplied={() => invalidate(DASHBOARD)} /> : listings.length === 0 ? (
              <EmptyState title={tab === 'active' ? 'No active listings' : `No ${tab} listings`} action={tab === 'active' ? <Link to="/sell" className="btn-forest">List a book</Link> : undefined}>
                {tab === 'active' ? 'Have a book you’ve finished? List it in under a minute.' : 'Nothing here yet.'}
              </EmptyState>
            ) : (
              <ul className="divide-y divide-line rounded-xl border border-line bg-paper">
                {listings.map((l) => (
                  <li key={l.id} className="flex flex-wrap items-center gap-4 p-4">
                    <div className="h-16 w-12 shrink-0 overflow-hidden rounded bg-parchment">{(l.images[0]?.url ?? l.cover_url) && <img src={l.images[0]?.url ?? l.cover_url!} alt="" loading="lazy" decoding="async" className="h-full w-full object-cover" />}</div>
                    <div className="min-w-0 flex-1 basis-48">
                      <Link to={`/marketplace/listings/${l.id}`} className="user-text font-semibold hover:text-forest">{l.title}</Link>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                        <ConditionBadge condition={l.condition} /><StatusBadge status={l.status} />
                        {publications.get(l.id)?.status === 'published' && <Badge tone="sky">On eBay</Badge>}
                        <span>{money(l.price_amount, l.currency)}</span><span>· {l.view_count ?? 0} views · {l.inquiry_count ?? 0} messages · saved by {l.favorite_count ?? 0}</span>
                        <span>· listed {relativeTime(l.created_at)}</span>{l.images.length === 0 && <span className="text-gold-dark">· no photos</span>}
                      </div>
                      {l.moderation_note && <p className="user-text mt-1 text-xs text-rust">Moderator note: {l.moderation_note}</p>}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {l.status === 'active' && <><Link to={`/sell/${l.id}/edit`} className="btn-outline btn-sm">Edit</Link>
                        <button className="btn-forest btn-sm" disabled={pending.has(l.id)} onClick={() => act(l, 'mark-sold', 'sold', 'Marked as sold.')}>Mark sold</button>
                        <button className="btn-ghost btn-sm" disabled={pending.has(l.id)} onClick={() => act(l, 'deactivate', 'inactive', 'Listing hidden.')}>Deactivate</button></>}
                      {(l.status === 'inactive' || l.status === 'sold') && <button className="btn-outline btn-sm" disabled={pending.has(l.id)} onClick={() => act(l, 'reactivate', 'active', 'Listing reactivated.')}>Reactivate</button>}
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
  const [sending, setSending] = useState<number | null>(null)

  async function reply(q: Inquiry, close = false) {
    const text = (drafts[q.id] ?? '').trim()
    if (!text || sending !== null) return
    setSending(q.id)
    try {
      await api.post(`/api/marketplace/inquiries/${q.id}/reply`, { reply: text, close })
      toast.success('Reply sent. Only this buyer can see it.')
      setDrafts((d) => ({ ...d, [q.id]: '' }))
      onReplied()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSending(null)
    }
  }
  if (!inquiries.length) return <EmptyState title="No messages yet">When buyers message you about a listing, they’ll appear here.</EmptyState>
  return (
    <ul className="space-y-4">
      {inquiries.map((q) => {
        const draft = drafts[q.id] ?? ''
        const invalid = !draft.trim() || draft.length > REPLY_MAX || sending !== null
        return (
          <li key={q.id} className="card p-4 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="min-w-0"><strong>{q.role === 'seller' ? q.buyer.display_name : q.seller.display_name}</strong> about <Link to={`/marketplace/listings/${q.listing_id}`} className="link">{q.listing_title}</Link></p>
              <span className="text-xs text-muted">{relativeTime(q.created_at)} · {q.status}</span>
            </div>
            <p className="user-text mt-2 rounded-lg bg-parchment px-3 py-2">{q.message}</p>
            {q.seller_reply && <div className="mt-2 rounded-lg border border-forest/30 bg-forest-soft px-3 py-2"><span className="text-xs text-muted">{q.role === 'seller' ? 'Your reply' : 'Seller replied'} · {relativeTime(q.replied_at)}</span><p className="user-text">{q.seller_reply}</p></div>}
            {q.role === 'seller' && q.status !== 'closed' && (
              <div className="mt-3 space-y-2">
                <label htmlFor={`r-${q.id}`} className="sr-only">Reply</label>
                <textarea id={`r-${q.id}`} className="input" rows={2} placeholder="Reply privately. Share contact details only if you want to." value={draft} onChange={(e) => setDrafts((d) => ({ ...d, [q.id]: e.target.value }))} />
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex gap-2"><button className="btn-primary btn-sm" disabled={invalid} onClick={() => reply(q)}>{sending === q.id ? 'Sending…' : 'Send reply'}</button><button className="btn-ghost btn-sm" disabled={invalid} onClick={() => reply(q, true)}>Reply & close</button></div>
                  <CharCounter value={draft.length} max={REPLY_MAX} warnAt={0.8} />
                </div>
              </div>
            )}
          </li>
        )
      })}
    </ul>
  )
}
