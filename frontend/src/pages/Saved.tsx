import { Heart } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { BookCard, BookGrid } from '../components/books'
import { ListingCard } from '../components/marketplace'
import { EmptyState, ErrorState, PageHeader, Spinner, Tabs } from '../components/ui'
import { useToast } from '../contexts/ToastContext'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import type { BookSummary, Inquiry, Listing, ShelfEntry } from '../types'
import { Messages } from './SellerDashboard'

type Tab = 'listings' | 'wishlist' | 'messages'

export default function Saved() {
  const toast = useToast()
  const [tab, setTab] = useState<Tab>('listings')
  const favs = useApi(() => api.get<Listing[]>('/api/marketplace/favorites'), [])
  const wish = useApi(() => api.get<{ items: ShelfEntry[] }>('/api/bookshelf', { status: 'want_to_read' }), [])
  const history = useApi(() => api.get<{ saved: BookSummary[] }>('/api/reading-history'), [])
  const inquiries = useApi(() => api.get<Inquiry[]>('/api/marketplace/inquiries', { role: 'buyer' }), [])

  async function unfavorite(l: Listing) {
    await api.del(`/api/marketplace/listings/${l.id}/favorite`)
    favs.setData((d) => d && d.filter((x) => x.id !== l.id))
    toast.info('Removed from saved listings.')
  }

  const wishlistBooks = [...(wish.data?.items.map((e) => e.book) ?? []), ...(history.data?.saved ?? [])]
    .filter((b, i, arr) => arr.findIndex((x) => x.id === b.id) === i)

  return (
    <div>
      <PageHeader eyebrow="Saved" title="Wishlist & saved listings">Books you want to read, second-hand copies you’re watching, and your messages to sellers.</PageHeader>
      <Tabs label="Saved items" value={tab} onChange={setTab} tabs={[
        { value: 'listings', label: 'Saved listings', count: favs.data?.length },
        { value: 'wishlist', label: 'Wishlist', count: wishlistBooks.length },
        { value: 'messages', label: 'My messages', count: inquiries.data?.length },
      ]} />
      <div className="mt-6">
        {tab === 'listings' && (favs.loading ? <Spinner /> : favs.error ? <ErrorState error={favs.error} onRetry={favs.reload} /> : favs.data!.length === 0 ? (
          <EmptyState icon={<Heart className="h-6 w-6" />} title="No saved listings" action={<Link to="/marketplace" className="btn-outline">Browse used books</Link>}>Tap the heart on a listing to watch it here.</EmptyState>
        ) : (
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4">
            {favs.data!.map((l) => <ListingCard key={l.id} listing={{ ...l, is_favorite: true }} onFavorite={unfavorite} />)}
          </div>
        ))}
        {tab === 'wishlist' && (wish.loading || history.loading ? <Spinner /> : wishlistBooks.length === 0 ? (
          <EmptyState title="Your wishlist is empty" action={<Link to="/for-you" className="btn-outline">Get recommendations</Link>}>Save books from recommendations or add them to “Want to Read”.</EmptyState>
        ) : (
          <BookGrid>{wishlistBooks.map((b) => <BookCard key={b.id} book={b} footer={<Link to={`/marketplace/find?title=${encodeURIComponent(b.title)}`} className="link text-xs">Find a used copy</Link>} />)}</BookGrid>
        ))}
        {tab === 'messages' && (inquiries.loading ? <Spinner /> : <Messages inquiries={inquiries.data ?? []} onReplied={inquiries.reload} />)}
      </div>
    </div>
  )
}
