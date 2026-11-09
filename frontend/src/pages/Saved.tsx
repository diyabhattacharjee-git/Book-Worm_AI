import { Heart } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { BookCard, BookGrid } from '../components/books'
import { ListingCard } from '../components/marketplace'
import { EmptyState, ErrorState, ListSkeleton, PageHeader, Tabs } from '../components/ui'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { TTL, queryKey, useGet } from '../hooks/useApi'
import { api } from '../services/api'
import { invalidate, optimistic } from '../services/queryCache'
import type { BookSummary, Inquiry, Listing, ShelfEntry } from '../types'
import { Messages } from './SellerDashboard'

type Tab = 'listings' | 'wishlist' | 'messages'
const FAVORITES = '/api/marketplace/favorites'

export default function Saved() {
  const { user } = useAuth()
  const toast = useToast()
  const [tab, setTab] = useState<Tab>('listings')
  const userId = user?.id
  const favs = useGet<Listing[]>(FAVORITES, undefined, { userId, ttl: TTL.medium })
  const wish = useGet<{ items: ShelfEntry[] }>('/api/bookshelf', { status: 'want_to_read' }, { userId, ttl: TTL.medium, enabled: tab === 'wishlist' })
  const history = useGet<{ saved: BookSummary[] }>('/api/reading-history', undefined, { userId, ttl: TTL.medium, enabled: tab === 'wishlist' })
  const inquiries = useGet<Inquiry[]>('/api/marketplace/inquiries', { role: 'buyer' }, { userId, ttl: TTL.short, enabled: tab === 'messages' })

  async function unfavorite(l: Listing) {
    try {
      await optimistic<Listing[], void>(queryKey(FAVORITES, undefined, userId), (d) => d.filter((x) => x.id !== l.id), () => api.del(`/api/marketplace/listings/${l.id}/favorite`))
      invalidate('/api/marketplace/listings')
      toast.info('Removed from saved listings.')
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  const wishlistBooks = [...(wish.data?.items.map((e) => e.book) ?? []), ...(history.data?.saved ?? [])]
    .filter((b, i, arr) => arr.findIndex((x) => x.id === b.id) === i)

  return (
    <div>
      <PageHeader eyebrow="Saved" title="Wishlist & saved listings">Books you want to read, second-hand copies you’re watching, and your messages to sellers.</PageHeader>
      <Tabs label="Saved items" value={tab} onChange={setTab} tabs={[
        { value: 'listings', label: 'Saved listings', count: favs.data?.length },
        { value: 'wishlist', label: 'Wishlist', count: wish.data ? wishlistBooks.length : undefined },
        { value: 'messages', label: 'My messages', count: inquiries.data?.length },
      ]} />
      <div className="mt-6">
        {tab === 'listings' && (favs.loading ? <ListSkeleton rows={3} /> : favs.error || !favs.data ? <ErrorState error={favs.error} onRetry={favs.reload} /> : favs.data.length === 0 ? (
          <EmptyState icon={<Heart className="h-6 w-6" />} title="No saved listings" action={<Link to="/marketplace" className="btn-outline">Browse used books</Link>}>Tap the heart on a listing to watch it here.</EmptyState>
        ) : (
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4">
            {favs.data.map((l) => <ListingCard key={l.id} listing={{ ...l, is_favorite: true }} onFavorite={unfavorite} />)}
          </div>
        ))}
        {tab === 'wishlist' && (wish.loading || history.loading ? <ListSkeleton rows={3} /> : wish.error ? <ErrorState error={wish.error} onRetry={wish.reload} /> : wishlistBooks.length === 0 ? (
          <EmptyState title="Your wishlist is empty" action={<Link to="/for-you" className="btn-outline">Get recommendations</Link>}>Save books from recommendations or add them to “Want to Read”.</EmptyState>
        ) : (
          <BookGrid>{wishlistBooks.map((b) => <BookCard key={b.id} book={b} footer={<Link to={`/marketplace/find?title=${encodeURIComponent(b.title)}`} className="link text-xs">Find a used copy</Link>} />)}</BookGrid>
        ))}
        {tab === 'messages' && (inquiries.loading ? <ListSkeleton rows={3} /> : inquiries.error ? <ErrorState error={inquiries.error} onRetry={inquiries.reload} /> : <Messages inquiries={inquiries.data ?? []} onReplied={inquiries.reload} />)}
      </div>
    </div>
  )
}
