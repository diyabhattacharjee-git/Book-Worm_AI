import { useState } from 'react'
import { Link } from 'react-router'
import { ConditionBadge, StatusBadge } from '../components/marketplace'
import { Badge, EmptyState, ErrorState, Notice, PageHeader, Spinner, Tabs } from '../components/ui'
import { useToast } from '../contexts/ToastContext'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import type { Listing } from '../types'
import { money, relativeTime } from '../utils/format'

interface Reports {
  listing_reports: { id: number; listing_id: number; listing_title: string; listing_status: string; reason: string; details: string | null; status: string; created_at: string }[]
  review_reports: { id: number; review_id: number; book_id: number; review_excerpt: string; review_status: string; reason: string; details: string | null; status: string; created_at: string }[]
}
type AdminListing = Listing & { quality: { score: number; level: string; flags: string[] }; open_reports: number }
type Tab = 'reports' | 'suspicious' | 'reviews' | 'audit'

export default function Moderation() {
  const [tab, setTab] = useState<Tab>('reports')
  return (
    <div>
      <PageHeader eyebrow="Administration" title="Moderation" actions={<Link to="/admin" className="btn-outline">Back to dashboard</Link>}>
        Review reports, check listings with limited information and moderate reviews. Every action is recorded in the audit log.
      </PageHeader>
      <Tabs label="Moderation sections" value={tab} onChange={setTab} tabs={[{ value: 'reports', label: 'Reported content' }, { value: 'suspicious', label: 'Listings to review' }, { value: 'reviews', label: 'Reviews' }, { value: 'audit', label: 'Audit log' }]} />
      <div className="mt-6">
        {tab === 'reports' && <ReportQueue />}
        {tab === 'suspicious' && <SuspiciousListings />}
        {tab === 'reviews' && <ReviewModeration />}
        {tab === 'audit' && <AuditLog />}
      </div>
    </div>
  )
}

function ReportQueue() {
  const toast = useToast()
  const [status, setStatus] = useState<'open' | 'resolved' | 'dismissed'>('open')
  const r = useApi(() => api.get<Reports>('/api/admin/reports', { status }), [status])
  async function call(fn: () => Promise<unknown>, msg: string) {
    try { await fn(); toast.success(msg); r.reload() } catch (e) { toast.error((e as Error).message) }
  }
  return (
    <div className="space-y-8">
      <select aria-label="Report status" className="input w-auto" value={status} onChange={(e) => setStatus(e.target.value as typeof status)}><option value="open">Open</option><option value="resolved">Resolved</option><option value="dismissed">Dismissed</option></select>
      {r.loading ? <Spinner /> : r.error ? <ErrorState error={r.error} onRetry={r.reload} /> : (
        <>
          <section>
            <h2 className="mb-3 text-lg font-semibold">Listing reports ({r.data!.listing_reports.length})</h2>
            {r.data!.listing_reports.length === 0 ? <p className="text-sm text-muted">Nothing here.</p> : (
              <ul className="space-y-3">{r.data!.listing_reports.map((rep) => (
                <li key={rep.id} className="card p-4 text-sm">
                  <div className="flex flex-wrap items-center gap-2"><Link to={`/marketplace/listings/${rep.listing_id}`} className="font-semibold hover:text-forest">{rep.listing_title}</Link><StatusBadge status={rep.listing_status} /><Badge tone="rust">{rep.reason}</Badge><span className="text-xs text-muted">{relativeTime(rep.created_at)}</span></div>
                  {rep.details && <p className="mt-1 text-ink-soft">“{rep.details}”</p>}
                  {status === 'open' && <div className="mt-3 flex flex-wrap gap-2">
                    <button className="btn-danger btn-sm" onClick={() => call(() => api.patch(`/api/admin/listings/${rep.listing_id}`, { status: 'removed', note: `Removed after report: ${rep.reason}` }), 'Listing removed.')}>Remove listing</button>
                    <button className="btn-outline btn-sm" onClick={() => call(() => api.patch(`/api/admin/listings/${rep.listing_id}`, { status: 'inactive', note: 'Hidden pending seller changes' }), 'Listing deactivated.')}>Deactivate</button>
                    <button className="btn-ghost btn-sm" onClick={() => call(() => api.patch(`/api/admin/reports/listing/${rep.id}`, { status: 'dismissed' }), 'Report dismissed.')}>Dismiss report</button>
                  </div>}
                </li>
              ))}</ul>
            )}
          </section>
          <section>
            <h2 className="mb-3 text-lg font-semibold">Review reports ({r.data!.review_reports.length})</h2>
            {r.data!.review_reports.length === 0 ? <p className="text-sm text-muted">Nothing here.</p> : (
              <ul className="space-y-3">{r.data!.review_reports.map((rep) => (
                <li key={rep.id} className="card p-4 text-sm">
                  <div className="flex flex-wrap items-center gap-2"><Link to={`/books/${rep.book_id}`} className="font-semibold hover:text-forest">Review #{rep.review_id}</Link><Badge tone={rep.review_status === 'hidden' ? 'neutral' : 'forest'}>{rep.review_status}</Badge><Badge tone="rust">{rep.reason}</Badge><span className="text-xs text-muted">{relativeTime(rep.created_at)}</span></div>
                  <p className="mt-1 text-ink-soft">“{rep.review_excerpt}”</p>
                  {rep.details && <p className="text-xs text-muted">Reporter: {rep.details}</p>}
                  {status === 'open' && <div className="mt-3 flex gap-2">
                    <button className="btn-danger btn-sm" onClick={() => call(() => api.patch(`/api/admin/reviews/${rep.review_id}`, { status: 'hidden' }), 'Review hidden.')}>Hide review</button>
                    <button className="btn-ghost btn-sm" onClick={() => call(() => api.patch(`/api/admin/reports/review/${rep.id}`, { status: 'dismissed' }), 'Report dismissed.')}>Dismiss report</button>
                  </div>}
                </li>
              ))}</ul>
            )}
          </section>
        </>
      )}
    </div>
  )
}

