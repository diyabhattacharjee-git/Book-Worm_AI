import { CalendarDays, CheckCircle2, Circle, Download, Plus, Trash2, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { BookSearch } from '../components/BookSearch'
import { Badge, EmptyState, ErrorState, ListSkeleton, Notice, PageHeader } from '../components/ui'
import { useAuth } from '../contexts/AuthContext'
import { useConfirm } from '../contexts/ConfirmContext'
import { useToast } from '../contexts/ToastContext'
import { TTL, queryKey, useGet } from '../hooks/useApi'
import { ApiError, api } from '../services/api'
import { invalidate, optimistic, setQueryData } from '../services/queryCache'
import type { BookSummary, ReadingPlan, ShelfEntry } from '../types'
import { date } from '../utils/format'

const PLANS = '/api/reading-plans'
const MAX_PLAN_BOOKS = 10
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
  const { user } = useAuth()
  const plans = useGet<ReadingPlan[]>(PLANS, undefined, { userId: user?.id, ttl: TTL.medium })
  const plansKey = queryKey(PLANS, undefined, user?.id)
  return (
    <div>
      <PageHeader eyebrow="Reading plans" title="Plan your reading">
        Schedules are built from real page counts and your own reading speed. BookWorm doesn’t send reminders — export the plan to your calendar instead.
      </PageHeader>
      <PlanBuilder plansKey={plansKey} />
      <section className="mt-12" aria-labelledby="my-plans">
        <h2 id="my-plans" className="section-title">Your plans</h2>
        <div className="mt-5 space-y-6">
          {plans.loading ? <ListSkeleton rows={2} /> : plans.error || !plans.data ? <ErrorState error={plans.error} onRetry={plans.reload} />
            : plans.data.length === 0 ? <EmptyState icon={<CalendarDays className="h-6 w-6" />} title="No plans yet">Build one above to get a day-by-day schedule.</EmptyState>
              : plans.data.map((p) => <PlanCard key={p.id} plan={p} plansKey={plansKey} />)}
        </div>
      </section>
    </div>
  )
}

