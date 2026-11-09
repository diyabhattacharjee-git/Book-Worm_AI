import { CalendarClock, ExternalLink, Flag, ListPlus, Scale, Tag, ThumbsDown, ThumbsUp, Trash2 } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, useParams } from 'react-router'
import { BookCard, BookCover, BookGrid } from '../components/books'
import { ReportDialog } from '../components/ReportDialog'
import { Badge, CharCounter, ErrorState, Field, ListSkeleton, Modal, Notice, Skeleton, Spinner, StarInput, Stars } from '../components/ui'
import { useAuth } from '../contexts/AuthContext'
import { useConfirm } from '../contexts/ConfirmContext'
import { useToast } from '../contexts/ToastContext'
import { TTL, queryKey, useGet } from '../hooks/useApi'
import { api } from '../services/api'
import { invalidate, optimistic, refetch, setQueryData } from '../services/queryCache'
import type { BookDetail as Book, BookSummary, Edition, Review, ShelfEntry, ShelfStatus } from '../types'
import { SHELF_LABELS, date, languageName, money } from '../utils/format'
import { REVIEW_MAX_LENGTH } from '../utils/validation'

interface ReviewsPage { items: Review[]; total: number; my_review: Review | null; distribution: Record<string, number> }
interface ShelfPage { items: ShelfEntry[]; counts?: Record<string, number> }

const LIST_NAME_MAX = 80
const REVIEW_PAGE = 10
const REVIEW_PAGE_LIMIT = 50
const REVIEW_PREVIEW = 600
const READING_LISTS = '/api/reading-lists'

export default function BookDetail() {
  const { id } = useParams()
  const book = useGet<Book>(`/api/books/${id}`, undefined, { ttl: TTL.medium })
  if (book.loading) return <DetailSkeleton />
  if (book.error || !book.data) return <ErrorState error={book.error} onRetry={book.reload} />
  const b = book.data
  return (
    <div className="space-y-14">
      <BookHeader book={b} />
      <Editions book={b} />
      <Similar bookId={b.id} />
      <Reviews book={b} />
    </div>
  )
}

function DetailSkeleton() {
  return (
    <div className="grid gap-10 md:grid-cols-[260px_minmax(0,1fr)]">
      <Skeleton className="aspect-[2/3] w-full rounded-xl" />
      <div className="space-y-4"><Skeleton className="h-10 w-2/3" /><Skeleton className="h-4 w-1/3" /><Skeleton className="h-32 w-full" /></div>
    </div>
  )
}

