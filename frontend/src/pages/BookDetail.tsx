import { CalendarClock, ExternalLink, Flag, ListPlus, Scale, Tag, ThumbsDown, ThumbsUp, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { BookCard, BookCover, BookGrid } from '../components/books'
import { ReportDialog } from '../components/ReportDialog'
import { Badge, ErrorState, Modal, Notice, Skeleton, Spinner, StarInput, Stars } from '../components/ui'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import type { BookDetail as Book, BookSummary, Edition, Review, ShelfEntry, ShelfStatus } from '../types'
import { SHELF_LABELS, date, languageName, money } from '../utils/format'

interface ReviewsPage { items: Review[]; total: number; my_review: Review | null; distribution: Record<string, number> }

export default function BookDetail() {
  const { id } = useParams()
  const book = useApi(() => api.get<Book>(`/api/books/${id}`), [id])
  if (book.loading) return <DetailSkeleton />
  if (book.error) return <ErrorState error={book.error} onRetry={book.reload} />
  const b = book.data!
  return (
    <div className="space-y-14">
      <BookHeader book={b} onChanged={book.reload} />
      <Editions book={b} />
      <Similar bookId={b.id} />
      <Reviews book={b} onChanged={book.reload} />
    </div>
  )
}

function DetailSkeleton() {
  return (
    <div className="grid gap-10 md:grid-cols-[260px_1fr]">
      <Skeleton className="aspect-[2/3] w-full rounded-xl" />
      <div className="space-y-4"><Skeleton className="h-10 w-2/3" /><Skeleton className="h-4 w-1/3" /><Skeleton className="h-32 w-full" /></div>
    </div>
  )
}

function BookHeader({ book, onChanged }: { book: Book; onChanged: () => void }) {
  const { user } = useAuth()
  const toast = useToast()
  const shelf = useApi(() => api.get<{ items: ShelfEntry[] }>('/api/bookshelf'), [user?.id, book.id], !!user)
  const entry = shelf.data?.items.find((e) => e.book.id === book.id)
  const [expanded, setExpanded] = useState(false)
  const [listOpen, setListOpen] = useState(false)

  async function setStatus(status: ShelfStatus | '') {
    try {
      if (!status && entry) await api.del(`/api/bookshelf/${entry.id}`)
      else if (status) await api.post('/api/bookshelf', { book_id: book.id, status })
      toast.success(status ? `Moved to “${SHELF_LABELS[status]}”.` : 'Removed from your shelf.')
      shelf.reload()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function interaction(type: 'interested' | 'not_interested') {
    try {
      await api.post(`/api/books/${book.id}/interactions`, { type })
      toast.success(type === 'interested' ? 'Noted — we’ll recommend more like this.' : 'Noted — we’ll show fewer books like this.')
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  const desc = book.description ?? ''
  const long = desc.length > 700
  const r = book.ratings

  return (
    <section className="grid gap-10 md:grid-cols-[260px_1fr]">
      <div className="mx-auto w-48 md:w-full">
        <BookCover title={book.title} authors={book.authors} url={book.cover_url} size="lg" />
      </div>
      <div>
        <div className="flex flex-wrap gap-2">
          {book.genres.map((g) => <Link key={g} to={`/discover?genre=${encodeURIComponent(g.toLowerCase().replace(/[^a-z0-9]+/g, '-'))}`} className="chip hover:border-ink-soft">{g}</Link>)}
        </div>
        <h1 className="mt-3 font-serif text-4xl font-semibold leading-tight">{book.title}</h1>
        {book.subtitle && <p className="mt-1 text-lg text-ink-soft">{book.subtitle}</p>}
        <p className="mt-2 text-lg">by {book.authors.map((a, i) => <span key={a}>{i > 0 && ', '}<Link to={`/discover?author=${encodeURIComponent(a)}`} className="link">{a}</Link></span>)}{!book.authors.length && 'Unknown author'}</p>

        <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
          <div title="Ratings from BookWorm readers">
            {r.app_count ? <span className="inline-flex items-center gap-2"><Stars value={r.app_average} size="md" /><strong>{r.app_average?.toFixed(2)}</strong><span className="text-muted">{r.app_count} BookWorm rating{r.app_count === 1 ? '' : 's'}</span></span>
              : <span className="text-muted">No BookWorm ratings yet</span>}
          </div>
          {r.external_average && (
            <div className="text-muted" title="Rating supplied by an external metadata provider, not BookWorm readers">
              External: {r.external_average.toFixed(2)}★ from {r.external_count?.toLocaleString()} ratings on {r.external_source?.replace('_', ' ')}
            </div>
          )}
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-2">
          {user ? (
            <>
              <label className="sr-only" htmlFor="shelf-status">Bookshelf status</label>
              <select id="shelf-status" className="input w-auto" value={entry?.status ?? ''} onChange={(e) => setStatus(e.target.value as ShelfStatus | '')} disabled={shelf.loading}>
                <option value="">{entry ? 'Remove from shelf' : 'Add to shelf…'}</option>
                {Object.entries(SHELF_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
              <button className="btn-outline" onClick={() => setListOpen(true)}><ListPlus className="h-4 w-4" aria-hidden />Add to list</button>
              <button className="btn-ghost" onClick={() => interaction('interested')} title="More like this"><ThumbsUp className="h-4 w-4" aria-hidden />Interested</button>
              <button className="btn-ghost" onClick={() => interaction('not_interested')} title="Fewer like this"><ThumbsDown className="h-4 w-4" aria-hidden />Not for me</button>
            </>
          ) : (
            <Link to={`/login?next=/books/${book.id}`} className="btn-primary">Log in to shelve, rate & review</Link>
          )}
        </div>

        <div className="mt-6 grid gap-3 sm:grid-cols-3">
          <Link to={`/marketplace/find?isbn=${book.isbn13 ?? ''}&title=${encodeURIComponent(book.title)}`} className="card p-4 hover:shadow-[var(--shadow-lift)]">
            <Tag className="h-5 w-5 text-forest" aria-hidden />
            <p className="mt-2 font-semibold">Used copies</p>
            <p className="text-sm text-muted">{book.used_listing_count ? `${book.used_listing_count} listed, from ${money(book.lowest_used_price, book.lowest_used_currency)}` : 'Search & check fair prices'}</p>
          </Link>
          <Link to={`/books/${book.id}/offers`} className="card p-4 hover:shadow-[var(--shadow-lift)]">
            <ExternalLink className="h-5 w-5 text-forest" aria-hidden />
            <p className="mt-2 font-semibold">New copies</p>
            <p className="text-sm text-muted">Available offers & sources</p>
          </Link>
          <Link to={`/plans?book=${book.id}`} className="card p-4 hover:shadow-[var(--shadow-lift)]">
            <CalendarClock className="h-5 w-5 text-forest" aria-hidden />
            <p className="mt-2 font-semibold">Plan your reading</p>
            <p className="text-sm text-muted">{book.page_count ? `${book.page_count} pages` : 'Page count unknown'}</p>
          </Link>
        </div>

        <div className="mt-8">
          <h2 className="text-xl font-semibold">About this book</h2>
          {desc ? (
            <div className="mt-2 whitespace-pre-line leading-relaxed text-ink-soft">
              {long && !expanded ? `${desc.slice(0, 700)}…` : desc}
              {long && <button className="link ml-1 text-sm" onClick={() => setExpanded((x) => !x)}>{expanded ? 'Show less' : 'Read more'}</button>}
            </div>
          ) : <p className="mt-2 text-muted">No description is available from our metadata sources.</p>}
        </div>

        <dl className="mt-8 grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
          <Meta label="First published" value={book.first_published_year} />
          <Meta label="Pages" value={book.page_count} />
          <Meta label="Language" value={book.language ? languageName(book.language) : null} />
          <Meta label="Publisher" value={book.publisher} />
          <Meta label="ISBN-13" value={book.isbn13} />
          <Meta label="Series" value={book.series} />
          <Meta label="Difficulty signal" value={book.difficulty_signal} />
          <Meta label="Metadata source" value={`${book.source.replace('_', ' ')}${book.metadata_fetched_at ? ` · ${date(book.metadata_fetched_at)}` : ''}`} />
        </dl>
        {book.subjects.length > 0 && (
          <div className="mt-5 flex flex-wrap gap-1.5">{book.subjects.map((s) => <span key={s} className="chip">{s}</span>)}</div>
        )}
        <div className="mt-6 flex flex-wrap gap-3 text-sm">
          {book.external_links.map((l) => <a key={l.url} href={l.url} target="_blank" rel="noopener noreferrer" className="link inline-flex items-center gap-1">{l.label}<ExternalLink className="h-3 w-3" aria-hidden /></a>)}
          <Link to={`/compare?ids=${book.id}`} className="link inline-flex items-center gap-1"><Scale className="h-3.5 w-3.5" aria-hidden />Compare with another book</Link>
        </div>
      </div>
      {user && <AddToListDialog open={listOpen} onClose={() => { setListOpen(false); onChanged() }} bookId={book.id} />}
    </section>
  )
}

function Meta({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-muted">{label}</dt>
      <dd className="mt-0.5 text-ink">{value ?? <span className="text-muted">Not available</span>}</dd>
    </div>
  )
}

function AddToListDialog({ open, onClose, bookId }: { open: boolean; onClose: () => void; bookId: number }) {
  const toast = useToast()
  const lists = useApi(() => api.get<{ id: number; name: string; books: BookSummary[] }[]>('/api/reading-lists'), [open], open)
  const [name, setName] = useState('')
  async function add(listId: number) {
    try {
      await api.post(`/api/reading-lists/${listId}/items`, { book_id: bookId })
      toast.success('Added to list.')
      onClose()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }
  async function create() {
    if (!name.trim()) return
    try {
      const l = await api.post<{ id: number }>('/api/reading-lists', { name: name.trim() })
      await add(l.id)
      setName('')
    } catch (e) {
      toast.error((e as Error).message)
    }
  }
  return (
    <Modal open={open} onClose={onClose} title="Add to a reading list">
      {lists.loading ? <Spinner /> : (
        <div className="space-y-3">
          {lists.data?.length ? lists.data.map((l) => {
            const has = l.books.some((b) => b.id === bookId)
            return (
              <button key={l.id} disabled={has} onClick={() => add(l.id)} className="flex w-full items-center justify-between rounded-lg border border-line px-3 py-2 text-left text-sm hover:bg-parchment disabled:opacity-60">
                <span>{l.name} <span className="text-muted">({l.books.length})</span></span>
                {has && <Badge tone="forest">Added</Badge>}
              </button>
            )
          }) : <p className="text-sm text-muted">You don’t have any lists yet.</p>}
          <div className="flex gap-2 border-t border-line pt-3">
            <label htmlFor="new-list" className="sr-only">New list name</label>
            <input id="new-list" className="input" placeholder="New list name" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} />
            <button className="btn-primary" onClick={create} disabled={!name.trim()}>Create & add</button>
          </div>
        </div>
      )}
    </Modal>
  )
}

function Editions({ book }: { book: Book }) {
  const [more, setMore] = useState(false)
  const ext = useApi(() => api.get<{ catalogue: Edition[]; external: Edition[]; error: string | null }>(`/api/books/${book.id}/editions`, { include_external: true }), [book.id, more], more)
  return (
    <section aria-labelledby="editions">
      <div className="flex items-end justify-between">
        <h2 id="editions" className="section-title">Editions</h2>
        {!more && <button className="btn-outline btn-sm" onClick={() => setMore(true)}>Find more editions on Open Library</button>}
      </div>
      <p className="mt-1 text-sm text-muted">Different editions and translations can differ in pages and price, so they’re never treated as interchangeable.</p>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[560px] text-left text-sm">
          <thead className="border-b border-line text-xs uppercase tracking-wide text-muted">
            <tr><th className="py-2">ISBN</th><th>Format</th><th>Publisher</th><th>Year</th><th>Pages</th><th>Language</th><th>Source</th></tr>
          </thead>
          <tbody className="divide-y divide-line">
            {[...book.editions.map((e) => ({ ...e, source: 'catalogue' })), ...(ext.data?.external ?? [])].map((e, i) => (
              <tr key={`${e.isbn13}-${i}`}>
                <td className="py-2 font-mono text-xs">{e.isbn13 ?? '—'}</td>
                <td>{e.format ?? '—'}</td><td>{e.publisher ?? '—'}</td><td>{e.published_year ?? '—'}</td>
                <td>{e.page_count ?? '—'}</td><td>{e.language ? languageName(e.language) : '—'}</td>
                <td>{e.source_url ? <a href={e.source_url} target="_blank" rel="noopener noreferrer" className="link">Open Library</a> : e.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {more && ext.loading && <Spinner className="mt-3" label="Loading editions" />}
        {ext.data?.error && <div className="mt-3"><Notice tone="warn">{ext.data.error}. Showing catalogue editions only.</Notice></div>}
      </div>
    </section>
  )
}

function Similar({ bookId }: { bookId: number }) {
  const sims = useApi(() => api.get<{ book: BookSummary; similarity: number; reason: string }[]>(`/api/books/${bookId}/similar`, { limit: 5 }), [bookId])
  if (sims.loading || !sims.data?.length) return null
  return (
    <section aria-labelledby="similar">
      <h2 id="similar" className="section-title">Readers might also like</h2>
      <p className="mt-1 text-sm text-muted">Similar by subjects, genres and description in the catalogue.</p>
      <div className="mt-6"><BookGrid>{sims.data.map((s) => <BookCard key={s.book.id} book={s.book} why={s.reason} />)}</BookGrid></div>
    </section>
  )
}

function Reviews({ book, onChanged }: { book: Book; onChanged: () => void }) {
  const { user } = useAuth()
  const toast = useToast()
  const [sort, setSort] = useState('helpful')
  const reviews = useApi(() => api.get<ReviewsPage>(`/api/books/${book.id}/reviews`, { sort }), [book.id, sort, user?.id])
  const mine = reviews.data?.my_review
  const [rating, setRating] = useState(0)
  const [body, setBody] = useState('')
  const [editing, setEditing] = useState(false)
  const [reportId, setReportId] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)

  function startEdit() {
    setRating(mine?.rating ?? 0)
    setBody(mine?.body ?? '')
    setEditing(true)
  }

  async function save() {
    if (!rating) return toast.error('Choose a star rating first.')
    setBusy(true)
    try {
      await api.post(`/api/books/${book.id}/reviews`, { rating, body: body.trim() || null })
      toast.success(mine ? 'Review updated.' : 'Thanks for your review!')
      setEditing(false)
      reviews.reload()
      onChanged()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!mine || !confirm('Delete your rating and review?')) return
    await api.del(`/api/reviews/${mine.id}`)
    toast.info('Review deleted.')
    setEditing(false)
    reviews.reload()
    onChanged()
  }

  async function helpful(r: Review) {
    try {
      if (r.voted_helpful) await api.del(`/api/reviews/${r.id}/helpful`)
      else await api.post(`/api/reviews/${r.id}/helpful`)
      reviews.reload()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  const dist = reviews.data?.distribution ?? {}
  const totalRatings = Object.values(dist).reduce((a, b) => a + b, 0)

  return (
    <section aria-labelledby="reviews" className="grid gap-10 lg:grid-cols-[280px_1fr]">
      <div>
        <h2 id="reviews" className="section-title">Ratings & reviews</h2>
        <p className="mt-1 text-sm text-muted">From BookWorm readers only.</p>
        <div className="mt-4 space-y-1.5">
          {[5, 4, 3, 2, 1].map((s) => (
            <div key={s} className="flex items-center gap-2 text-xs">
              <span className="w-6">{s}★</span>
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-parchment"><div className="h-full bg-gold" style={{ width: `${totalRatings ? (100 * (dist[s] ?? 0)) / totalRatings : 0}%` }} /></div>
              <span className="w-6 text-right text-muted">{dist[s] ?? 0}</span>
            </div>
          ))}
        </div>
        {user ? (
          mine && !editing ? (
            <div className="card mt-6 p-4">
              <p className="text-sm font-medium">Your rating</p>
              <Stars value={mine.rating} size="md" />
              {mine.body && <p className="mt-2 text-sm text-ink-soft line-clamp-4">{mine.body}</p>}
              <div className="mt-3 flex gap-2"><button className="btn-outline btn-sm" onClick={startEdit}>Edit</button><button className="btn-ghost btn-sm" onClick={remove}><Trash2 className="h-3.5 w-3.5" aria-hidden />Delete</button></div>
            </div>
          ) : editing || !mine ? (
            <div className="card mt-6 space-y-3 p-4">
              <p className="text-sm font-medium">{mine ? 'Edit your review' : 'Rate this book'}</p>
              <StarInput value={rating} onChange={setRating} />
              <label htmlFor="review-body" className="sr-only">Review</label>
              <textarea id="review-body" className="input" rows={4} maxLength={5000} placeholder="What did you think? (optional)" value={body} onChange={(e) => setBody(e.target.value)} />
              <div className="flex gap-2">
                <button className="btn-primary btn-sm" onClick={save} disabled={busy || !rating}>{mine ? 'Save changes' : 'Post'}</button>
                {editing && <button className="btn-ghost btn-sm" onClick={() => setEditing(false)}>Cancel</button>}
              </div>
            </div>
          ) : null
        ) : <p className="mt-6 text-sm"><Link to={`/login?next=/books/${book.id}`} className="link">Log in</Link> to rate and review.</p>}
      </div>
      <div>
        <div className="mb-3 flex items-center justify-between">
          <p className="text-sm text-muted">{reviews.data?.total ?? 0} written review{reviews.data?.total === 1 ? '' : 's'}</p>
          <select aria-label="Sort reviews" className="input w-auto py-1.5" value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="helpful">Most helpful</option><option value="recent">Most recent</option>
            <option value="rating_high">Highest rated</option><option value="rating_low">Lowest rated</option>
          </select>
        </div>
        {reviews.loading ? <Spinner /> : reviews.error ? <ErrorState error={reviews.error} onRetry={reviews.reload} /> : (
          reviews.data!.items.length === 0 ? <p className="text-sm text-muted">No written reviews yet. Be the first!</p> : (
            <ul className="space-y-4">
              {reviews.data!.items.map((r) => (
                <li key={r.id} className="card p-4">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 text-sm"><strong>{r.user_display_name}</strong><Stars value={r.rating} /></div>
                    <span className="text-xs text-muted">{date(r.updated_at)}</span>
                  </div>
                  <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-ink-soft">{r.body}</p>
                  <div className="mt-3 flex items-center gap-3 text-xs">
                    {user && !r.is_mine && (
                      <>
                        <button className={`btn-ghost btn-sm ${r.voted_helpful ? 'text-forest' : ''}`} onClick={() => helpful(r)} aria-pressed={r.voted_helpful}>
                          <ThumbsUp className="h-3.5 w-3.5" aria-hidden />Helpful ({r.helpful_count})
                        </button>
                        <button className="btn-ghost btn-sm" onClick={() => setReportId(r.id)}><Flag className="h-3.5 w-3.5" aria-hidden />Report</button>
                      </>
                    )}
                    {(!user || r.is_mine) && <span className="text-muted">{r.helpful_count} found this helpful</span>}
                  </div>
                </li>
              ))}
            </ul>
          )
        )}
      </div>
      {reportId && <ReportDialog open onClose={() => setReportId(null)} endpoint={`/api/reviews/${reportId}/report`} what="review" />}
    </section>
  )
}