function PlanBuilder({ plansKey }: { plansKey: string }) {
  const { user } = useAuth()
  const toast = useToast()
  const [params] = useSearchParams()
  const shelf = useGet<{ items: ShelfEntry[] }>('/api/bookshelf', undefined, { userId: user?.id, ttl: TTL.medium })
  const [books, setBooks] = useState<BookSummary[]>([])
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
      api.get<BookSummary>(`/api/books/${id}`, { track: false }).then((b) => setBooks((bs) => (bs.some((x) => x.id === b.id) ? bs : [...bs, b]))).catch(() => undefined)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params])

  function add(b: BookSummary) {
    if (!books.some((x) => x.id === b.id) && books.length < MAX_PLAN_BOOKS) setBooks([...books, b])
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

  function planProblem(): string | null {
    if (!Number.isFinite(minutes) || minutes < 5 || minutes > 600) return 'Minutes per day must be between 5 and 600.'
    if (!Number.isFinite(ppm) || ppm < 0.1 || ppm > 5) return 'Pages per minute must be between 0.1 and 5.'
    if (start && target && target < start) return 'The finish date must be after the start date.'
    return null
  }

  async function generate(save: boolean) {
    if (busy) return
    const problem = planProblem()
    if (problem) return setError(problem)
    setBusy(true)
    setError(null)
    try {
      if (save) {
        const plan = await api.post<ReadingPlan>(PLANS, body())
        setQueryData<ReadingPlan[]>(plansKey, (prev) => [plan, ...(prev ?? [])])
        invalidate('/api/bookshelf')
        toast.success('Plan saved.')
        setPreview(null)
        setBooks([])
      } else setPreview(await api.post<Preview>(`${PLANS}/generate`, body()))
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
                  <span className="user-text min-w-0 flex-1 font-medium">{b.title}</span>
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
            <div className="mt-2"><BookSearch id="plan-search" placeholder="Search to add a book" onPick={add} exclude={books.map((b) => b.id)} describe={(b) => (b.page_count ? `${b.page_count} pages` : 'pages unknown')} /></div>
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

function PlanCard({ plan, plansKey }: { plan: ReadingPlan; plansKey: string }) {
  const toast = useToast()
  const confirm = useConfirm()
  const [working, setWorking] = useState(false)
  const [showAll, setShowAll] = useState(false)
  const [minutes, setMinutes] = useState(plan.minutes_per_day)
  const today = new Date().toISOString().slice(0, 10)
  const upcoming = plan.items.filter((i) => !i.completed || i.day >= today)
  const items = showAll ? plan.items : upcoming.slice(0, 7)
  const pr = plan.progress

  const replace = (updated: ReadingPlan) => setQueryData<ReadingPlan[]>(plansKey, (prev) => (prev ?? []).map((p) => (p.id === updated.id ? updated : p)))

  async function toggle(itemId: number, completed: boolean) {
    try {
      const updated = await optimistic<ReadingPlan[], ReadingPlan>(plansKey,
        (d) => d.map((p) => (p.id === plan.id ? { ...p, items: p.items.map((i) => (i.id === itemId ? { ...i, completed } : i)) } : p)),
        () => api.patch<ReadingPlan>(`${PLANS}/${plan.id}/items/${itemId}`, { completed }))
      replace(updated)
      invalidate('/api/bookshelf')
    } catch (e) {
      toast.error((e as Error).message)
    }
  }
  async function reschedule() {
    if (working) return
    if (!Number.isFinite(minutes) || minutes < 5 || minutes > 600) return toast.error('Minutes per day must be between 5 and 600.')
    setWorking(true)
    try {
      replace(await api.post<ReadingPlan>(`${PLANS}/${plan.id}/reschedule`, { minutes_per_day: minutes }))
      toast.success('Remaining schedule rebuilt from where you are.')
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setWorking(false)
    }
  }
  async function remove() {
    if (!await confirm({ title: 'Delete this plan?', message: `“${plan.title}” will be removed.`, confirmLabel: 'Delete', danger: true })) return
    try {
      await optimistic<ReadingPlan[], void>(plansKey, (d) => d.filter((p) => p.id !== plan.id), () => api.del(`${PLANS}/${plan.id}`))
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  return (
    <article className="card p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="user-text text-lg font-semibold">{plan.title}</h3>
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
            <span className={`w-24 shrink-0 sm:w-28 ${it.day < today && !it.completed ? 'text-rust' : ''}`}>{date(it.day, { weekday: 'short', day: 'numeric', month: 'short' })}</span>
            <span className="user-text min-w-0 flex-1 text-ink-soft">{it.title}: pages {it.start_page}–{it.end_page}</span>
          </li>
        ))}
      </ul>
      {plan.items.length > 7 && <button className="link mt-2 text-sm" onClick={() => setShowAll((s) => !s)}>{showAll ? 'Show upcoming only' : `Show all ${plan.items.length} days`}</button>}
      <div className="mt-4 flex flex-wrap items-end gap-3 border-t border-line pt-4">
        <div><label className="label" htmlFor={`m-${plan.id}`}>Minutes/day</label><input id={`m-${plan.id}`} type="number" min={5} className="input w-24" value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} /></div>
        <button className="btn-outline" onClick={reschedule} disabled={working}>{working ? 'Rebuilding…' : 'Reschedule from today'}</button>
        <a href={`/api/reading-plans/${plan.id}/calendar.ics`} className="btn-ghost"><Download className="h-4 w-4" aria-hidden />Add to calendar (.ics)</a>
        <button className="btn-ghost ml-auto text-rust" onClick={remove}><Trash2 className="h-4 w-4" aria-hidden />Delete</button>
      </div>
    </article>
  )
}
