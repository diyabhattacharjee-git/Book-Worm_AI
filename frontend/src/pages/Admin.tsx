import { BarChart3, BookOpen, Flag, Store, Users } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { Badge, EmptyState, ErrorState, Notice, PageHeader, Spinner, Tabs } from '../components/ui'
import { useToast } from '../contexts/ToastContext'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { date, money } from '../utils/format'

interface Overview {
  users: Record<string, number>
  catalogue: Record<string, number>
  marketplace: { listings_by_status: Record<string, number>; sample_listings: number; inquiries: number; new_listings_7d: number; real_active_avg_price: { currency: string; count: number; average: number }[] }
  reviews: Record<string, number>
  reports: Record<string, number>
  recommendations: { events_7d: number; by_event: Record<string, number> }
}

interface Metrics {
  usage: { events: Record<string, number>; shown_by_strategy: Record<string, number>; engagement_rate: number | null; engagement_note: string | null }
  model: { content_backend: string; collaborative: { reliable: boolean; users_with_enough_data: number; required_users: number; items_in_matrix: number }; fitted_at: string | null; real_users_with_activity: number }
  runs: { id: number; status: string; k: number; include_demo: boolean; n_users: number; results: Record<string, Record<string, number | string | null | boolean>>; notes: string | null; created_at: string }[]
}

type Tab = 'overview' | 'recs' | 'users' | 'books'

export default function Admin() {
  const [tab, setTab] = useState<Tab>('overview')
  return (
    <div>
      <PageHeader eyebrow="Administration" title="Admin dashboard" actions={<Link to="/admin/moderation" className="btn-primary"><Flag className="h-4 w-4" aria-hidden />Moderation queue</Link>} />
      <Tabs label="Admin sections" value={tab} onChange={setTab} tabs={[{ value: 'overview', label: 'Overview' }, { value: 'recs', label: 'Recommendation performance' }, { value: 'users', label: 'Users' }, { value: 'books', label: 'Catalogue' }]} />
      <div className="mt-6">
        {tab === 'overview' && <OverviewTab />}
        {tab === 'recs' && <RecsTab />}
        {tab === 'users' && <UsersTab />}
        {tab === 'books' && <BooksTab />}
      </div>
    </div>
  )
}

