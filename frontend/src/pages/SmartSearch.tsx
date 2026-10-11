import { Sparkles, Wand2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { BookCard, BookGrid } from '../components/books'
import { Badge, BookGridSkeleton, EmptyState, ErrorState, Notice, PageHeader } from '../components/ui'
import { ApiError, api } from '../services/api'
import type { BookSummary } from '../types'

interface NLResult {
  query: Record<string, unknown>
  interpreted_as: string[]
  results: { book: BookSummary; score: number; semantic_similarity: number; why: string[] }[]
  search_backend: string
  notes: string[]
}

const EXAMPLES = [
  'Suggest a beginner-friendly book on machine learning',
  'I want a psychological thriller with an unexpected ending',
  'Recommend something similar to The Alchemist',
  'Find a practical book about personal finance for students',
  'I want a short, inspiring book that I can finish in a weekend',
]
const REFINEMENTS = ['Shorter', 'Longer', 'More technical', 'Simpler', 'Cheaper used copies']

export default function SmartSearch() {
  const [q, setQ] = useState('')
  const [refine, setRefine] = useState('')
  const [result, setResult] = useState<NLResult | null>(null)
  const [history, setHistory] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  async function run(body: object, label: string) {
    setLoading(true)
    setError(null)
    try {
      const r = await api.post<NLResult>('/api/books/nl-search', body)
      setResult(r)
      setHistory((h) => [...h, label])
    } catch (e) {
      setError(e as ApiError)
    } finally {
      setLoading(false)
    }
  }

  function search(e?: FormEvent, text = q) {
    e?.preventDefault()
    if (!text.trim()) return
    setQ(text)
    setHistory([])
    void run({ query: text.trim() }, text.trim())
  }

  function applyRefinement(text: string) {
    if (!result || !text.trim()) return
    setRefine('')
    void run({ refinement: text.trim(), previous: result.query }, text.trim())
  }

  return (
    <div>
      <PageHeader eyebrow="Smart search" title="Describe what you feel like reading">
        Ask in plain language. We turn it into filters (length, level, language, “similar to…”) and rank catalogue books by meaning, keywords and ratings.
      </PageHeader>

      <form onSubmit={search} className="card p-4 sm:p-5" role="search">
        <label htmlFor="nl-q" className="label">Your request</label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input id="nl-q" className="input py-3 text-base" value={q} onChange={(e) => setQ(e.target.value)} placeholder={EXAMPLES[4]} maxLength={300} />
          <button className="btn-primary py-3" disabled={loading || !q.trim()}><Sparkles className="h-4 w-4" aria-hidden />Search</button>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => <button key={ex} type="button" className="chip hover:border-ink-soft" onClick={() => search(undefined, ex)}>{ex}</button>)}
        </div>
      </form>

      <div className="mt-8" aria-live="polite">
        {error && <ErrorState error={error} />}
        {loading && <BookGridSkeleton count={5} />}
        {!loading && result && (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              {history.length > 1 && <span className="text-muted">{history.join(' → ')}</span>}
              {result.interpreted_as.length > 0 && <><span className="text-muted">Interpreted as:</span>{result.interpreted_as.map((i) => <Badge key={i} tone="sky">{i}</Badge>)}</>}
            </div>
            {result.notes.map((n) => <Notice key={n} tone="info">{n}</Notice>)}

            <div className="card flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
              <p className="flex items-center gap-2 text-sm font-medium"><Wand2 className="h-4 w-4 text-gold-dark" aria-hidden />Refine:</p>
              <div className="flex flex-wrap gap-2">
                {REFINEMENTS.map((r) => <button key={r} className="chip hover:border-ink-soft" onClick={() => applyRefinement(r)}>{r}</button>)}
              </div>
              <form className="flex flex-1 gap-2" onSubmit={(e) => { e.preventDefault(); applyRefinement(refine) }}>
                <label htmlFor="refine" className="sr-only">Custom refinement</label>
                <input id="refine" className="input" placeholder="or type: “more about startups”" value={refine} onChange={(e) => setRefine(e.target.value)} />
                <button className="btn-outline" disabled={!refine.trim()}>Apply</button>
              </form>
            </div>

            {result.results.length === 0 ? (
              <EmptyState title="No matching books">Try removing a constraint, or search the public catalogues from Discover.</EmptyState>
            ) : (
              <BookGrid>
                {result.results.map((r) => (
                  <BookCard key={r.book.id} book={r.book} why={r.why.length ? <span>Why: {r.why.join('; ')}</span> : undefined} />
                ))}
              </BookGrid>
            )}
          </div>
        )}
        {!loading && !result && !error && (
          <p className="text-center text-sm text-muted">Results appear here.</p>
        )}
      </div>
    </div>
  )
}
