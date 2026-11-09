import { useState, type ReactNode } from 'react'
import { TTL, useDebounced, useGet } from '../hooks/useApi'
import type { BookSummary, Page } from '../types'
import { authorsText } from '../utils/format'
import { Spinner } from './ui'

const MIN_QUERY = 2
const SEARCH_DELAY_MS = 300

/** Type-to-find picker over the catalogue. Waits for a pause in typing, and repeat searches come from the cache. */
export function BookSearch({ id, label, placeholder = 'Search by title, author or ISBN', onPick, exclude = [], describe, emptyText = 'No matches in the catalogue.', pageSize = 5 }: {
  id: string
  label?: string
  placeholder?: string
  onPick: (book: BookSummary) => void
  exclude?: number[]
  describe?: (book: BookSummary) => ReactNode
  emptyText?: string
  pageSize?: number
}) {
  const [q, setQ] = useState('')
  const term = useDebounced(q.trim(), SEARCH_DELAY_MS)
  const ready = term.length >= MIN_QUERY
  const found = useGet<Page<BookSummary>>(ready ? '/api/books' : null, { q: term, page_size: pageSize, track: false }, { ttl: TTL.long })
  const items = found.data?.items.filter((b) => !exclude.includes(b.id)) ?? []

  return (
    <div>
      <label htmlFor={id} className={label ? 'label' : 'sr-only'}>{label ?? placeholder}</label>
      <input id={id} className="input" placeholder={placeholder} value={q} onChange={(e) => setQ(e.target.value)} maxLength={200} autoComplete="off"
        onKeyDown={(e) => { if (e.key === 'Escape') setQ('') }} />
      {ready && q.trim() && (
        <div className="mt-1 rounded-lg border border-line bg-white" aria-live="polite">
          {found.loading ? <div className="px-3 py-2"><Spinner label="Searching" /></div>
            : found.error ? <p className="px-3 py-2 text-sm text-rust">{found.error.message}</p>
              : items.length === 0 ? <p className="px-3 py-2 text-sm text-muted">{emptyText}</p>
                : (
                  <ul className="divide-y divide-line">
                    {items.map((b) => (
                      <li key={b.id}>
                        <button type="button" className="user-text w-full px-3 py-2 text-left text-sm hover:bg-parchment"
                          onClick={() => { onPick(b); setQ('') }}>
                          {b.title} <span className="text-muted">· {describe ? describe(b) : authorsText(b.authors)}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
        </div>
      )}
    </div>
  )
}
