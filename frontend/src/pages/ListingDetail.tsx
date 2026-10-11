import { Flag, Heart, MapPin, MessageCircle, Pencil, Scale, ShieldAlert, Trash2, Truck } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { ConditionBadge, PriceEstimateCard, StatusBadge, VerdictBadge } from '../components/marketplace'
import { ReportDialog } from '../components/ReportDialog'
import { Badge, ErrorState, Notice, SampleBadge, Skeleton, Spinner } from '../components/ui'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import type { Inquiry, Listing, PriceEstimate, PriceVerdict } from '../types'
import { CONDITION_HELP, date, money, relativeTime } from '../utils/format'

interface Detail { listing: Listing; my_inquiries: Inquiry[]; disclaimer: string }
interface CompareRow { listing_id: number; condition: string; price: number; currency: string; total_known_cost: number | null; total_cost_complete: boolean; seller: string; is_sample: boolean; quality: { score: number; flags: string[] }; price_verdict: PriceVerdict; delivery: string; location: string | null }

export default function ListingDetail() {
  const { id } = useParams()
  const { user } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const detail = useApi(() => api.get<Detail>(`/api/marketplace/listings/${id}`), [id, user?.id])
  const [img, setImg] = useState(0)
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [reporting, setReporting] = useState(false)
  const [estimate, setEstimate] = useState<{ estimate: PriceEstimate; asking_price_verdict: PriceVerdict | null } | null>(null)
  const [estimating, setEstimating] = useState(false)

  if (detail.loading) return <div className="grid gap-8 md:grid-cols-2"><Skeleton className="aspect-[4/5]" /><div className="space-y-3"><Skeleton className="h-10 w-3/4" /><Skeleton className="h-24" /></div></div>
  if (detail.error) return <ErrorState error={detail.error} onRetry={detail.reload} />
  const { listing: l, my_inquiries, disclaimer } = detail.data!
  const photos = l.images.length ? l.images.map((i) => i.url) : l.cover_url ? [l.cover_url] : []

  async function act(path: string, msg: string) {
    try {
      await api.post(`/api/marketplace/listings/${l.id}/${path}`)
      toast.success(msg)
      detail.reload()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function remove() {
    if (!confirm('Delete this listing permanently? Photos and messages will be removed.')) return
    await api.del(`/api/marketplace/listings/${l.id}`)
    toast.info('Listing deleted.')
    navigate('/seller')
  }

  async function favorite() {
    if (!user) return navigate(`/login?next=/marketplace/listings/${l.id}`)
    if (l.is_favorite) await api.del(`/api/marketplace/listings/${l.id}/favorite`)
    else await api.post(`/api/marketplace/listings/${l.id}/favorite`)
    detail.reload()
  }

  async function sendInquiry(e: FormEvent) {
    e.preventDefault()
    setSending(true)
    try {
      await api.post(`/api/marketplace/listings/${l.id}/inquiries`, { message: message.trim() })
      setMessage('')
      toast.success('Message sent. The seller’s reply will appear here and under Saved → Messages.')
      detail.reload()
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setSending(false)
    }
  }

  async function checkPrice() {
    setEstimating(true)
    try {
      setEstimate(await api.post('/api/marketplace/estimate-price', {
        isbn: l.isbn, title: l.title, author: l.author, condition: l.condition, asking_price: l.price_amount,
        currency: l.currency, exclude_listing_id: l.id,
      }))
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setEstimating(false)
    }
  }

  return (
    <div className="space-y-10">
      <nav className="text-sm text-muted"><Link to="/marketplace" className="hover:text-ink">Marketplace</Link> / <span>{l.title}</span></nav>
      {l.status !== 'active' && (
        <Notice tone="warn" title={l.status === 'sold' ? 'This book has been sold' : l.status === 'removed' ? 'Removed by a moderator' : 'This listing is inactive'}>
          {l.status === 'sold' ? `Marked sold ${date(l.sold_at)}.` : l.moderation_note ?? 'It isn’t visible in search and can’t receive messages.'}
        </Notice>
      )}
      <div className="grid gap-10 md:grid-cols-2">
        <div>
          <div className="aspect-[4/5] overflow-hidden rounded-2xl bg-parchment">
            {photos[img] ? <img src={photos[img]} alt={l.images.length ? `Seller photo ${img + 1} of ${l.title}` : `Catalogue cover of ${l.title}`} className="h-full w-full object-contain" /> : <div className="flex h-full items-center justify-center text-muted">No photos</div>}
          </div>
          {!l.images.length && <p className="mt-2 text-xs text-gold-dark">The seller hasn’t uploaded photos of this copy; the image is the catalogue cover.</p>}
          {l.images.length > 1 && (
            <div className="mt-3 flex gap-2">
              {l.images.map((im, i) => (
                <button key={im.id} onClick={() => setImg(i)} aria-label={`Show photo ${i + 1}`} className={`h-16 w-14 overflow-hidden rounded-lg border-2 ${i === img ? 'border-gold' : 'border-transparent'}`}>
                  <img src={im.url} alt="" className="h-full w-full object-cover" />
                </button>
              ))}
            </div>
          )}
          <p className="mt-2 text-xs text-muted">Photos are provided by the seller and don’t prove a book’s authenticity or condition.</p>
        </div>

        <div>
          <div className="flex flex-wrap gap-2"><ConditionBadge condition={l.condition} /><StatusBadge status={l.status} />{l.is_sample && <SampleBadge what="listing" />}</div>
          <h1 className="mt-3 font-serif text-3xl font-semibold leading-tight">{l.title}</h1>
          <p className="mt-1 text-ink-soft">{l.author}{l.edition_text ? ` · ${l.edition_text}` : ''}{l.published_year ? ` · ${l.published_year}` : ''}</p>
          {l.book_id && <Link to={`/books/${l.book_id}`} className="link mt-1 inline-block text-sm">About this book</Link>}

          <div className="card mt-5 p-5">
            <p className="text-3xl font-semibold">{money(l.price_amount, l.currency)}</p>
            <p className="mt-1 flex items-center gap-1.5 text-sm text-ink-soft"><Truck className="h-4 w-4" aria-hidden />
              {l.delivery === 'pickup' ? 'Pickup only' : l.delivery === 'both' ? 'Pickup or shipping' : 'Shipping'}
              {l.delivery !== 'pickup' && (l.shipping_known ? ` · shipping ${l.shipping_cost ? money(l.shipping_cost, l.currency) : 'free'}` : ' · shipping cost not stated')}
            </p>
            <p className="mt-1 text-sm">Total known cost: <strong>{money(l.total_known_cost, l.currency)}</strong>{!l.total_cost_complete && <span className="ml-1 text-xs text-gold-dark">(incomplete: shipping unknown)</span>}</p>
            {l.location_city && <p className="mt-1 flex items-center gap-1.5 text-sm text-ink-soft"><MapPin className="h-4 w-4" aria-hidden />{l.location_city}</p>}
            <p className="mt-3 text-xs text-muted">{CONDITION_HELP[l.condition]}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              {!l.is_mine && <button className="btn-outline" onClick={favorite} aria-pressed={l.is_favorite}><Heart className={`h-4 w-4 ${l.is_favorite ? 'fill-rust text-rust' : ''}`} aria-hidden />{l.is_favorite ? 'Saved' : 'Save'}</button>}
              <button className="btn-outline" onClick={checkPrice} disabled={estimating}><Scale className="h-4 w-4" aria-hidden />{estimating ? 'Checking…' : 'Is this a fair price?'}</button>
              {!l.is_mine && user && <button className="btn-ghost" onClick={() => setReporting(true)}><Flag className="h-4 w-4" aria-hidden />Report</button>}
            </div>
          </div>

          {estimate && (
            <div className="mt-4 space-y-2">
              {estimate.asking_price_verdict && <p className="text-sm"><VerdictBadge verdict={estimate.asking_price_verdict} /> <span className="ml-1">{estimate.asking_price_verdict.text}</span></p>}
              <PriceEstimateCard estimate={estimate.estimate} title="Typical asking price (excluding this listing)" />
            </div>
          )}

          {l.description && <div className="mt-6"><h2 className="text-lg font-semibold">Seller’s description</h2><p className="mt-1 whitespace-pre-line text-ink-soft">{l.description}</p></div>}
          <dl className="mt-6 grid grid-cols-2 gap-3 text-sm">
            <div><dt className="text-xs uppercase text-muted">ISBN</dt><dd>{l.isbn ?? 'Not provided'}</dd></div>
            <div><dt className="text-xs uppercase text-muted">Listed</dt><dd>{relativeTime(l.created_at)}</dd></div>
          </dl>

          <div className="card mt-6 flex items-center justify-between gap-3 p-4">
            <div>
              <p className="text-xs uppercase text-muted">Seller</p>
              <Link to={`/sellers/${l.seller.id}`} className="font-semibold hover:text-forest">{l.seller.display_name}</Link>
              <p className="text-xs text-muted">Member since {date(l.seller.member_since, { month: 'short', year: 'numeric' })} · {l.seller.completed_sales} completed sale{l.seller.completed_sales === 1 ? '' : 's'}</p>
            </div>
          </div>

          {l.is_mine ? (
            <div className="card mt-6 p-4">
              <p className="font-semibold">Manage your listing</p>
              <p className="text-xs text-muted">{l.view_count ?? 0} views · {l.inquiry_count ?? 0} messages · saved by {l.favorite_count ?? 0}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {l.status === 'active' && <Link to={`/sell/${l.id}/edit`} className="btn-outline btn-sm"><Pencil className="h-3.5 w-3.5" aria-hidden />Edit</Link>}
                {l.status === 'active' && <button className="btn-forest btn-sm" onClick={() => act('mark-sold', 'Marked as sold.')}>Mark sold</button>}
                {l.status === 'active' && <button className="btn-outline btn-sm" onClick={() => act('deactivate', 'Listing hidden.')}>Deactivate</button>}
                {(l.status === 'inactive' || l.status === 'sold') && <button className="btn-outline btn-sm" onClick={() => act('reactivate', 'Listing is active again.')}>Reactivate</button>}
                <button className="btn-danger btn-sm" onClick={remove}><Trash2 className="h-3.5 w-3.5" aria-hidden />Delete</button>
              </div>
            </div>
          ) : (
            <div className="mt-6">
              <h2 className="flex items-center gap-2 text-lg font-semibold"><MessageCircle className="h-5 w-5" aria-hidden />Contact the seller</h2>
              {my_inquiries.map((q) => (
                <div key={q.id} className="mt-3 space-y-2 text-sm">
                  <p className="rounded-xl rounded-tr-sm bg-parchment px-3 py-2"><span className="text-xs text-muted">You · {relativeTime(q.created_at)}</span><br />{q.message}</p>
                  {q.seller_reply ? <p className="rounded-xl rounded-tl-sm border border-forest/30 bg-forest-soft px-3 py-2"><span className="text-xs text-muted">Seller · {relativeTime(q.replied_at)}</span><br />{q.seller_reply}</p>
                    : <p className="text-xs text-muted">Waiting for the seller’s reply.</p>}
                </div>
              ))}
              {l.status !== 'active' ? <p className="mt-2 text-sm text-muted">Messaging is closed for this listing.</p>
                : !l.allow_inquiries ? <p className="mt-2 text-sm text-muted">The seller isn’t accepting messages for this listing.</p>
                  : !user ? <p className="mt-2 text-sm"><Link to={`/login?next=/marketplace/listings/${l.id}`} className="link">Log in</Link> to message the seller.</p>
                    : (
                      <form onSubmit={sendInquiry} className="mt-3 space-y-2">
                        <label htmlFor="inq" className="sr-only">Message to seller</label>
                        <textarea id="inq" className="input" rows={3} minLength={5} maxLength={1500} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Hi! Is this still available? Could we meet near…" />
                        <p className="text-xs text-muted">Your email is never shared. Only the seller sees your message, and only you see their reply.</p>
                        <button className="btn-primary" disabled={sending || message.trim().length < 5}>{sending ? 'Sending…' : 'Send message'}</button>
                      </form>
                    )}
            </div>
          )}
          <p className="mt-6 flex gap-2 rounded-xl bg-parchment px-3 py-2 text-xs text-ink-soft"><ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />{disclaimer}</p>
        </div>
      </div>
      <SameBook listing={l} />
      {reporting && <ReportDialog open onClose={() => setReporting(false)} endpoint={`/api/marketplace/listings/${l.id}/report`} what="listing" />}
    </div>
  )
}

function SameBook({ listing }: { listing: Listing }) {
  const others = useApi(() => api.get<Listing[]>(`/api/marketplace/listings/${listing.id}/same-book`), [listing.id])
  const ids = [listing.id, ...(others.data ?? []).map((o) => o.id)].slice(0, 6)
  const cmp = useApi(() => api.post<{ rows: CompareRow[]; suggestion: { listing_id: number; text: string } | null }>('/api/marketplace/compare-listings', { listing_ids: ids }), [ids.join(',')], ids.length >= 2)
  if (others.loading || !others.data?.length) return null
  return (
    <section aria-labelledby="same-book">
      <h2 id="same-book" className="section-title">Other copies of this book</h2>
      <p className="mt-1 text-sm text-muted">Compared on total known cost, condition, listing completeness and typical price.</p>
      {cmp.loading ? <Spinner className="mt-4" /> : cmp.data && (
        <div className="mt-4 overflow-x-auto rounded-xl border border-line bg-paper">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="border-b border-line text-xs uppercase tracking-wide text-muted"><tr><th className="p-3">Listing</th><th>Condition</th><th>Price</th><th>Total known</th><th>Price check</th><th>Completeness</th><th /></tr></thead>
            <tbody className="divide-y divide-line">
              {cmp.data.rows.map((r) => (
                <tr key={r.listing_id} className={r.listing_id === listing.id ? 'bg-gold-soft/50' : ''}>
                  <td className="p-3">{r.listing_id === listing.id ? 'This listing' : r.seller}{r.is_sample && <span className="ml-1 text-xs text-gold-dark">(sample)</span>}{cmp.data!.suggestion?.listing_id === r.listing_id && <Badge tone="forest">Suggested</Badge>}</td>
                  <td><ConditionBadge condition={r.condition} /></td>
                  <td>{money(r.price, r.currency)}</td>
                  <td>{money(r.total_known_cost, r.currency)}{!r.total_cost_complete && <span className="text-xs text-gold-dark"> +?</span>}</td>
                  <td><VerdictBadge verdict={r.price_verdict} /></td>
                  <td title={r.quality.flags.join('; ')}>{r.quality.score}/100</td>
                  <td className="pr-3">{r.listing_id !== listing.id && <Link to={`/marketplace/listings/${r.listing_id}`} className="link">View</Link>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {cmp.data?.suggestion && <p className="mt-2 text-xs text-muted">Suggestion: {cmp.data.suggestion.text}</p>}
    </section>
  )
}
