import { Scale, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import { BookSearch } from '../components/BookSearch'
import { BookCover } from '../components/books'
import { ComparisonTable } from '../components/ComparisonTable'
import { EmptyState, ErrorState, PageHeader, Skeleton, Spinner } from '../components/ui'
import { TTL, useGet } from '../hooks/useApi'
import { ApiError, api } from '../services/api'
import type { BookSummary, ComparisonData } from '../types'

function ChosenBook({ id, onRemove }: { id: number; onRemove: () => void }) {
  const book = useGet<BookSummary>(`/api/books/${id}`, { track: false }, { ttl: TTL.long })
  if (book.loading) return <Skeleton className="h-36 w-24 rounded-xl" />
  if (book.error || !book.data) return <div className="w-24"><p className="text-xs text-rust">{book.error?.message ?? 'Unavailable'}</p><button className="link text-xs" onClick={onRemove}>Remove</button></div>
  const b = book.data
  return (
    <div className="relative w-24">
      <BookCover title={b.title} authors={b.authors} url={b.cover_url} size="sm" />
      <p className="mt-1 text-xs font-medium line-clamp-2">{b.title}</p>
      <button className="absolute -right-2 -top-2 rounded-full bg-paper p-1 shadow" aria-label={`Remove ${b.title}`} onClick={onRemove}><X className="h-3.5 w-3.5" /></button>
    </div>
  )
}

export default function Compare() {
  const [params, setParams] = useSearchParams()
  const ids = (params.get('ids') ?? '').split(',').map(Number).filter(Boolean).slice(0, 4)
  const [goal, setGoal] = useState(params.get('goal') ?? '')
  const comparing = useRef(false)
  const [result, setResult] = useState<ComparisonData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  function setIds(next: number[]) {
    const p = new URLSearchParams(params)
    if (next.length) p.set('ids', next.join(','))
    else p.delete('ids')
    setParams(p)
    setResult(null)
  }

  async function compare() {
    if (comparing.current) return
    comparing.current = true
    setLoading(true)
    setError(null)
    try {
      setResult(await api.post<ComparisonData>('/api/books/compare', { book_ids: ids, goal: goal.trim() || null }))
    } catch (e) {
      setError(e as ApiError)
    } finally {
      comparing.current = false
      setLoading(false)
    }
  }

  useEffect(() => {
    if (ids.length >= 2 && !result && !loading) void compare()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids.join(',')])

  return (
    <div>
      <PageHeader eyebrow="Compare" title="Compare books side by side">
        Pick two to four books. Missing information shows as “Not available” — nothing is guessed. Add a goal (e.g. “for a beginner”, “short read”) for evidence-based advice.
      </PageHeader>
      <div className="card p-5">
        <div className="flex flex-wrap gap-4">
          {ids.map((id) => <ChosenBook key={id} id={id} onRemove={() => setIds(ids.filter((i) => i !== id))} />)}
          {ids.length < 4 && (
            <div className="min-w-0 flex-1 basis-60">
              <BookSearch id="cmp-search" label="Add a book" placeholder="Search by title or author" pageSize={6} exclude={ids} onPick={(b) => setIds([...ids, b.id])} />
            </div>
          )}
        </div>
        <div className="mt-4 flex flex-col gap-2 sm:flex-row">
          <label htmlFor="cmp-goal" className="sr-only">Your goal</label>
          <input id="cmp-goal" className="input" value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="Optional goal: beginner, short read, best rated…" maxLength={200} />
          <button className="btn-primary" onClick={compare} disabled={ids.length < 2 || loading}><Scale className="h-4 w-4" aria-hidden />Compare</button>
        </div>
      </div>
      <div className="mt-8">
        {loading && <Spinner label="Comparing" />}
        {error && <ErrorState error={error} />}
        {!loading && result && <ComparisonTable data={result} />}
        {!loading && !result && ids.length < 2 && <EmptyState icon={<Scale className="h-6 w-6" />} title="Choose at least two books">Search above to add books to compare.</EmptyState>}
      </div>
    </div>
  )
}
