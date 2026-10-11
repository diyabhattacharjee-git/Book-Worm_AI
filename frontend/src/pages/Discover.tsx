import { BookPlus, Filter, Globe, SearchX } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { BookCard, BookGrid } from '../components/books'
import { BookGridSkeleton, EmptyState, ErrorState, Notice, PageHeader, Pagination, Spinner } from '../components/ui'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import type { BookDetail, BookSummary, Page } from '../types'
import { languageName } from '../utils/format'

interface Facets {
  genres: { name: string; slug: string; count: number }[]
  languages: { code: string; count: number }[]
  formats: string[]
  year_range: [number | null, number | null]
}

interface ExternalResult {
  title: string
  authors: string[]
  published_year: number | null
  isbns: string[]
  cover_url: string | null
  source: string
  info_url: string | null
  in_catalogue_book_id: number | null
}

const SORTS = [
  ['relevance', 'Relevance'], ['popularity', 'Popularity'], ['rating', 'Rating'], ['title', 'Title A–Z'],
  ['year_desc', 'Newest first'], ['year_asc', 'Oldest first'], ['price', 'Lowest used price'],
] as const

const FILTER_KEYS = ['genre', 'author', 'language', 'year_min', 'year_max', 'min_rating', 'pages_max', 'format', 'availability'] as const

