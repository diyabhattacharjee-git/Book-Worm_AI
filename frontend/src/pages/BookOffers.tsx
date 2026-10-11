import { ExternalLink, Info, Tag } from 'lucide-react'
import { Link, useParams } from 'react-router'
import { BookCover } from '../components/books'
import { EmptyState, ErrorState, Notice, PageHeader, Spinner } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import type { BookSummary } from '../types'
import { authorsText, money, relativeTime } from '../utils/format'

interface Offers {
  book_id: number
  offers: { source: string; title: string; format: string | null; price: number | null; currency: string | null; availability: string | null; url: string | null; retrieved_at: string; note: string | null }[]
  used_summary: { active_listings: number; lowest_price: number | null; currency: string | null }
  metadata_links: { label: string; url: string }[]
  provider_notes: string[]
}

export default function BookOffers() {
  const { id } = useParams()
  const book = useApi(() => api.get<BookSummary>(`/api/books/${id}`), [id])
  const offers = useApi(() => api.get<Offers>(`/api/books/${id}/offers`), [id])
  const b = book.data
  return (
    <div>
      <PageHeader eyebrow="New copies" title={b ? `Buying “${b.title}” new` : 'New-copy offers'}>
        Only prices actually returned by a configured source are shown, with the time they were retrieved. Metadata services are not price-comparison sites.
      </PageHeader>
      {b && (
        <div className="mb-8 flex items-center gap-4">
          <div className="w-16"><BookCover title={b.title} authors={b.authors} url={b.cover_url} size="sm" /></div>
          <div><Link to={`/books/${b.id}`} className="font-serif text-lg font-semibold hover:text-forest">{b.title}</Link><p className="text-sm text-muted">{authorsText(b.authors)}</p></div>
        </div>
      )}
      {offers.loading ? <Spinner label="Checking sources" /> : offers.error ? <ErrorState error={offers.error} onRetry={offers.reload} /> : (
        <div className="grid gap-8 lg:grid-cols-[1fr_320px]">
          <section>
            {offers.data!.offers.length === 0 ? (
              <EmptyState icon={<Info className="h-6 w-6" />} title="No priced offers from configured sources">
                None of the configured sources returned a current price for this book. Use the reference links to check availability yourself.
              </EmptyState>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-line bg-paper">
                <table className="w-full min-w-[560px] text-left text-sm">
                  <thead className="border-b border-line text-xs uppercase tracking-wide text-muted"><tr><th className="p-3">Source</th><th>Format</th><th>Price</th><th>Availability</th><th>Retrieved</th><th /></tr></thead>
                  <tbody className="divide-y divide-line">
                    {offers.data!.offers.map((o, i) => (
                      <tr key={i}>
                        <td className="p-3"><p className="font-medium">{o.source}</p><p className="text-xs text-muted line-clamp-1">{o.title}</p>{o.note && <p className="text-xs text-gold-dark">{o.note}</p>}</td>
                        <td>{o.format ?? 'Not stated'}</td>
                        <td className="font-semibold">{money(o.price, o.currency)}</td>
                        <td className="text-ink-soft">{o.availability ?? 'Not stated'}</td>
                        <td className="text-muted">{relativeTime(o.retrieved_at)}</td>
                        <td className="pr-3">{o.url && <a href={o.url} target="_blank" rel="noopener noreferrer nofollow" className="btn-outline btn-sm">Open <ExternalLink className="h-3 w-3" aria-hidden /></a>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="mt-5 space-y-2">{offers.data!.provider_notes.map((n) => <Notice key={n} tone="info">{n}</Notice>)}</div>
          </section>
          <aside className="space-y-4">
            <div className="card p-5">
              <Tag className="h-5 w-5 text-forest" aria-hidden />
              <p className="mt-2 font-semibold">Second-hand on BookWorm</p>
              <p className="text-sm text-muted">{offers.data!.used_summary.active_listings ? `${offers.data!.used_summary.active_listings} active listing(s), from ${money(offers.data!.used_summary.lowest_price, offers.data!.used_summary.currency)}` : 'No active community listings.'}</p>
              <Link to={`/marketplace/find?title=${encodeURIComponent(b?.title ?? '')}`} className="btn-forest btn-sm mt-3">Find & price-check used copies</Link>
            </div>
            <div className="card p-5">
              <p className="font-semibold">Reference links</p>
              <ul className="mt-2 space-y-1 text-sm">
                {offers.data!.metadata_links.map((l) => <li key={l.url}><a href={l.url} target="_blank" rel="noopener noreferrer" className="link inline-flex items-center gap-1">{l.label}<ExternalLink className="h-3 w-3" aria-hidden /></a></li>)}
              </ul>
            </div>
          </aside>
        </div>
      )}
    </div>
  )
}
