import { CalendarDays, CheckCircle2, Circle, Download, Plus, Trash2, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { Badge, EmptyState, ErrorState, Notice, PageHeader, Spinner } from '../components/ui'
import { useToast } from '../contexts/ToastContext'
import { useApi, useDebounced } from '../hooks/useApi'
import { ApiError, api } from '../services/api'
import type { BookSummary, Page, ReadingPlan, ShelfEntry } from '../types'
import { date } from '../utils/format'

const DAYS = [[1, 'Mon'], [2, 'Tue'], [3, 'Wed'], [4, 'Thu'], [5, 'Fri'], [6, 'Sat'], [7, 'Sun']] as const

interface Preview {
  pages_per_day: number
  minutes_per_day: number
  total_pages: number
  estimated_finish: string | null
  feasibility_note: string | null
  unscheduled: { book_id: number; title?: string; reason: string }[]
  days: { day: string; title: string; start_page: number; end_page: number }[]
}

export default function ReadingPlans() {
  const plans = useApi(() => api.get<ReadingPlan[]>('/api/reading-plans'), [])
  return (
    <div>
      <PageHeader eyebrow="Reading plans" title="Plan your reading">
        Schedules are built from real page counts and your own reading speed. BookWorm doesn’t send reminders — export the plan to your calendar instead.
      </PageHeader>
      <PlanBuilder onCreated={plans.reload} />
      <section className="mt-12" aria-labelledby="my-plans">
        <h2 id="my-plans" className="section-title">Your plans</h2>
        <div className="mt-5 space-y-6">
          {plans.loading ? <Spinner /> : plans.error ? <ErrorState error={plans.error} onRetry={plans.reload} />
            : plans.data!.length === 0 ? <EmptyState icon={<CalendarDays className="h-6 w-6" />} title="No plans yet">Build one above to get a day-by-day schedule.</EmptyState>
              : plans.data!.map((p) => <PlanCard key={p.id} plan={p} onChange={plans.reload} />)}
        </div>
      </section>
    </div>
  )
}

function PlanBuilder({ onCreated }: { onCreated: () => void }) {
  const toast = useToast()
  const [params] = useSearchParams()
  const shelf = useApi(() => api.get<{ items: ShelfEntry[] }>('/api/bookshelf'), [])
  const [books, setBooks] = useState<BookSummary[]>([])
  const [q, setQ] = useState('')
  const dq = useDebounced(q)
  const found = useApi(() => api.get<Page<BookSummary>>('/api/books', { q: dq, page_size: 5 }), [dq], dq.length > 1)
  const [minutes, setMinutes] = useState(30)
  const [ppm, setPpm] = useState(0.8)
  const [days, setDays] = useState<number[]>([1, 2, 3, 4, 5, 6, 7])
  const [start, setStart] = useState('')
  const [target, setTarget] = useState('')
  const [fit, setFit] = useState(false)
  const [overrides, setOverrides] = useState<Record<number, string>>({})
  const [preview, setPreview] = useState<Preview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const id = Number(params.get('book'))
    if (id && !books.some((b) => b.id === id)) {
      api.get<BookSummary>(`/api/books/${id}`).then((b) => setBooks((bs) => (bs.some((x) => x.id === b.id) ? bs : [...bs, b]))).catch(() => undefined)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params])

  function add(b: BookSummary) {
    if (!books.some((x) => x.id === b.id) && books.length < 10) setBooks([...books, b])
    setQ('')
    setPreview(null)
  }

  function body() {
    const page_overrides: Record<number, number> = {}
    for (const [k, v] of Object.entries(overrides)) if (Number(v) > 0) page_overrides[Number(k)] = Number(v)
    return {
      book_ids: books.map((b) => b.id), minutes_per_day: minutes, pages_per_minute: ppm, reading_days: days,
      start_date: start || null, target_date: target || null, fit_to_target: fit && !!target, page_overrides,
    }
  }

  async function generate(save: boolean) {
    setBusy(true)
    setError(null)
    try {
      if (save) {
        await api.post('/api/reading-plans', body())
        toast.success('Plan saved.')
        setPreview(null)
        setBooks([])
        onCreated()
      } else setPreview(await api.post<Preview>('/api/reading-plans/generate', body()))
    } catch (e) {
      const err = e as ApiError
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const reading = shelf.data?.items.filter((e) => e.status === 'reading' || e.status === 'want_to_read') ?? []

  return (
    <section className="card p-5 sm:p-6" aria-labelledby="new-plan">
      <h2 id="new-plan" className="text-xl font-semibold">New plan</h2>
      <div className="mt-4 grid gap-6 lg:grid-cols-2">
        <div className="space-y-4">
          <div>
            <p className="label">Books</p>
            <ul className="space-y-2">
              {books.map((b) => (
                <li key={b.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-white px-3 py-2 text-sm">
                  <span className="flex-1 font-medium">{b.title}</span>
                  {b.page_count ? <span className="text-muted">{b.page_count} pages</span> : (
                    <label className="flex items-center gap-1 text-xs text-gold-dark">Pages in your copy:
                      <input type="number" min={1} className="input w-20 py-1" value={overrides[b.id] ?? ''} onChange={(e) => setOverrides({ ...overrides, [b.id]: e.target.value })} />
                    </label>
                  )}
                  <button aria-label={`Remove ${b.title}`} onClick={() => setBooks(books.filter((x) => x.id !== b.id))}><X className="h-4 w-4" /></button>
                </li>
              ))}
            </ul>
            {reading.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                <span className="text-xs text-muted">From your shelf:</span>
                {reading.slice(0, 6).map((e) => <button key={e.id} className="chip hover:border-ink-soft" onClick={() => add(e.book)}><Plus className="h-3 w-3" aria-hidden />{e.book.title}</button>)}
              </div>
            )}
            <label htmlFor="plan-search" className="sr-only">Search books to add</label>
            <input id="plan-search" className="input mt-2" placeholder="Search to add a book" value={q} onChange={(e) => setQ(e.target.value)} />
            {found.data && dq.length > 1 && (
              <ul className="mt-1 divide-y divide-line rounded-lg border border-line bg-white">
                {found.data.items.map((b) => <li key={b.id}><button className="w-full px-3 py-2 text-left text-sm hover:bg-parchment" onClick={() => add(b)}>{b.title} <span className="text-muted">· {b.page_count ? `${b.page_count} pages` : 'pages unknown'}</span></button></li>)}
              </ul>
            )}
          </div>
          <fieldset>
            <legend className="label">Reading days</legend>
            <div className="flex flex-wrap gap-1.5">
              {DAYS.map(([n, l]) => (
                <button key={n} type="button" aria-pressed={days.includes(n)} onClick={() => setDays(days.includes(n) ? days.filter((d) => d !== n) : [...days, n].sort())}
                  className={`chip ${days.includes(n) ? 'border-forest bg-forest-soft text-forest-dark' : ''}`}>{l}</button>
              ))}
            </div>
          </fieldset>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div><label className="label" htmlFor="p-min">Minutes per day</label><input id="p-min" type="number" min={5} max={600} className="input" value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} /></div>
          <div><label className="label" htmlFor="p-ppm">Pages per minute</label><input id="p-ppm" type="number" step={0.1} min={0.1} max={5} className="input" value={ppm} onChange={(e) => setPpm(Number(e.target.value))} />
            <p className="mt-1 text-xs text-muted">Not sure? 0.6–1.0 is common for non-fiction.</p></div>
          <div><label className="label" htmlFor="p-start">Start date</label><input id="p-start" type="date" className="input" value={start} onChange={(e) => setStart(e.target.value)} /></div>
          <div><label className="label" htmlFor="p-target">Finish by (optional)</label><input id="p-target" type="date" className="input" value={target} onChange={(e) => setTarget(e.target.value)} /></div>
          <label className="col-span-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={fit} onChange={(e) => setFit(e.target.checked)} disabled={!target} />Adjust daily pages to hit the finish date</label>
        </div>
      </div>
      {error && <div className="mt-4"><Notice tone="warn">{error}</Notice></div>}
      <div className="mt-5 flex flex-wrap gap-2">
        <button className="btn-outline" onClick={() => generate(false)} disabled={!books.length || !days.length || busy}>Preview schedule</button>
        <button className="btn-primary" onClick={() => generate(true)} disabled={!books.length || !days.length || busy}>Save plan</button>
      </div>
      {preview && (
        <div className="mt-6 border-t border-line pt-5">
          <div className="flex flex-wrap gap-4 text-sm">
            <span><strong>{preview.pages_per_day}</strong> pages/day (~{preview.minutes_per_day} min)</span>
            <span><strong>{preview.total_pages}</strong> pages total</span>
            <span>Finishes <strong>{date(preview.estimated_finish)}</strong></span>
          </div>
          {preview.feasibility_note && <div className="mt-3"><Notice tone={preview.feasibility_note.startsWith('On track') ? 'success' : 'warn'}>{preview.feasibility_note}</Notice></div>}
          {preview.unscheduled.map((u) => <p key={u.book_id} className="mt-2 text-sm text-gold-dark">{u.title ?? `Book ${u.book_id}`}: {u.reason}</p>)}
          <ol className="mt-4 grid max-h-72 gap-1 overflow-y-auto text-sm sm:grid-cols-2">
            {preview.days.map((d, i) => <li key={i} className="flex justify-between rounded px-2 py-1 odd:bg-parchment/60"><span>{date(d.day, { weekday: 'short', day: 'numeric', month: 'short' })}</span><span className="text-ink-soft">{d.title}: p. {d.start_page}–{d.end_page}</span></li>)}
          </ol>
        </div>
      )}
    </section>
  )
}

function PlanCard({ plan, onChange }: { plan: ReadingPlan; onChange: () => void }) {
  const toast = useToast()
  const [showAll, setShowAll] = useState(false)
  const [minutes, setMinutes] = useState(plan.minutes_per_day)
  const today = new Date().toISOString().slice(0, 10)
  const upcoming = plan.items.filter((i) => !i.completed || i.day >= today)
  const items = showAll ? plan.items : upcoming.slice(0, 7)
  const pr = plan.progress

  async function toggle(itemId: number, completed: boolean) {
    await api.patch(`/api/reading-plans/${plan.id}/items/${itemId}`, { completed })
    onChange()
  }
  async function reschedule() {
    try {
      await api.post(`/api/reading-plans/${plan.id}/reschedule`, { minutes_per_day: minutes })
      toast.success('Remaining schedule rebuilt from where you are.')
      onChange()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }
  async function remove() {
    if (!confirm('Delete this plan?')) return
    await api.del(`/api/reading-plans/${plan.id}`)
    onChange()
  }

  return (
    <article className="card p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold">{plan.title}</h3>
          <p className="text-sm text-muted">{plan.minutes_per_day} min/day at {plan.pages_per_minute} pages/min · {plan.reading_days.length} days a week · started {date(plan.start_date)}{plan.target_date ? ` · target ${date(plan.target_date)}` : ''}</p>
        </div>
        <div className="flex gap-2">
          <Badge tone={pr.status === 'behind' ? 'rust' : pr.status === 'ahead' ? 'forest' : 'sky'}>{pr.status === 'on_track' ? 'On track' : `${Math.abs(pr.difference)} pages ${pr.status}`}</Badge>
          {plan.status === 'completed' && <Badge tone="forest">Completed</Badge>}
        </div>
      </div>
      <div className="mt-4 h-2 overflow-hidden rounded-full bg-parchment" role="progressbar" aria-valuenow={pr.percent_complete ?? 0} aria-valuemin={0} aria-valuemax={100} aria-label="Plan progress">
        <div className="h-full bg-forest" style={{ width: `${pr.percent_complete ?? 0}%` }} />
      </div>
      <p className="mt-1 text-xs text-muted">{pr.actual_pages} of {pr.planned_total} pages · planned by today: {pr.planned_pages_to_date} · scheduled finish {date(pr.scheduled_finish)}</p>
      {plan.feasibility_note && <p className="mt-2 text-sm text-ink-soft">{plan.feasibility_note}</p>}
      <ul className="mt-4 divide-y divide-line">
        {items.map((it) => (
          <li key={it.id} className="flex items-center gap-3 py-2 text-sm">
            <button onClick={() => toggle(it.id, !it.completed)} aria-label={`${it.completed ? 'Unmark' : 'Mark'} ${date(it.day)} as done`} aria-pressed={it.completed}>
              {it.completed ? <CheckCircle2 className="h-5 w-5 text-forest" /> : <Circle className="h-5 w-5 text-line" />}
            </button>
            <span className={`w-28 ${it.day < today && !it.completed ? 'text-rust' : ''}`}>{date(it.day, { weekday: 'short', day: 'numeric', month: 'short' })}</span>
            <span className="flex-1 text-ink-soft">{it.title}: pages {it.start_page}–{it.end_page}</span>
          </li>
        ))}
      </ul>
      {plan.items.length > 7 && <button className="link mt-2 text-sm" onClick={() => setShowAll((s) => !s)}>{showAll ? 'Show upcoming only' : `Show all ${plan.items.length} days`}</button>}
      <div className="mt-4 flex flex-wrap items-end gap-3 border-t border-line pt-4">
        <div><label className="label" htmlFor={`m-${plan.id}`}>Minutes/day</label><input id={`m-${plan.id}`} type="number" min={5} className="input w-24" value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} /></div>
        <button className="btn-outline" onClick={reschedule}>Reschedule from today</button>
        <a href={`/api/reading-plans/${plan.id}/calendar.ics`} className="btn-ghost"><Download className="h-4 w-4" aria-hidden />Add to calendar (.ics)</a>
        <button className="btn-ghost ml-auto text-rust" onClick={remove}><Trash2 className="h-4 w-4" aria-hidden />Delete</button>
      </div>
    </article>
  )
}