function SuspiciousListings() {
  const toast = useToast()
  const l = useApi(() => api.get<{ items: AdminListing[]; total: number; note: string }>('/api/admin/listings', { suspicious: true, status: 'active' }), [])
  async function moderate(id: number, status: string) {
    const note = status === 'active' ? null : prompt('Note for the seller (optional):') ?? null
    try { await api.patch(`/api/admin/listings/${id}`, { status, note }); toast.success('Listing updated.'); l.reload() } catch (e) { toast.error((e as Error).message) }
  }
  if (l.loading) return <Spinner />
  if (l.error) return <ErrorState error={l.error} onRetry={l.reload} />
  return (
    <div className="space-y-4">
      <Notice tone="info">{l.data!.note}</Notice>
      {l.data!.items.length === 0 ? <EmptyState title="Nothing to review">No active listings with limited information or open reports.</EmptyState> : l.data!.items.map((x) => (
        <div key={x.id} className="card flex flex-wrap items-start gap-4 p-4 text-sm">
          <div className="min-w-0 flex-1">
            <Link to={`/marketplace/listings/${x.id}`} className="font-semibold hover:text-forest">{x.title}</Link>
            <div className="mt-1 flex flex-wrap items-center gap-2"><ConditionBadge condition={x.condition} /><span>{money(x.price_amount, x.currency)}</span><span className="text-muted">by {x.seller.display_name}</span>{x.open_reports > 0 && <Badge tone="rust">{x.open_reports} report(s)</Badge>}<Badge tone="gold">quality {x.quality.score}/100</Badge></div>
            <ul className="mt-2 list-disc pl-5 text-xs text-muted">{x.quality.flags.map((f) => <li key={f}>{f}</li>)}</ul>
          </div>
          <div className="flex gap-2"><button className="btn-outline btn-sm" onClick={() => moderate(x.id, 'inactive')}>Deactivate</button><button className="btn-danger btn-sm" onClick={() => moderate(x.id, 'removed')}>Remove</button></div>
        </div>
      ))}
    </div>
  )
}

function ReviewModeration() {
  const toast = useToast()
  const [status, setStatus] = useState<'visible' | 'hidden'>('visible')
  const r = useApi(() => api.get<{ id: number; book_id: number; user: string; rating: number; body: string; status: string; helpful_count: number; updated_at: string }[]>('/api/admin/reviews', { status }), [status])
  async function set(id: number, s: 'visible' | 'hidden') {
    try { await api.patch(`/api/admin/reviews/${id}`, { status: s }); toast.success(`Review ${s}.`); r.reload() } catch (e) { toast.error((e as Error).message) }
  }
  return (
    <div className="space-y-3">
      <select aria-label="Review status" className="input w-auto" value={status} onChange={(e) => setStatus(e.target.value as typeof status)}><option value="visible">Visible</option><option value="hidden">Hidden</option></select>
      {r.loading ? <Spinner /> : r.data?.length === 0 ? <p className="text-sm text-muted">No reviews.</p> : r.data?.map((rv) => (
        <div key={rv.id} className="card p-4 text-sm">
          <p><strong>{rv.user}</strong> · {rv.rating}★ · <Link to={`/books/${rv.book_id}`} className="link">book #{rv.book_id}</Link> · {relativeTime(rv.updated_at)}</p>
          <p className="mt-1 text-ink-soft line-clamp-3">{rv.body}</p>
          <button className="btn-outline btn-sm mt-2" onClick={() => set(rv.id, rv.status === 'visible' ? 'hidden' : 'visible')}>{rv.status === 'visible' ? 'Hide' : 'Restore'}</button>
        </div>
      ))}
    </div>
  )
}

function AuditLog() {
  const a = useApi(() => api.get<{ id: number; actor_id: number | null; action: string; target_type: string; target_id: number | null; details: Record<string, unknown>; created_at: string }[]>('/api/admin/audit-log'), [])
  if (a.loading) return <Spinner />
  return a.data?.length ? (
    <ul className="divide-y divide-line rounded-xl border border-line bg-paper text-sm">
      {a.data.map((e) => <li key={e.id} className="flex flex-wrap gap-3 p-3"><span className="text-xs text-muted">{relativeTime(e.created_at)}</span><span className="font-medium">{e.action}</span><span>{e.target_type} #{e.target_id}</span><span className="text-xs text-muted">admin #{e.actor_id ?? '—'} {Object.keys(e.details).length ? JSON.stringify(e.details) : ''}</span></li>)}
    </ul>
  ) : <p className="text-sm text-muted">No administrative actions yet.</p>
}