function Stat({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return <div className="card p-4"><p className="text-2xl font-semibold">{value}</p><p className="text-sm text-muted">{label}</p>{sub && <p className="mt-1 text-xs text-muted">{sub}</p>}</div>
}

function OverviewTab() {
  const o = useApi(() => api.get<Overview>('/api/admin/overview'), [])
  if (o.loading) return <Spinner />
  if (o.error) return <ErrorState error={o.error} onRetry={o.reload} />
  const d = o.data!
  return (
    <div className="space-y-8">
      <section><h2 className="mb-3 flex items-center gap-2 text-lg font-semibold"><Users className="h-5 w-5" aria-hidden />Users</h2>
        <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Total" value={d.users.total} />
          <Stat label="Sellers" value={d.users.sellers} /><Stat label="Admins" value={d.users.admins} /><Stat label="New (7 days)" value={d.users.new_last_7_days} />
        </div></section>
      <section><h2 className="mb-3 flex items-center gap-2 text-lg font-semibold"><Store className="h-5 w-5" aria-hidden />Marketplace</h2>
        <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-6">
          {Object.entries(d.marketplace.listings_by_status).map(([k, v]) => <Stat key={k} label={`${k} listings`} value={v} />)}
          <Stat label="Sample listings" value={d.marketplace.sample_listings} /><Stat label="Inquiries" value={d.marketplace.inquiries} /><Stat label="New listings (7d)" value={d.marketplace.new_listings_7d} />
        </div>
        <p className="mt-2 text-sm text-muted">Average active asking price (real listings only): {d.marketplace.real_active_avg_price.length ? d.marketplace.real_active_avg_price.map((p) => `${money(p.average, p.currency)} over ${p.count}`).join(', ') : 'no real listings yet'}.</p></section>
      <section className="grid gap-4 sm:grid-cols-4">
        <Stat label="Books in catalogue" value={d.catalogue.books} />
        <Stat label="Reviews" value={d.reviews.total} sub={`${d.reviews.hidden} hidden`} />
        <Stat label="Open reports" value={d.reports.open_listing_reports + d.reports.open_review_reports} sub={`${d.reports.open_listing_reports} listings · ${d.reports.open_review_reports} reviews`} />
        <Stat label="Recommendation events (7d)" value={d.recommendations.events_7d} sub={Object.entries(d.recommendations.by_event).map(([k, v]) => `${k} ${v}`).join(' · ')} />
      </section>
    </div>
  )
}

const METRIC_LABELS: [string, string][] = [['precision_at_', 'Precision@K'], ['recall_at_', 'Recall@K'], ['ndcg_at_', 'NDCG@K'], ['catalogue_coverage', 'Coverage'], ['intra_list_diversity', 'Diversity'], ['popularity_concentration', 'Popularity concentration'], ['cold_start_precision', 'Cold-start precision']]

function RecsTab() {
  const toast = useToast()
  const m = useApi(() => api.get<Metrics>('/api/recommendations/metrics'), [])
  const [k, setK] = useState(10)
  const [running, setRunning] = useState(false)
  const [last, setLast] = useState<{ status: string; message?: string; methodology: string; requirements: string; data_warning: string | null } | null>(null)

  async function evaluate() {
    setRunning(true)
    try {
      const r = await api.post<NonNullable<typeof last>>('/api/recommendations/evaluate', { k })
      setLast(r)
      m.reload()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setRunning(false)
    }
  }

  if (m.loading) return <Spinner />
  if (m.error) return <ErrorState error={m.error} onRetry={m.reload} />
  const d = m.data!
  return (
    <div className="space-y-8">
      <section className="grid gap-4 sm:grid-cols-4">
        <Stat label="Content model" value={d.model.content_backend} />
        <Stat label="Collaborative filtering" value={d.model.collaborative.reliable ? 'Active' : 'Off'} sub={`${d.model.collaborative.users_with_enough_data}/${d.model.collaborative.required_users} users with enough data`} />
        <Stat label="Real users with activity" value={d.model.real_users_with_activity} />
        <Stat label="Engagement rate" value={d.usage.engagement_rate !== null ? `${(d.usage.engagement_rate * 100).toFixed(1)}%` : '—'} sub={d.usage.engagement_note ?? 'saved + rated + opened / shown'} />
      </section>
      <section className="card p-5">
        <h2 className="flex items-center gap-2 text-lg font-semibold"><BarChart3 className="h-5 w-5" aria-hidden />Offline evaluation</h2>
        <p className="mt-1 text-sm text-muted">Temporal hold-out: the most recent 20% of each eligible user’s liked/finished books are hidden; models trained on the rest must rank them. Compares the hybrid with single-signal baselines.</p>
        <div className="mt-4 flex flex-wrap items-end gap-3">
          <div><label className="label" htmlFor="k">K</label><input id="k" type="number" min={1} max={50} className="input w-20" value={k} onChange={(e) => setK(Number(e.target.value))} /></div>
          <button className="btn-primary" onClick={evaluate} disabled={running}>{running ? 'Evaluating…' : 'Run evaluation'}</button>
        </div>
        {last && (
          <div className="mt-4 space-y-2">
            {last.status === 'insufficient_data' && <Notice tone="warn" title="Not enough evaluation data">{last.message}</Notice>}
            {last.data_warning && <Notice tone="warn">{last.data_warning}</Notice>}
            <details className="text-xs text-muted"><summary className="cursor-pointer">Methodology & assumptions</summary><pre className="mt-2 whitespace-pre-wrap font-sans">{last.methodology}</pre></details>
          </div>
        )}
      </section>
      <section>
        <h2 className="mb-3 text-lg font-semibold">Evaluation runs</h2>
        {d.runs.length === 0 ? <EmptyState title="No evaluation runs yet">Run one above. Until enough readers have rated books you’ll see “Not enough evaluation data”.</EmptyState> : (
          <div className="space-y-4">
            {d.runs.map((r) => (
              <div key={r.id} className="card overflow-x-auto p-4">
                <p className="text-sm"><strong>Run #{r.id}</strong> · {date(r.created_at, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })} · K={r.k} · {r.n_users} users {r.status !== 'ok' && <Badge tone="neutral">{r.status.replace('_', ' ')}</Badge>}</p>
                {r.status === 'ok' && (
                  <table className="mt-3 w-full min-w-[640px] text-left text-sm">
                    <thead className="text-xs uppercase text-muted"><tr><th className="py-1">Configuration</th>{METRIC_LABELS.map(([, l]) => <th key={l}>{l}</th>)}</tr></thead>
                    <tbody className="divide-y divide-line">
                      {Object.entries(r.results).map(([name, res]) => (
                        <tr key={name}>
                          <td className="py-1.5 font-medium">{name.replace('_', ' ')}</td>
                          {res.status !== 'ok' ? <td colSpan={METRIC_LABELS.length} className="text-muted">{String(res.message ?? res.status)}</td>
                            : METRIC_LABELS.map(([key, l]) => {
                              const v = key.endsWith('_at_') ? res[`${key}${r.k}`] : res[key]
                              return <td key={l}>{typeof v === 'number' ? v.toFixed(3) : '—'}</td>
                            })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {r.notes && <p className="mt-2 text-xs text-gold-dark">{r.notes}</p>}
              </div>
            ))}
          </div>
        )}
      </section>
      <section className="text-sm text-muted">
        <p>Recommendations served by dominant signal: {Object.entries(d.usage.shown_by_strategy).map(([k, v]) => `${k} ${v}`).join(' · ') || 'none yet'}.</p>
      </section>
    </div>
  )
}

function UsersTab() {
  const toast = useToast()
  const [q, setQ] = useState('')
  const users = useApi(() => api.get<{ total: number; items: { id: number; email: string; username: string | null; display_name: string; role: string; is_seller: boolean; is_active: boolean; is_demo: boolean; created_at: string; last_login_at: string | null }[] }>('/api/admin/users', { q }), [q])
  async function toggle(id: number, is_active: boolean) {
    try {
      await api.patch(`/api/admin/users/${id}`, { is_active })
      toast.success(is_active ? 'User reactivated.' : 'User suspended and signed out.')
      users.reload()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }
  return (
    <div>
      <label htmlFor="uq" className="sr-only">Search users</label>
      <input id="uq" className="input max-w-sm" placeholder="Search name or email" value={q} onChange={(e) => setQ(e.target.value)} />
      {users.loading ? <Spinner className="mt-4" /> : (
        <div className="mt-4 overflow-x-auto rounded-xl border border-line bg-paper">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="border-b border-line text-xs uppercase text-muted"><tr><th className="p-3">User</th><th>Role</th><th>Joined</th><th>Last login</th><th>Status</th><th /></tr></thead>
            <tbody className="divide-y divide-line">
              {users.data?.items.map((u) => (
                <tr key={u.id}>
                  <td className="p-3"><p className="font-medium">{u.display_name} {u.username && <span className="text-xs text-muted">@{u.username}</span>}</p><p className="text-xs text-muted">{u.email}</p></td>
                  <td>{u.role}{u.is_seller && ' · seller'}</td><td>{date(u.created_at)}</td><td>{date(u.last_login_at)}</td>
                  <td>{u.is_active ? <Badge tone="forest">active</Badge> : <Badge tone="rust">suspended</Badge>}</td>
                  <td className="pr-3">{u.role !== 'admin' && <button className="btn-outline btn-sm" onClick={() => toggle(u.id, !u.is_active)}>{u.is_active ? 'Suspend' : 'Reactivate'}</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function BooksTab() {
  const toast = useToast()
  const [q, setQ] = useState('')
  const books = useApi(() => api.get<{ total: number; items: { id: number; title: string; authors: string[]; page_count: number | null; source: string; has_description: boolean; is_sample: boolean }[] }>('/api/admin/books', { q }), [q])
  async function setPages(id: number) {
    const v = prompt('Page count (from a reliable source):')
    if (!v) return
    try {
      await api.patch(`/api/admin/books/${id}`, { page_count: Number(v) })
      toast.success('Book updated.')
      books.reload()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }
  async function remove(id: number, title: string) {
    if (!confirm(`Delete “${title}” from the catalogue?`)) return
    await api.del(`/api/admin/books/${id}`)
    books.reload()
  }
  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor="bq" className="sr-only">Search catalogue</label>
        <input id="bq" className="input max-w-sm" placeholder="Search title" value={q} onChange={(e) => setQ(e.target.value)} />
        <Link to="/discover" className="link text-sm"><BookOpen className="mr-1 inline h-4 w-4" aria-hidden />Import books by ISBN from Discover</Link>
      </div>
      {books.loading ? <Spinner className="mt-4" /> : (
        <div className="mt-4 overflow-x-auto rounded-xl border border-line bg-paper">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="border-b border-line text-xs uppercase text-muted"><tr><th className="p-3">Book</th><th>Pages</th><th>Description</th><th>Source</th><th /></tr></thead>
            <tbody className="divide-y divide-line">
              {books.data?.items.map((b) => (
                <tr key={b.id}>
                  <td className="p-3"><Link to={`/books/${b.id}`} className="font-medium hover:text-forest">{b.title}</Link><p className="text-xs text-muted">{b.authors.join(', ')}</p></td>
                  <td>{b.page_count ?? <button className="link text-xs" onClick={() => setPages(b.id)}>Add</button>}</td>
                  <td>{b.has_description ? 'Yes' : <span className="text-gold-dark">Missing</span>}</td>
                  <td>{b.source.replace('_', ' ')}</td>
                  <td className="pr-3"><button className="btn-ghost btn-sm text-rust" onClick={() => remove(b.id, b.title)}>Delete</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="p-3 text-xs text-muted">{books.data?.total} books</p>
        </div>
      )}
    </div>
  )
}
