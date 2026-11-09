import { Scale, SearchX, Store } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { ListingCard } from '../components/marketplace'
import { EmptyState, ErrorState, Notice, PageHeader, Pagination, Skeleton } from '../components/ui'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { TTL, queryKey, useGet } from '../hooks/useApi'
import { api } from '../services/api'
import { invalidate, optimistic } from '../services/queryCache'
import type { Listing, Page } from '../types'
import { CONDITION_LABELS } from '../utils/format'

const SORTS = [['recent', 'Newest'], ['price_asc', 'Price: low to high'], ['price_desc', 'Price: high to low'], ['condition', 'Best condition']] as const

export default function Marketplace() {
  const { user, loading: authLoading } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const page = Math.max(1, Number(params.get('page')) || 1)
  const urlQ = params.get('q') ?? ''
  const [q, setQ] = useState(urlQ)
  useEffect(() => setQ(urlQ), [urlQ])
  const query = { ...Object.fromEntries(params.entries()), page_size: 20 }
  const listings = useGet<Page<Listing>>('/api/marketplace/listings', query, { userId: user?.id, ttl: TTL.short, keepPrevious: true, paused: authLoading })

  function update(changes: Record<string, string | null>) {
    if (Object.entries(changes).every(([k, v]) => (params.get(k) ?? null) === (v || null))) return
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(changes)) {
      if (v) next.set(k, v)
      else next.delete(k)
    }
    if (!('page' in changes)) next.delete('page')
    setParams(next)
  }

  async function toggleFavorite(l: Listing) {
    if (!user) return navigate('/login?next=/marketplace')
    try {
      await optimistic<Page<Listing>, void>(queryKey('/api/marketplace/listings', query, user.id),
        (d) => ({ ...d, items: d.items.map((x) => (x.id === l.id ? { ...x, is_favorite: !l.is_favorite } : x)) }),
        () => (l.is_favorite ? api.del(`/api/marketplace/listings/${l.id}/favorite`) : api.post(`/api/marketplace/listings/${l.id}/favorite`)))
      invalidate('/api/marketplace/favorites')
      toast.success(l.is_favorite ? 'Removed from saved listings.' : 'Saved. Find it under Saved.')
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  return (
    <div>
      <PageHeader eyebrow="Second-hand marketplace" title="Used books from readers near you"
        actions={<><Link to="/marketplace/find" className="btn-outline"><Scale className="h-4 w-4" aria-hidden />Find a fair deal</Link><Link to="/sell" className="btn-forest"><Store className="h-4 w-4" aria-hidden />Sell a book</Link></>}>
        Browse community listings, message sellers privately and arrange the handover yourselves.
      </PageHeader>
      <Notice tone="info">BookWorm doesn’t process payments, hold funds or guarantee transactions, and doesn’t verify every seller or book. Inspect the copy before paying.</Notice>

      <form onSubmit={(e: FormEvent) => { e.preventDefault(); update({ q: q.trim() || null }) }} className="mt-6 grid gap-3 md:grid-cols-[1fr_auto_auto_auto_auto]" role="search">
        <label htmlFor="mk-q" className="sr-only">Search listings</label>
        <input id="mk-q" className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Title, author or ISBN" />
        <select aria-label="Minimum condition" className="input" value={params.get('min_condition') ?? ''} onChange={(e) => update({ min_condition: e.target.value || null })}>
          <option value="">Any condition</option>
          {['like_new', 'very_good', 'good', 'acceptable'].map((c) => <option key={c} value={c}>{CONDITION_LABELS[c]}{c !== 'like_new' ? ' or better' : ''}</option>)}
        </select>
        <input aria-label="Maximum price" key={`max-${params.get('max_price') ?? ''}`} type="number" min={1} className="input md:w-32" placeholder="Max price" defaultValue={params.get('max_price') ?? ''} onBlur={(e) => update({ max_price: e.target.value || null })} />
        <input aria-label="City" key={`city-${params.get('location') ?? ''}`} className="input md:w-36" placeholder="City" defaultValue={params.get('location') ?? ''} onBlur={(e) => update({ location: e.target.value.trim() || null })} />
        <button className="btn-primary">Search</button>
      </form>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-2 text-sm" role="group" aria-label="Delivery">
          {[['any', 'Any delivery'], ['pickup', 'Pickup'], ['shipping', 'Shipping']].map(([v, l]) => (
            <button key={v} className={`chip ${(params.get('delivery') ?? 'any') === v ? 'border-ink bg-ink text-paper' : ''}`} onClick={() => update({ delivery: v === 'any' ? null : v })}>{l}</button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm"><span className="text-muted">Sort</span>
          <select className="input w-auto py-1.5" value={params.get('sort') ?? 'recent'} onChange={(e) => update({ sort: e.target.value })}>
            {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
      </div>

      <div className="mt-6" aria-live="polite">
        {listings.loading ? (
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-80" />)}</div>
        ) : listings.error || !listings.data ? <ErrorState error={listings.error} onRetry={listings.reload} /> : listings.data.items.length === 0 ? (
          <EmptyState icon={<SearchX className="h-6 w-6" />} title="No listings match" action={<Link to="/sell" className="btn-forest">List your copy</Link>}>
            Try fewer filters, or use “Find a fair deal” to include external marketplaces.
          </EmptyState>
        ) : (
          <>
            <p className="mb-3 text-sm text-muted">{listings.data.total} active listing{listings.data.total === 1 ? '' : 's'}</p>
            <div className={`grid grid-cols-2 gap-4 transition-opacity md:grid-cols-3 lg:grid-cols-4 ${listings.refreshing ? 'opacity-60' : ''}`}>
              {listings.data.items.map((l) => <ListingCard key={l.id} listing={l} onFavorite={toggleFavorite} />)}
            </div>
            <Pagination page={page} total={listings.data.total} pageSize={20} onPage={(p) => { update({ page: String(p) }); window.scrollTo({ top: 0 }) }} />
          </>
        )}
      </div>
    </div>
  )
}
