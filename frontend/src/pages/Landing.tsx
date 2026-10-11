import { ArrowRight, BookOpenCheck, Bot, Scale, Search, Sparkles, Store } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { BookCard, BookCover, BookGrid } from '../components/books'
import { ListingCard } from '../components/marketplace'
import { BookGridSkeleton, EmptyState, ErrorState } from '../components/ui'
import { useAuth } from '../contexts/AuthContext'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import type { BookSummary, Listing, Page } from '../types'

const EXAMPLES = [
  'Used copy of Atomic Habits under ₹250, good condition',
  'Clean Code under ₹500 with pickup in Kolkata',
  'Is ₹300 a fair price for The Alchemist?',
]

const FEATURES = [
  { icon: Sparkles, title: 'Recommendations that explain themselves', text: 'A hybrid of content similarity, similar readers, popularity and your stated preferences — with the reason for every pick.', to: '/for-you' },
  { icon: Search, title: 'Search the way you talk', text: '“A short, inspiring book I can finish in a weekend.” Semantic search turns that into real catalogue results.', to: '/search' },
  { icon: Scale, title: 'Fair-price checks for used books', text: 'A multi-step agent identifies the edition, gathers listings, estimates a fair range and ranks deals — showing its evidence.', to: '/marketplace/find' },
  { icon: Store, title: 'A community marketplace', text: 'List your own books with photos, answer buyer messages privately, and mark copies as sold.', to: '/sell' },
  { icon: BookOpenCheck, title: 'Shelves, goals and reading plans', text: 'Track what you read, set yearly goals and get a realistic daily schedule from real page counts.', to: '/shelf' },
  { icon: Bot, title: 'A reading assistant', text: 'Ask what to read next, compare books or find a used copy — answered from the catalogue, not invented.', to: '/assistant' },
]

export default function Landing() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const popular = useApi(() => api.get<Page<BookSummary>>('/api/books', { sort: 'popularity', page_size: 10 }), [])
  const listings = useApi(() => api.get<Page<Listing>>('/api/marketplace/listings', { page_size: 4 }), [])

  function findDeal(e: FormEvent) {
    e.preventDefault()
    if (q.trim()) navigate(`/marketplace/find?q=${encodeURIComponent(q.trim())}`)
  }

  const heroBooks = popular.data?.items.slice(0, 3) ?? []

  return (
    <div className="space-y-20">
      <section className="grid items-center gap-10 lg:grid-cols-[1.2fr_1fr]">
        <div>
          <p className="eyebrow mb-4">Discover · Read · Buy second-hand wisely</p>
          <h1 className="font-serif text-4xl font-semibold leading-[1.1] sm:text-5xl lg:text-6xl">
            Your next book, <span className="italic text-forest">fairly priced</span>.
          </h1>
          <p className="mt-5 max-w-xl text-lg text-ink-soft">
            Find books you’ll actually enjoy, understand why they were recommended, and check whether a used copy is worth the asking price before you buy.
          </p>
          <form onSubmit={findDeal} className="mt-8 max-w-xl" role="search">
            <label htmlFor="deal-q" className="label">Describe the used book you want</label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <input id="deal-q" value={q} onChange={(e) => setQ(e.target.value)} className="input py-3 text-base" placeholder={EXAMPLES[0]} />
              <button className="btn-primary py-3">Find deals <ArrowRight className="h-4 w-4" aria-hidden /></button>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {EXAMPLES.map((ex) => (
                <button key={ex} type="button" onClick={() => navigate(`/marketplace/find?q=${encodeURIComponent(ex)}`)} className="chip hover:border-ink-soft">{ex}</button>
              ))}
            </div>
          </form>
          {!user && <p className="mt-6 text-sm text-muted">No account needed to browse. <Link to="/register" className="link">Create a free account</Link> for personalised picks and to sell books.</p>}
        </div>
        <div className="relative mx-auto hidden h-[420px] w-full max-w-md sm:block" aria-hidden>
          {heroBooks.map((b, i) => (
            <div key={b.id} className="absolute w-44 transition-transform" style={{ left: `${8 + i * 26}%`, top: `${i % 2 ? 18 : 4}%`, transform: `rotate(${(i - 1) * 5}deg)`, zIndex: i === 1 ? 2 : 1 }}>
              <BookCover title={b.title} authors={b.authors} url={b.cover_url} className="shadow-[var(--shadow-lift)]" />
            </div>
          ))}
          <div className="absolute bottom-0 left-0 right-0 card p-4">
            <p className="text-xs text-muted">How deals are judged</p>
            <p className="mt-1 text-sm">Identify the edition → gather listings → validate → estimate a fair range → rank by value, condition and listing quality.</p>
          </div>
        </div>
      </section>

      <section aria-labelledby="features">
        <h2 id="features" className="section-title">Everything for a reader on a budget</h2>
        <div className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <Link key={f.title} to={f.to} className="card group p-6 transition-shadow hover:shadow-[var(--shadow-lift)]">
              <f.icon className="h-6 w-6 text-gold-dark" aria-hidden />
              <h3 className="mt-4 text-lg font-semibold group-hover:text-forest">{f.title}</h3>
              <p className="mt-2 text-sm text-muted">{f.text}</p>
            </Link>
          ))}
        </div>
      </section>

      <section aria-labelledby="popular">
        <div className="mb-6 flex items-end justify-between">
          <h2 id="popular" className="section-title">Popular in the catalogue</h2>
          <Link to="/discover?sort=popularity" className="link text-sm">Browse all</Link>
        </div>
        {popular.loading ? <BookGridSkeleton count={5} /> : popular.error ? <ErrorState error={popular.error} onRetry={popular.reload} /> : (
          <BookGrid>{popular.data!.items.slice(0, 10).map((b) => <BookCard key={b.id} book={b} />)}</BookGrid>
        )}
      </section>

      <section aria-labelledby="latest">
        <div className="mb-6 flex items-end justify-between">
          <h2 id="latest" className="section-title">Latest second-hand listings</h2>
          <Link to="/marketplace" className="link text-sm">See the marketplace</Link>
        </div>
        {listings.error ? <ErrorState error={listings.error} onRetry={listings.reload} /> : listings.data && listings.data.items.length === 0 ? (
          <EmptyState title="No books listed yet" action={<Link to="/sell" className="btn-forest">Sell a book</Link>}>
            Be the first to list a book you’ve finished. Buyers will be able to message you privately.
          </EmptyState>
        ) : (
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {(listings.data?.items ?? []).map((l) => <ListingCard key={l.id} listing={l} />)}
          </div>
        )}
      </section>
    </div>
  )
}
