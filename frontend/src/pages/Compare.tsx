import { Plus, Scale, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { BookCover } from '../components/books'
import { ComparisonTable } from '../components/ComparisonTable'
import { EmptyState, ErrorState, PageHeader, Spinner } from '../components/ui'
import { useApi, useDebounced } from '../hooks/useApi'
import { ApiError, api } from '../services/api'
import type { BookSummary, ComparisonData, Page } from '../types'

export default function Compare() {
  const [params, setParams] = useSearchParams()
  const ids = (params.get('ids') ?? '').split(',').map(Number).filter(Boolean).slice(0, 4)
  const [goal, setGoal] = useState(params.get('goal') ?? '')
  const [q, setQ] = useState('')
  const dq = useDebounced(q)
  const found = useApi(() => api.get<Page<BookSummary>>('/api/books', { q: dq, page_size: 6 }), [dq], dq.length > 1)
  const chosen = useApi(() => Promise.all(ids.map((id) => api.get<BookSummary>(`/api/books/${id}`))), [ids.join(',')], ids.length > 0)
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
    setLoading(true)
    setError(null)
    try {
      setResult(await api.post<ComparisonData>('/api/books/compare', { book_ids: ids, goal: goal.trim() || null }))
    } catch (e) {
      setError(e as ApiError)
    } finally {
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
          {(chosen.data ?? []).map((b) => (
            <div key={b.id} className="relative w-24">
              <BookCover title={b.title} authors={b.authors} url={b.cover_url} size="sm" />
              <p className="mt-1 text-xs font-medium line-clamp-2">{b.title}</p>
              <button className="absolute -right-2 -top-2 rounded-full bg-paper p-1 shadow" aria-label={`Remove ${b.title}`} onClick={() => setIds(ids.filter((i) => i !== b.id))}><X className="h-3.5 w-3.5" /></button>
            </div>
          ))}
          {ids.length < 4 && (
            <div className="min-w-[240px] flex-1">
              <label className="label" htmlFor="cmp-search">Add a book</label>
              <input id="cmp-search" className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by title or author" />
              {found.data && dq.length > 1 && (
                <ul className="mt-2 divide-y divide-line rounded-lg border border-line bg-white">
                  {found.data.items.filter((b) => !ids.includes(b.id)).map((b) => (
                    <li key={b.id}><button className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-parchment" onClick={() => { setIds([...ids, b.id]); setQ('') }}><Plus className="h-3.5 w-3.5" aria-hidden />{b.title} <span className="text-muted">· {b.authors.join(', ')}</span></button></li>
                  ))}
                  {found.data.items.length === 0 && <li className="px-3 py-2 text-sm text-muted">No matches</li>}
                </ul>
              )}
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
