import { MapPin } from 'lucide-react'
import { useParams } from 'react-router'
import { ListingCard } from '../components/marketplace'
import { EmptyState, ErrorState, Spinner } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import type { Listing } from '../types'
import { date } from '../utils/format'

interface Seller { id: number; display_name: string; bio: string | null; avatar_url: string | null; location_city: string | null; member_since: string; active_listings: number; sold_listings: number; is_demo: boolean }

export default function SellerProfile() {
  const { id } = useParams()
  const data = useApi(() => api.get<{ seller: Seller; listings: Listing[] }>(`/api/marketplace/sellers/${id}`), [id])
  if (data.loading) return <Spinner />
  if (data.error) return <ErrorState error={data.error} onRetry={data.reload} />
  const { seller: s, listings } = data.data!
  return (
    <div>
      <header className="card flex flex-col gap-5 p-6 sm:flex-row sm:items-center">
        {s.avatar_url ? <img src={s.avatar_url} alt="" className="h-20 w-20 rounded-full object-cover" />
          : <span className="flex h-20 w-20 items-center justify-center rounded-full bg-gold-soft font-serif text-3xl text-gold-dark">{s.display_name[0]?.toUpperCase()}</span>}
        <div className="flex-1">
          <h1 className="font-serif text-3xl font-semibold">{s.display_name}</h1>
          <p className="mt-1 flex flex-wrap gap-x-4 text-sm text-muted">
            <span>Member since {date(s.member_since, { month: 'long', year: 'numeric' })}</span>
            {s.location_city && <span className="inline-flex items-center gap-1"><MapPin className="h-3.5 w-3.5" aria-hidden />{s.location_city}</span>}
            <span>{s.active_listings} active · {s.sold_listings} sold</span>
          </p>
          {s.bio && <p className="mt-3 max-w-2xl text-ink-soft">{s.bio}</p>}
          <p className="mt-2 text-xs text-muted">Only information the seller chose to make public is shown. Sales counts are self-reported by marking listings sold.</p>
        </div>
      </header>
      <h2 className="mt-10 section-title">Books for sale</h2>
      <div className="mt-5">
        {listings.filter((l) => l.status === 'active').length === 0 ? <EmptyState title="No active listings">Check back later.</EmptyState> : (
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4">
            {listings.filter((l) => l.status === 'active').map((l) => <ListingCard key={l.id} listing={l} />)}
          </div>
        )}
      </div>
    </div>
  )
}