function BookHeader({ book }: { book: Book }) {
  const { user } = useAuth()
  const toast = useToast()
  const shelfPath = user ? '/api/bookshelf' : null
  const shelfParams = { book_id: book.id }
  const shelfKey = queryKey('/api/bookshelf', shelfParams, user?.id)
  const shelf = useGet<ShelfPage>(shelfPath, shelfParams, { userId: user?.id, ttl: TTL.medium })
  const entry = shelf.data?.items[0]
  const [expanded, setExpanded] = useState(false)
  const [listOpen, setListOpen] = useState(false)
  const [feedback, setFeedback] = useState<'interested' | 'not_interested' | null>(null)
  const [shelfBusy, setShelfBusy] = useState(false)

  async function setStatus(status: ShelfStatus | '') {
    if (shelfBusy) return
    setShelfBusy(true)
    const draft: ShelfEntry = { id: entry?.id ?? -1, book, status: (status || 'want_to_read') as ShelfStatus, pages_read: entry?.pages_read ?? 0, total_pages: book.page_count, percent: entry?.percent ?? null, started_on: entry?.started_on ?? null, finished_on: entry?.finished_on ?? null, notes: entry?.notes ?? null, updated_at: new Date().toISOString() }
    try {
      if (!status) {
        if (!entry) return
        await optimistic<ShelfPage, void>(shelfKey, (d) => ({ ...d, items: [] }), () => api.del(`/api/bookshelf/${entry.id}`))
      } else {
        const saved = await optimistic<ShelfPage, ShelfEntry>(shelfKey, (d) => ({ ...d, items: [draft] }), () => api.post<ShelfEntry>('/api/bookshelf', { book_id: book.id, status }))
        setQueryData<ShelfPage>(shelfKey, (d) => ({ ...(d ?? {}), items: [saved] }))
      }
      toast.success(status ? `Moved to “${SHELF_LABELS[status]}”.` : 'Removed from your shelf.')
      invalidate('/api/bookshelf', '/api/recommendations')
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setShelfBusy(false)
    }
  }

  async function interaction(type: 'interested' | 'not_interested') {
    const before = feedback
    setFeedback(type)
    try {
      await api.post(`/api/books/${book.id}/interactions`, { type })
      toast.success(type === 'interested' ? 'Noted. We’ll recommend more like this.' : 'Noted. We’ll show fewer books like this.')
      invalidate('/api/recommendations')
    } catch (e) {
      setFeedback(before)
      toast.error((e as Error).message)
    }
  }

  const desc = book.description ?? ''
  const long = desc.length > 700
  const r = book.ratings

  return (
    <section className="grid gap-10 md:grid-cols-[260px_minmax(0,1fr)]">
      <div className="mx-auto w-48 md:w-full">
        <BookCover title={book.title} authors={book.authors} url={book.cover_url} size="lg" />
      </div>
      <div className="min-w-0">
        <div className="flex flex-wrap gap-2">
          {book.genres.map((g) => <Link key={g} to={`/discover?genre=${encodeURIComponent(g.toLowerCase().replace(/[^a-z0-9]+/g, '-'))}`} className="chip hover:border-ink-soft">{g}</Link>)}
        </div>
        <h1 className="user-text mt-3 font-serif text-3xl font-semibold leading-tight sm:text-4xl">{book.title}</h1>
        {book.subtitle && <p className="user-text mt-1 text-lg text-ink-soft">{book.subtitle}</p>}
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
              <select id="shelf-status" className="input w-auto" value={entry?.status ?? ''} onChange={(e) => setStatus(e.target.value as ShelfStatus | '')} disabled={shelf.loading || shelfBusy}>
                <option value="">{entry ? 'Remove from shelf' : 'Add to shelf…'}</option>
                {Object.entries(SHELF_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
              <button className="btn-outline" onClick={() => setListOpen(true)}><ListPlus className="h-4 w-4" aria-hidden />Add to list</button>
              <button className={`btn-ghost ${feedback === 'interested' ? 'bg-forest-soft text-forest-dark' : ''}`} aria-pressed={feedback === 'interested'} onClick={() => interaction('interested')} title="More like this"><ThumbsUp className="h-4 w-4" aria-hidden />Interested</button>
              <button className={`btn-ghost ${feedback === 'not_interested' ? 'bg-rust-soft text-rust' : ''}`} aria-pressed={feedback === 'not_interested'} onClick={() => interaction('not_interested')} title="Fewer like this"><ThumbsDown className="h-4 w-4" aria-hidden />Not for me</button>
            </>
          ) : (
            <Link to={`/login?next=/books/${book.id}`} className="btn-primary">Log in to shelve, rate & review</Link>
          )}
        </div>

        <div className="mt-6 grid gap-3 sm:grid-cols-3">
          <Link to={`/marketplace/find?isbn=${book.isbn13 ?? ''}&title=${encodeURIComponent(book.title)}`} className="card p-4 transition-shadow hover:shadow-[var(--shadow-lift)]">
            <Tag className="h-5 w-5 text-forest" aria-hidden />
            <p className="mt-2 font-semibold">Used copies</p>
            <p className="text-sm text-muted">{book.used_listing_count ? `${book.used_listing_count} listed, from ${money(book.lowest_used_price, book.lowest_used_currency)}` : 'Search & check fair prices'}</p>
          </Link>
          <Link to={`/books/${book.id}/offers`} className="card p-4 transition-shadow hover:shadow-[var(--shadow-lift)]">
            <ExternalLink className="h-5 w-5 text-forest" aria-hidden />
            <p className="mt-2 font-semibold">New copies</p>
            <p className="text-sm text-muted">Available offers & sources</p>
          </Link>
          <Link to={`/plans?book=${book.id}`} className="card p-4 transition-shadow hover:shadow-[var(--shadow-lift)]">
            <CalendarClock className="h-5 w-5 text-forest" aria-hidden />
            <p className="mt-2 font-semibold">Plan your reading</p>
            <p className="text-sm text-muted">{book.page_count ? `${book.page_count} pages` : 'Page count unknown'}</p>
          </Link>
        </div>

        <div className="mt-8">
          <h2 className="text-xl font-semibold">About this book</h2>
          {desc ? (
            <div className="user-text mt-2 leading-relaxed text-ink-soft">
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
      {user && listOpen && <AddToListDialog onClose={() => setListOpen(false)} bookId={book.id} />}
    </section>
  )
}

function Meta({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs uppercase tracking-wide text-muted">{label}</dt>
      <dd className="user-text mt-0.5 text-ink">{value ?? <span className="text-muted">Not available</span>}</dd>
    </div>
  )
}

function AddToListDialog({ onClose, bookId }: { onClose: () => void; bookId: number }) {
  const { user } = useAuth()
  const toast = useToast()
  const lists = useGet<{ id: number; name: string; books: BookSummary[] }[]>(READING_LISTS, undefined, { userId: user?.id, ttl: TTL.medium })
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)

  async function add(listId: number) {
    setBusy(true)
    try {
      await api.post(`${READING_LISTS}/${listId}/items`, { book_id: bookId })
      invalidate(READING_LISTS)
      toast.success('Added to list.')
      onClose()
    } catch (e) {
      toast.error((e as Error).message)
      setBusy(false)
    }
  }

  async function create() {
    const clean = name.trim()
    if (!clean || clean.length > LIST_NAME_MAX) return
    setBusy(true)
    try {
      const l = await api.post<{ id: number }>(READING_LISTS, { name: clean })
      await add(l.id)
    } catch (e) {
      toast.error((e as Error).message)
      setBusy(false)
    }
  }

  return (
    <Modal open onClose={onClose} title="Add to a reading list">
      {lists.loading ? <ListSkeleton rows={2} /> : lists.error ? <ErrorState error={lists.error} onRetry={lists.reload} /> : (
        <div className="space-y-3">
          {lists.data?.length ? lists.data.map((l) => {
            const has = l.books.some((b) => b.id === bookId)
            return (
              <button key={l.id} disabled={has || busy} onClick={() => add(l.id)} className="flex w-full items-center justify-between rounded-lg border border-line px-3 py-2 text-left text-sm hover:bg-parchment disabled:opacity-60">
                <span className="user-text min-w-0">{l.name} <span className="text-muted">({l.books.length})</span></span>
                {has && <Badge tone="forest">Added</Badge>}
              </button>
            )
          }) : <p className="text-sm text-muted">You don’t have any lists yet.</p>}
          <div className="flex gap-2 border-t border-line pt-3">
            <label htmlFor="new-list" className="sr-only">New list name</label>
            <input id="new-list" className="input" placeholder="New list name" value={name} onChange={(e) => setName(e.target.value)} maxLength={LIST_NAME_MAX} />
            <button className="btn-primary" onClick={create} disabled={!name.trim() || busy}>Create & add</button>
          </div>
        </div>
      )}
    </Modal>
  )
}

function Editions({ book }: { book: Book }) {
  const [more, setMore] = useState(false)
  const ext = useGet<{ catalogue: Edition[]; external: Edition[]; error: string | null }>(`/api/books/${book.id}/editions`, { include_external: true }, { enabled: more, ttl: TTL.hour })
  return (
    <section aria-labelledby="editions">
      <div className="flex flex-wrap items-end justify-between gap-2">
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
        {ext.error && <div className="mt-3"><ErrorState error={ext.error} onRetry={ext.reload} /></div>}
        {ext.data?.error && <div className="mt-3"><Notice tone="warn">{ext.data.error}. Showing catalogue editions only.</Notice></div>}
      </div>
    </section>
  )
}

function Similar({ bookId }: { bookId: number }) {
  const sims = useGet<{ book: BookSummary; similarity: number; reason: string }[]>(`/api/books/${bookId}/similar`, { limit: 5 }, { ttl: TTL.long })
  if (sims.loading || !sims.data?.length) return null
  return (
    <section aria-labelledby="similar">
      <h2 id="similar" className="section-title">Readers might also like</h2>
      <p className="mt-1 text-sm text-muted">Similar by subjects, genres and description in the catalogue.</p>
      <div className="mt-6"><BookGrid>{sims.data.map((s) => <BookCard key={s.book.id} book={s.book} why={s.reason} />)}</BookGrid></div>
    </section>
  )
}

function ReviewBody({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  const long = text.length > REVIEW_PREVIEW
  return (
    <div className="user-text mt-2 text-sm leading-relaxed text-ink-soft">
      {long && !open ? `${text.slice(0, REVIEW_PREVIEW)}…` : text}
      {long && <button className="link ml-1 text-xs" onClick={() => setOpen((o) => !o)} aria-expanded={open}>{open ? 'Show less' : 'Read more'}</button>}
    </div>
  )
}

function Reviews({ book }: { book: Book }) {
  const { user, loading: authLoading } = useAuth()
  const toast = useToast()
  const confirm = useConfirm()
  const [sort, setSort] = useState('helpful')
  const [limit, setLimit] = useState(REVIEW_PAGE)
  const path = `/api/books/${book.id}/reviews`
  const params = { sort, page_size: limit }
  const key = queryKey(path, params, user?.id)
  const reviews = useGet<ReviewsPage>(path, params, { userId: user?.id, ttl: TTL.short, keepPrevious: true, paused: authLoading })
  const mine = reviews.data?.my_review
  const [rating, setRating] = useState(0)
  const [body, setBody] = useState('')
  const [editing, setEditing] = useState(false)
  const [reportId, setReportId] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const savingRef = useRef(false)
  const voting = useRef(new Set<number>())

  const tooLong = body.length > REVIEW_MAX_LENGTH

  function startEdit() {
    setRating(mine?.rating ?? 0)
    setBody(mine?.body ?? '')
    setFormError(null)
    setEditing(true)
  }

  function afterRatingChange() {
    invalidate(`/api/books/${book.id}/reviews`, '/api/recommendations')
    refetch(`/api/books/${book.id}`)
  }

  async function save() {
    if (savingRef.current) return
    if (!rating) return setFormError('Choose a star rating first.')
    if (tooLong) return setFormError(`Your review is ${(body.length - REVIEW_MAX_LENGTH).toLocaleString()} characters over the ${REVIEW_MAX_LENGTH.toLocaleString()} limit.`)
    savingRef.current = true
    setBusy(true)
    setFormError(null)
    const text = body.trim() || null
    const now = new Date().toISOString()
    const draft: Review = { id: mine?.id ?? -1, book_id: book.id, user_id: user!.id, user_display_name: user!.display_name, rating, body: text, helpful_count: mine?.helpful_count ?? 0, status: 'visible', created_at: mine?.created_at ?? now, updated_at: now, is_mine: true, voted_helpful: false }
    const wasEditing = editing
    setEditing(false)
    try {
      const saved = await optimistic<ReviewsPage, Review>(key, (d) => {
        const distribution = { ...d.distribution }
        if (d.my_review) distribution[d.my_review.rating] = Math.max(0, (distribution[d.my_review.rating] ?? 0) - 1)
        distribution[rating] = (distribution[rating] ?? 0) + 1
        const others = d.items.filter((r) => !r.is_mine)
        const items = text ? [draft, ...others] : others
        return { ...d, my_review: draft, items, distribution, total: items.length }
      }, () => api.post<Review>(path, { rating, body: text }))
      setQueryData<ReviewsPage>(key, (d) => (d ? { ...d, my_review: saved, items: d.items.map((r) => (r.is_mine ? saved : r)) } : d as unknown as ReviewsPage))
      toast.success(mine ? 'Review updated.' : 'Thanks for your review!')
      setBody('')
      setRating(0)
      afterRatingChange()
    } catch (e) {
      setEditing(wasEditing)
      setFormError((e as Error).message)
    } finally {
      savingRef.current = false
      setBusy(false)
    }
  }

  async function remove() {
    if (!mine || mine.id < 0) return
    if (!await confirm({ title: 'Delete your rating and review?', confirmLabel: 'Delete', danger: true })) return
    try {
      await optimistic<ReviewsPage, void>(key, (d) => ({
        ...d, my_review: null, items: d.items.filter((r) => !r.is_mine), total: Math.max(0, d.total - (mine.body ? 1 : 0)),
        distribution: { ...d.distribution, [mine.rating]: Math.max(0, (d.distribution[mine.rating] ?? 0) - 1) },
      }), () => api.del(`/api/reviews/${mine.id}`))
      toast.info('Review deleted.')
      setEditing(false)
      afterRatingChange()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function helpful(r: Review) {
    if (voting.current.has(r.id)) return
    voting.current.add(r.id)
    const delta = r.voted_helpful ? -1 : 1
    try {
      const result = await optimistic<ReviewsPage, { helpful_count: number; voted: boolean }>(key,
        (d) => ({ ...d, items: d.items.map((x) => (x.id === r.id ? { ...x, voted_helpful: !r.voted_helpful, helpful_count: Math.max(0, x.helpful_count + delta) } : x)) }),
        () => (r.voted_helpful ? api.del(`/api/reviews/${r.id}/helpful`) : api.post(`/api/reviews/${r.id}/helpful`)))
      setQueryData<ReviewsPage>(key, (d) => (d ? { ...d, items: d.items.map((x) => (x.id === r.id ? { ...x, helpful_count: result.helpful_count, voted_helpful: result.voted } : x)) } : d as unknown as ReviewsPage))
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      voting.current.delete(r.id)
    }
  }

  const dist = reviews.data?.distribution ?? {}
  const totalRatings = Object.values(dist).reduce((a, b) => a + b, 0)
  const showForm = !!user && (editing || !mine)
  const items = reviews.data?.items ?? []
  const canLoadMore = (reviews.data?.total ?? 0) > items.length && limit < REVIEW_PAGE_LIMIT

  return (
    <section aria-labelledby="reviews" className="grid gap-10 lg:grid-cols-[280px_minmax(0,1fr)]">
      <div className="min-w-0">
        <h2 id="reviews" className="section-title">Ratings & reviews</h2>
        <p className="mt-1 text-sm text-muted">From BookWorm readers only.</p>
        <div className="mt-4 space-y-1.5">
          {[5, 4, 3, 2, 1].map((s) => (
            <div key={s} className="flex items-center gap-2 text-xs">
              <span className="w-6">{s}★</span>
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-parchment"><div className="h-full bg-gold transition-[width] duration-300" style={{ width: `${totalRatings ? (100 * (dist[s] ?? 0)) / totalRatings : 0}%` }} /></div>
              <span className="w-6 text-right text-muted">{dist[s] ?? 0}</span>
            </div>
          ))}
        </div>
        {!user ? <p className="mt-6 text-sm"><Link to={`/login?next=/books/${book.id}`} className="link">Log in</Link> to rate and review.</p> : mine && !editing ? (
          <div className="card mt-6 p-4">
            <p className="text-sm font-medium">Your rating</p>
            <Stars value={mine.rating} size="md" />
            {mine.body && <p className="user-text mt-2 line-clamp-4 text-sm text-ink-soft">{mine.body}</p>}
            <div className="mt-3 flex gap-2"><button className="btn-outline btn-sm" onClick={startEdit}>Edit</button><button className="btn-ghost btn-sm" onClick={remove}><Trash2 className="h-3.5 w-3.5" aria-hidden />Delete</button></div>
          </div>
        ) : null}
      </div>

      <div className="min-w-0">
        {showForm && (
          <form className="card mb-6 space-y-3 p-4 sm:p-5" onSubmit={(e) => { e.preventDefault(); void save() }} noValidate>
            <p className="font-semibold">{mine ? 'Edit your review' : 'Rate this book'}</p>
            <StarInput value={rating} onChange={(v) => { setRating(v); setFormError(null) }} />
            <Field label="Your review (optional)" htmlFor="review-body" error={tooLong ? `Your review is ${(body.length - REVIEW_MAX_LENGTH).toLocaleString()} characters over the limit.` : undefined} errorId="review-err">
              <textarea id="review-body" className="input" rows={5} placeholder="What did you think?" value={body} onChange={(e) => setBody(e.target.value)} aria-invalid={tooLong} aria-describedby="review-count" />
            </Field>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex gap-2">
                <button className="btn-primary btn-sm" disabled={busy || !rating || tooLong}>{busy ? 'Saving…' : mine ? 'Save changes' : 'Post'}</button>
                {editing && <button type="button" className="btn-ghost btn-sm" onClick={() => setEditing(false)}>Cancel</button>}
              </div>
              <CharCounter id="review-count" value={body.length} max={REVIEW_MAX_LENGTH} warnAt={0.9} />
            </div>
            {formError && <p className="text-xs text-rust" role="alert">{formError}</p>}
          </form>
        )}
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm text-muted">{reviews.data?.total ?? 0} written review{reviews.data?.total === 1 ? '' : 's'}</p>
          <select aria-label="Sort reviews" className="input w-auto py-1.5" value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="helpful">Most helpful</option><option value="recent">Most recent</option>
            <option value="rating_high">Highest rated</option><option value="rating_low">Lowest rated</option>
          </select>
        </div>
        {reviews.loading ? <ListSkeleton rows={2} /> : reviews.error ? <ErrorState error={reviews.error} onRetry={reviews.reload} /> : (
          items.length === 0 ? <p className="text-sm text-muted">No written reviews yet. Be the first!</p> : (
            <>
              <ul className={`space-y-4 transition-opacity ${reviews.refreshing ? 'opacity-70' : ''}`}>
                {items.map((r) => (
                  <li key={r.id} className="card min-w-0 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex min-w-0 items-center gap-2 text-sm"><strong className="truncate">{r.user_display_name}</strong><Stars value={r.rating} /></div>
                      <span className="text-xs text-muted">{date(r.updated_at)}</span>
                    </div>
                    {r.body && <ReviewBody text={r.body} />}
                    <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
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
              {canLoadMore && <div className="mt-4 text-center"><button className="btn-outline btn-sm" disabled={reviews.refreshing} onClick={() => setLimit((n) => Math.min(n + REVIEW_PAGE, REVIEW_PAGE_LIMIT))}>Show more reviews</button></div>}
            </>
          )
        )}
      </div>
      {reportId && <ReportDialog open onClose={() => setReportId(null)} endpoint={`/api/reviews/${reportId}/report`} what="review" />}
    </section>
  )
}