export default function Discover() {
  const [params, setParams] = useSearchParams()
  const [showFilters, setShowFilters] = useState(false)
  const q = params.get('q') ?? ''
  const page = Number(params.get('page') ?? 1)
  const [term, setTerm] = useState(q)
  useEffect(() => setTerm(q), [q])

  const facets = useApi(() => api.get<Facets>('/api/books/facets'), [])
  const query = Object.fromEntries([...params.entries()])
  const results = useApi(() => api.get<Page<BookSummary>>('/api/books', { ...query, page_size: 20 }), [params.toString()])

  function update(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(changes)) {
      if (v) next.set(k, v)
      else next.delete(k)
    }
    if (!('page' in changes)) next.delete('page')
    setParams(next)
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    update({ q: term.trim() || null })
  }

  const activeFilters = FILTER_KEYS.filter((k) => params.get(k))

  return (
    <div>
      <PageHeader eyebrow="Catalogue" title="Discover books">
        Search by title, author, ISBN, genre, publisher or keywords. Prefer plain language? Try <Link to="/search" className="link">Smart Search</Link>.
      </PageHeader>

      <form onSubmit={submit} className="mb-6 flex flex-col gap-2 sm:flex-row" role="search">
        <label htmlFor="discover-q" className="sr-only">Search the catalogue</label>
        <input id="discover-q" className="input py-2.5" value={term} onChange={(e) => setTerm(e.target.value)} placeholder="e.g. Kahneman, 9780132350884, thriller, Penguin…" />
        <div className="flex gap-2">
          <button className="btn-primary">Search</button>
          <button type="button" className="btn-outline lg:hidden" onClick={() => setShowFilters((s) => !s)} aria-expanded={showFilters}>
            <Filter className="h-4 w-4" aria-hidden /> Filters{activeFilters.length ? ` (${activeFilters.length})` : ''}
          </button>
        </div>
      </form>

      <div className="grid gap-8 lg:grid-cols-[240px_1fr]">
        <aside className={`${showFilters ? 'block' : 'hidden'} space-y-5 lg:block`} aria-label="Filters">
          <div>
            <label className="label" htmlFor="f-genre">Genre</label>
            <select id="f-genre" className="input" value={params.get('genre') ?? ''} onChange={(e) => update({ genre: e.target.value || null })}>
              <option value="">All genres</option>
              {facets.data?.genres.map((g) => <option key={g.slug} value={g.slug}>{g.name} ({g.count})</option>)}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="f-author">Author</label>
            <input id="f-author" className="input" defaultValue={params.get('author') ?? ''} placeholder="Any author"
              onBlur={(e) => update({ author: e.target.value.trim() || null })} onKeyDown={(e) => { if (e.key === 'Enter') update({ author: (e.target as HTMLInputElement).value.trim() || null }) }} />
          </div>
          <div>
            <label className="label" htmlFor="f-lang">Language</label>
            <select id="f-lang" className="input" value={params.get('language') ?? ''} onChange={(e) => update({ language: e.target.value || null })}>
              <option value="">Any language</option>
              {facets.data?.languages.map((l) => <option key={l.code} value={l.code}>{languageName(l.code)} ({l.count})</option>)}
            </select>
          </div>
          <fieldset>
            <legend className="label">Publication year</legend>
            <div className="flex gap-2">
              <input aria-label="From year" type="number" className="input" placeholder={String(facets.data?.year_range[0] ?? 'From')} defaultValue={params.get('year_min') ?? ''} onBlur={(e) => update({ year_min: e.target.value || null })} />
              <input aria-label="To year" type="number" className="input" placeholder={String(facets.data?.year_range[1] ?? 'To')} defaultValue={params.get('year_max') ?? ''} onBlur={(e) => update({ year_max: e.target.value || null })} />
            </div>
          </fieldset>
          <div>
            <label className="label" htmlFor="f-rating">Minimum rating</label>
            <select id="f-rating" className="input" value={params.get('min_rating') ?? ''} onChange={(e) => update({ min_rating: e.target.value || null })}>
              <option value="">Any rating</option>
              {[4.5, 4, 3.5, 3].map((r) => <option key={r} value={r}>{r}★ & up</option>)}
            </select>
            <p className="mt-1 text-xs text-muted">Uses BookWorm ratings, or the external rating when a book has none.</p>
          </div>
          <div>
            <label className="label" htmlFor="f-pages">Length</label>
            <select id="f-pages" className="input" value={params.get('pages_max') ?? ''} onChange={(e) => update({ pages_max: e.target.value || null })}>
              <option value="">Any length</option>
              <option value="200">Up to 200 pages</option>
              <option value="300">Up to 300 pages</option>
              <option value="450">Up to 450 pages</option>
            </select>
            <p className="mt-1 text-xs text-muted">Books with unknown page counts are hidden by this filter.</p>
          </div>
          <div>
            <label className="label" htmlFor="f-format">Format</label>
            <select id="f-format" className="input" value={params.get('format') ?? ''} onChange={(e) => update({ format: e.target.value || null })}>
              <option value="">Any format</option>
              {facets.data?.formats.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={params.get('availability') === 'used'} onChange={(e) => update({ availability: e.target.checked ? 'used' : null })} />
            Only books with used copies for sale
          </label>
          {activeFilters.length > 0 && (
            <button className="btn-ghost btn-sm" onClick={() => update(Object.fromEntries(FILTER_KEYS.map((k) => [k, null])))}>Clear filters</button>
          )}
        </aside>

        <section aria-live="polite">
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-muted">
              {results.loading ? 'Searching…' : results.data ? `${results.data.total} book${results.data.total === 1 ? '' : 's'}${q ? ` for “${q}”` : ''}` : ''}
            </p>
            <label className="flex items-center gap-2 text-sm">
              <span className="text-muted">Sort by</span>
              <select className="input w-auto py-1.5" value={params.get('sort') ?? 'relevance'} onChange={(e) => update({ sort: e.target.value })}>
                {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
          </div>
          {results.loading ? <BookGridSkeleton count={10} />
            : results.error ? <ErrorState error={results.error} onRetry={results.reload} />
              : results.data!.items.length === 0 ? (
                <EmptyState icon={<SearchX className="h-6 w-6" />} title="No books match"
                  action={activeFilters.length ? <button className="btn-outline" onClick={() => update(Object.fromEntries(FILTER_KEYS.map((k) => [k, null])))}>Clear filters</button> : undefined}>
                  Try a broader search{activeFilters.length ? ' or remove some filters' : ''}. You can also look it up in public catalogues below.
                </EmptyState>
              ) : (
                <>
                  <BookGrid>{results.data!.items.map((b) => <BookCard key={b.id} book={b} />)}</BookGrid>
                  <Pagination page={page} total={results.data!.total} pageSize={20} onPage={(p) => update({ page: String(p) })} />
                </>
              )}
          {q && !results.loading && <ExternalLookup query={q} />}
        </section>
      </div>
    </div>
  )
}

function ExternalLookup({ query }: { query: string }) {
  const { user } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [importing, setImporting] = useState<string | null>(null)
  const ext = useApi(() => api.get<{ results: ExternalResult[]; errors: string[] }>('/api/books/external-search', { q: query }), [query, open], open)

  async function importIsbn(isbn: string) {
    setImporting(isbn)
    try {
      const b = await api.post<BookDetail>('/api/books/import', { isbn })
      toast.success(`Added “${b.title}” to the catalogue.`)
      navigate(`/books/${b.id}`)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setImporting(null)
    }
  }

  return (
    <div className="mt-10 border-t border-line pt-6">
      {!open ? (
        <button className="btn-outline" onClick={() => setOpen(true)}><Globe className="h-4 w-4" aria-hidden /> Search Open Library & Google Books for “{query}”</button>
      ) : (
        <div>
          <h2 className="text-xl font-semibold">From public catalogues</h2>
          <p className="mb-4 text-sm text-muted">Live results from Open Library and Google Books. Importing by ISBN stores the metadata locally.</p>
          {ext.loading && <Spinner label="Searching public catalogues" />}
          {ext.error && <ErrorState error={ext.error} onRetry={ext.reload} />}
          {ext.data?.errors.map((e) => <Notice key={e} tone="warn">{e}. Results from the other source are still shown.</Notice>)}
          {ext.data && ext.data.results.length === 0 && <p className="text-sm text-muted">No matches found.</p>}
          <ul className="mt-3 divide-y divide-line">
            {ext.data?.results.map((r) => (
              <li key={`${r.source}-${r.title}-${r.isbns[0]}`} className="flex flex-wrap items-center gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{r.title} <span className="text-xs text-muted">({r.source.replace('_', ' ')})</span></p>
                  <p className="text-sm text-muted">{r.authors.join(', ') || 'Unknown author'}{r.published_year ? ` · ${r.published_year}` : ''}{r.isbns[0] ? ` · ISBN ${r.isbns[0]}` : ''}</p>
                </div>
                {r.in_catalogue_book_id ? <Link to={`/books/${r.in_catalogue_book_id}`} className="btn-outline btn-sm">In catalogue</Link>
                  : r.isbns[0] ? (user
                    ? <button className="btn-forest btn-sm" disabled={importing !== null} onClick={() => importIsbn(r.isbns[0])}><BookPlus className="h-4 w-4" aria-hidden />{importing === r.isbns[0] ? 'Importing…' : 'Import'}</button>
                    : <Link to="/login?next=/discover" className="btn-outline btn-sm">Log in to import</Link>)
                    : <span className="text-xs text-muted">No ISBN to import</span>}
                {r.info_url && <a href={r.info_url} target="_blank" rel="noopener noreferrer" className="link text-sm">Source</a>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
