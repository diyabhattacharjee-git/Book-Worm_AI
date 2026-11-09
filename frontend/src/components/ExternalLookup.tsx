import { BookPlus, Globe } from 'lucide-react'
import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { TTL, useGet } from '../hooks/useApi'
import { api } from '../services/api'
import type { BookDetail } from '../types'
import { BookCover } from './books'
import { Badge, ErrorState, Notice, Spinner } from './ui'

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

/** Live results from Google Books and Open Library for books the catalogue doesn't hold yet. */
export function ExternalLookup({ query, autoOpen }: { query: string; autoOpen: boolean }) {
  const { user } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const location = useLocation()
  const [open, setOpen] = useState(autoOpen)
  const [importing, setImporting] = useState<string | null>(null)
  const ext = useGet<{ results: ExternalResult[]; errors: string[] }>('/api/books/external-search', { q: query }, { enabled: open, ttl: TTL.long })
  const loginLink = `/login?next=${encodeURIComponent(location.pathname + location.search)}`

  async function importIsbn(isbn: string, source: string) {
    setImporting(isbn)
    try {
      const b = await api.post<BookDetail>('/api/books/import', { isbn, source })
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
        <button className="btn-outline max-w-full whitespace-normal" onClick={() => setOpen(true)}><Globe className="h-4 w-4 shrink-0" aria-hidden /> Search Google Books & Open Library for “{query}”</button>
      ) : (
        <div>
          <h2 className="text-xl font-semibold">From public catalogues</h2>
          <p className="mb-4 text-sm text-muted">Results from Google Books and Open Library. Importing adds the book to the catalogue.</p>
          {ext.loading && <Spinner label="Searching public catalogues" />}
          {ext.error && <ErrorState error={ext.error} onRetry={ext.reload} />}
          {ext.data?.errors.map((e) => <Notice key={e} tone="warn">{e}. Showing what the other source found.</Notice>)}
          {ext.data && ext.data.results.length === 0 && <p className="text-sm text-muted">No matches found.</p>}
          <ul className="mt-3 divide-y divide-line">
            {ext.data?.results.map((r) => (
              <li key={`${r.source}-${r.title}-${r.isbns[0]}`} className="flex flex-wrap items-center gap-3 py-3">
                <div className="w-12 shrink-0"><BookCover title={r.title} authors={r.authors} url={r.cover_url} size="sm" /></div>
                <div className="min-w-0 flex-1 basis-40">
                  <p className="user-text font-medium">{r.title}</p>
                  <div className="mt-0.5"><Badge tone={r.source === 'google_books' ? 'sky' : 'neutral'}>{r.source === 'google_books' ? 'Google Books' : 'Open Library'}</Badge></div>
                  <p className="text-sm text-muted">{r.authors.join(', ') || 'Unknown author'}{r.published_year ? ` · ${r.published_year}` : ''}{r.isbns[0] ? ` · ISBN ${r.isbns[0]}` : ''}</p>
                </div>
                {r.in_catalogue_book_id ? <Link to={`/books/${r.in_catalogue_book_id}`} className="btn-outline btn-sm">In catalogue</Link>
                  : r.isbns[0] ? (user
                    ? <button className="btn-forest btn-sm" disabled={importing !== null} onClick={() => importIsbn(r.isbns[0], r.source)}><BookPlus className="h-4 w-4" aria-hidden />{importing === r.isbns[0] ? 'Importing…' : 'Import'}</button>
                    : <Link to={loginLink} className="btn-outline btn-sm">Log in to import</Link>)
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
