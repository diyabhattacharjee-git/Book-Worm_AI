import { AlertTriangle, BookCheck, ChevronDown, Scale, SlidersHorizontal } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'
import { BookCover } from '../components/books'
import { DealCard, PriceEstimateCard, VerdictBadge, WorkflowStatus } from '../components/marketplace'
import { Badge, EmptyState, ErrorState, Notice, PageHeader } from '../components/ui'
import { ApiError, streamNdjson } from '../services/api'
import type { Deal, TraceStep, UsedSearchResult } from '../types'
import { CONDITION_LABELS, money } from '../utils/format'

interface Form {
  query: string
  title: string
  author: string
  isbn: string
  max_price: string
  currency: string
  min_condition: string
  location: string
  delivery: 'any' | 'pickup' | 'shipping'
  include_external: boolean
}

const EMPTY: Form = { query: '', title: '', author: '', isbn: '', max_price: '', currency: 'INR', min_condition: '', location: '', delivery: 'any', include_external: true }

export default function UsedSearch() {
  const [params] = useSearchParams()
  const [form, setForm] = useState<Form>({ ...EMPTY, query: params.get('q') ?? '', title: params.get('title') ?? '', isbn: params.get('isbn') ?? '' })
  const [advanced, setAdvanced] = useState(!!(params.get('title') || params.get('isbn')))
  const [steps, setSteps] = useState<TraceStep[]>([])
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<UsedSearchResult | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  async function run(f: Form = form) {
    if (!f.query.trim() && !f.title.trim() && !f.isbn.trim()) return
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setRunning(true)
    setSteps([])
    setResult(null)
    setError(null)
    const body = {
      query: f.query.trim() || null, title: f.title.trim() || null, author: f.author.trim() || null, isbn: f.isbn.trim() || null,
      max_price: f.max_price ? Number(f.max_price) : null, currency: f.currency, min_condition: f.min_condition || null,
      location: f.location.trim() || null, delivery: f.delivery, include_external: f.include_external,
    }
    try {
      await streamNdjson('/api/marketplace/search-used-books/stream', body, (raw) => {
        const e = raw as { type: string; data?: UsedSearchResult; detail?: string } & TraceStep
        if (e.type === 'step') setSteps((s) => [...s, e])
        else if (e.type === 'result' && e.data) setResult(e.data)
        else if (e.type === 'error') setError(new ApiError(500, e.detail ?? 'Search failed'))
      }, ctrl.signal)
    } catch (e) {
      setError(e as ApiError)
    } finally {
      if (abortRef.current === ctrl) setRunning(false)
    }
  }

  useEffect(() => {
    // Auto-run when arriving with a query. In StrictMode the effect runs twice: the
    // cleanup aborts the first stream and the second mount starts a fresh one.
    if (form.query || form.title || form.isbn) void run()
    return () => abortRef.current?.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => ({ ...f, [k]: v }))

  return (
    <div>
      <PageHeader eyebrow="Used-book deal finder" title="Find a fairly priced used copy">
        Describe what you want. A multi-step workflow identifies the book, searches community listings (and eBay when configured), validates and de-duplicates results, estimates a fair price range from comparable listings, and ranks the deals.
      </PageHeader>

      <form onSubmit={(e: FormEvent) => { e.preventDefault(); void run() }} className="card p-5">
        <label htmlFor="used-q" className="label">What are you looking for?</label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input id="used-q" className="input py-3 text-base" value={form.query} onChange={(e) => set('query', e.target.value)}
            placeholder="I want a used copy of Atomic Habits under ₹250 in good condition" maxLength={500} />
          <button className="btn-primary py-3" disabled={running}><Scale className="h-4 w-4" aria-hidden />{running ? 'Searching…' : 'Find deals'}</button>
        </div>
        <button type="button" className="mt-3 inline-flex items-center gap-1 text-sm text-ink-soft hover:text-ink" onClick={() => setAdvanced((a) => !a)} aria-expanded={advanced}>
          <SlidersHorizontal className="h-4 w-4" aria-hidden />Exact details (optional)<ChevronDown className={`h-4 w-4 transition-transform ${advanced ? 'rotate-180' : ''}`} aria-hidden />
        </button>
        {advanced && (
          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div><label className="label" htmlFor="u-title">Title</label><input id="u-title" className="input" value={form.title} onChange={(e) => set('title', e.target.value)} /></div>
            <div><label className="label" htmlFor="u-author">Author</label><input id="u-author" className="input" value={form.author} onChange={(e) => set('author', e.target.value)} /></div>
            <div><label className="label" htmlFor="u-isbn">ISBN</label><input id="u-isbn" className="input" value={form.isbn} onChange={(e) => set('isbn', e.target.value)} /></div>
            <div>
              <label className="label" htmlFor="u-price">Max total price</label>
              <div className="flex gap-1">
                <select aria-label="Currency" className="input w-20" value={form.currency} onChange={(e) => set('currency', e.target.value)}><option>INR</option><option>USD</option></select>
                <input id="u-price" type="number" min={1} className="input" value={form.max_price} onChange={(e) => set('max_price', e.target.value)} />
              </div>
            </div>
            <div>
              <label className="label" htmlFor="u-cond">Minimum condition</label>
              <select id="u-cond" className="input" value={form.min_condition} onChange={(e) => set('min_condition', e.target.value)}>
                <option value="">Any</option>{['like_new', 'very_good', 'good', 'acceptable'].map((c) => <option key={c} value={c}>{CONDITION_LABELS[c]}</option>)}
              </select>
            </div>
            <div><label className="label" htmlFor="u-loc">City</label><input id="u-loc" className="input" value={form.location} onChange={(e) => set('location', e.target.value)} /></div>
            <div>
              <label className="label" htmlFor="u-del">Delivery</label>
              <select id="u-del" className="input" value={form.delivery} onChange={(e) => set('delivery', e.target.value as Form['delivery'])}>
                <option value="any">Any</option><option value="pickup">Pickup</option><option value="shipping">Shipping</option>
              </select>
            </div>
            <label className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" checked={form.include_external} onChange={(e) => set('include_external', e.target.checked)} />Include external marketplaces</label>
          </div>
        )}
        <p className="mt-3 text-xs text-muted">Typed details override what’s understood from the sentence.</p>
      </form>

      <div className="mt-8 grid gap-8 lg:grid-cols-[300px_1fr]">
        <aside className="space-y-4">
          <WorkflowStatus steps={steps} running={running} />
          {result?.providers && result.providers.length > 0 && (
            <div className="card p-4 text-sm">
              <p className="mb-2 font-semibold">Sources</p>
              <ul className="space-y-1.5">
                {result.providers.map((p) => (
                  <li key={p.provider} className="flex items-start justify-between gap-2">
                    <span>{p.label}</span>
                    {p.ok ? <Badge tone="forest">{p.count} found</Badge> : <Badge tone={p.error ? 'rust' : 'neutral'} title={p.error ?? p.skipped ?? ''}>{p.error ? 'Unavailable' : 'Not used'}</Badge>}
                  </li>
                ))}
              </ul>
              {result.providers.filter((p) => !p.ok).map((p) => <p key={p.provider} className="mt-2 text-xs text-muted">{p.label}: {p.error ?? p.skipped}</p>)}
            </div>
          )}
        </aside>
        <section aria-live="polite" className="min-w-0 space-y-6">
          {error && <ErrorState error={error} onRetry={() => run()} />}
          {!running && !result && !error && (
            <EmptyState icon={<Scale className="h-6 w-6" />} title="Ask about any book">Try: “Clean Code under ₹500 with pickup in Kolkata” or “Is ₹300 a fair price for The Alchemist?”</EmptyState>
          )}
          {result && <Results result={result} />}
        </section>
      </div>
    </div>
  )
}

function Results({ result }: { result: UsedSearchResult }) {
  const [showExcluded, setShowExcluded] = useState(false)
  if (result.status === 'needs_clarification') {
    return <Notice tone="warn" title="Which book?">{result.summary.text}</Notice>
  }
  const groups: [Deal['deal']['group'], string][] = [['match', 'Best options'], ['near_match', 'Near matches'], ['other', 'Other listings']]
  const b = result.book
  let rank = 0
  return (
    <>
      <div className="card p-5">
        <p className="eyebrow mb-1">Summary</p>
        <p className="text-ink">{result.summary.text}</p>
      </div>

      {b && (
        <div className="card flex gap-4 p-4">
          {b.found && <div className="w-14 shrink-0"><BookCover title={b.title ?? ''} url={b.cover_url} size="sm" /></div>}
          <div className="min-w-0 flex-1 text-sm">
            <p className="flex flex-wrap items-center gap-2 font-semibold"><BookCheck className="h-4 w-4 text-forest" aria-hidden />
              {b.found ? <>{b.book_id ? <Link to={`/books/${b.book_id}`} className="hover:text-forest">{b.title}</Link> : b.title}</> : 'Book not identified'}
              {b.found && <Badge tone="sky" title="Identification confidence (1.0 = exact ISBN match)">match confidence {b.confidence.toFixed(2)}</Badge>}
              {b.ambiguous && <Badge tone="gold">Ambiguous</Badge>}
            </p>
            {b.authors.length > 0 && <p className="text-muted">{b.authors.join(', ')}</p>}
            {b.notes.map((n) => <p key={n} className="text-xs text-muted">{n}</p>)}
            {b.ambiguous && b.candidates.length > 0 && (
              <p className="mt-1 text-xs">Did you mean: {b.candidates.slice(1).map((c, i) => <span key={i}>{i > 0 && ', '}{c.book_id ? <Link className="link" to={`/marketplace/find?title=${encodeURIComponent(c.title)}`} reloadDocument>{c.title}</Link> : c.title}</span>)}</p>
            )}
          </div>
        </div>
      )}

      {result.asking_price_verdict && (
        <Notice tone="info" title={`Your quoted price: ${money(result.asking_price_verdict.price ?? null, result.params?.currency ?? 'INR')}`}>
          <span className="mr-2"><VerdictBadge verdict={result.asking_price_verdict} /></span>{result.asking_price_verdict.text}
        </Notice>
      )}
      {result.estimate && <PriceEstimateCard estimate={result.estimate} />}

      {result.deals.length === 0 && result.status !== 'ok' && (
        <EmptyState title="No matching listings right now" action={<Link to="/sell" className="btn-outline">Selling one? List it</Link>}>
          Nothing available was found for this book in the searched sources.
        </EmptyState>
      )}

      {groups.map(([g, label]) => {
        const deals = result.deals.filter((d) => d.deal.group === g)
        if (!deals.length) return null
        return (
          <div key={g}>
            <h2 className="mb-3 text-xl font-semibold">{label} <span className="text-base font-normal text-muted">({deals.length})</span></h2>
            <div className="space-y-4">{deals.map((d) => <DealCard key={d.listing.uid} deal={d} rank={++rank} />)}</div>
          </div>
        )
      })}

      {result.excluded.length > 0 && (
        <div>
          <button className="link text-sm" onClick={() => setShowExcluded((s) => !s)} aria-expanded={showExcluded}>{showExcluded ? 'Hide' : 'Show'} {result.excluded.length} excluded result(s)</button>
          {showExcluded && (
            <ul className="mt-2 space-y-1 text-sm text-muted">
              {result.excluded.map((e) => <li key={e.uid}>“{e.title}” ({e.provider}): {e.reason}</li>)}
            </ul>
          )}
        </div>
      )}
      {result.errors.length > 0 && <Notice tone="warn" title="Some steps had problems">{result.errors.join(' · ')}</Notice>}
      <ul className="space-y-1 border-t border-line pt-4 text-xs text-muted">
        {result.disclaimers.map((d) => <li key={d} className="flex gap-1.5"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />{d}</li>)}
      </ul>
    </>
  )
}
