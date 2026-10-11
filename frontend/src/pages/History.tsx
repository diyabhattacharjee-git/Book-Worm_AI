import { Target, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { BookCard, BookGrid, BookRow } from '../components/books'
import { EmptyState, ErrorState, PageHeader, Spinner } from '../components/ui'
import { useToast } from '../contexts/ToastContext'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import type { BookSummary } from '../types'
import { date } from '../utils/format'

interface Goal { id: number; year: number; month: number | null; target_books: number; completed_books: number; percent: number }
interface HistoryData {
  finished: { entry_id: number; book: BookSummary; finished_on: string | null; started_on: string | null }[]
  by_year: Record<string, number>
  pages_read_known: number
  books_with_unknown_pages: number
  recently_viewed: BookSummary[]
}

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

export default function History() {
  const toast = useToast()
  const goals = useApi(() => api.get<Goal[]>('/api/reading-goals'), [])
  const hist = useApi(() => api.get<HistoryData>('/api/reading-history'), [])
  const now = new Date()
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState<string>('')
  const [target, setTarget] = useState(12)

  async function saveGoal(e: FormEvent) {
    e.preventDefault()
    try {
      await api.post('/api/reading-goals', { year, month: month ? Number(month) : null, target_books: target })
      toast.success('Goal saved.')
      goals.reload()
    } catch (err) {
      toast.error((err as Error).message)
    }
  }
  async function deleteGoal(id: number) {
    await api.del(`/api/reading-goals/${id}`)
    goals.reload()
  }

  return (
    <div className="space-y-12">
      <PageHeader eyebrow="Reading life" title="History & goals" actions={<Link to="/shelf" className="btn-outline">Bookshelf</Link>}>
        Goals count books you mark as Read, by their finish date.
      </PageHeader>

      <section aria-labelledby="goals" className="grid gap-6 lg:grid-cols-[1fr_340px]">
        <div>
          <h2 id="goals" className="section-title">Goals</h2>
          <div className="mt-4 space-y-3">
            {goals.loading ? <Spinner /> : goals.data?.length === 0 ? <EmptyState icon={<Target className="h-6 w-6" />} title="No goals yet">Set a yearly or monthly target to track your progress.</EmptyState>
              : goals.data?.map((g) => (
                <div key={g.id} className="card p-4">
                  <div className="flex items-center justify-between">
                    <p className="font-semibold">{g.month ? `${MONTHS[g.month - 1]} ${g.year}` : `${g.year} reading challenge`}</p>
                    <button className="btn-ghost btn-sm" onClick={() => deleteGoal(g.id)} aria-label="Delete goal"><Trash2 className="h-4 w-4" /></button>
                  </div>
                  <div className="mt-3 h-3 overflow-hidden rounded-full bg-parchment" role="progressbar" aria-valuenow={g.percent} aria-valuemin={0} aria-valuemax={100} aria-label="Goal progress">
                    <div className="h-full bg-gold" style={{ width: `${g.percent}%` }} />
                  </div>
                  <p className="mt-1 text-sm text-muted">{g.completed_books} of {g.target_books} books · {g.percent}%{g.completed_books >= g.target_books ? ' · Goal reached!' : ''}</p>
                </div>
              ))}
          </div>
        </div>
        <form onSubmit={saveGoal} className="card h-fit space-y-3 p-5">
          <h3 className="font-semibold">Set a goal</h3>
          <div className="grid grid-cols-2 gap-3">
            <div><label className="label" htmlFor="g-year">Year</label><input id="g-year" type="number" className="input" value={year} onChange={(e) => setYear(Number(e.target.value))} /></div>
            <div><label className="label" htmlFor="g-month">Month</label>
              <select id="g-month" className="input" value={month} onChange={(e) => setMonth(e.target.value)}><option value="">Whole year</option>{MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}</select></div>
          </div>
          <div><label className="label" htmlFor="g-target">Books</label><input id="g-target" type="number" min={1} max={1000} className="input" value={target} onChange={(e) => setTarget(Number(e.target.value))} /></div>
          <button className="btn-primary w-full">Save goal</button>
          <p className="text-xs text-muted">Saving a goal for the same period updates it.</p>
        </form>
      </section>

      <section aria-labelledby="finished">
        <h2 id="finished" className="section-title">Finished books</h2>
        {hist.loading ? <Spinner /> : hist.error ? <ErrorState error={hist.error} onRetry={hist.reload} /> : (
          <>
            <div className="mt-3 flex flex-wrap gap-4 text-sm text-muted">
              {Object.entries(hist.data!.by_year).map(([y, n]) => <span key={y} className="chip">{y}: {n} book{n === 1 ? '' : 's'}</span>)}
              <span>{hist.data!.pages_read_known.toLocaleString()} pages read{hist.data!.books_with_unknown_pages ? ` (+ ${hist.data!.books_with_unknown_pages} book(s) with unknown page count)` : ''}</span>
            </div>
            {hist.data!.finished.length === 0 ? <div className="mt-4"><EmptyState title="No finished books yet">Mark books as Read on your shelf to build your history.</EmptyState></div> : (
              <ul className="mt-5 space-y-3">
                {hist.data!.finished.map((f) => (
                  <li key={f.entry_id} className="card p-4"><BookRow book={f.book} right={<span className="text-xs text-muted">Finished {date(f.finished_on)}</span>} /></li>
                ))}
              </ul>
            )}
          </>
        )}
      </section>

      {hist.data && hist.data.recently_viewed.length > 0 && (
        <section aria-labelledby="viewed">
          <h2 id="viewed" className="section-title">Recently viewed</h2>
          <div className="mt-5"><BookGrid>{hist.data.recently_viewed.slice(0, 10).map((b) => <BookCard key={b.id} book={b} />)}</BookGrid></div>
        </section>
      )}
    </div>
  )
}
