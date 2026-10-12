import { AlertTriangle, CheckCircle2, Circle, ExternalLink, Heart, Image as ImageIcon, Loader2, MapPin, ShieldAlert, Truck, XCircle } from 'lucide-react'
import { Link } from 'react-router'
import type { Deal, Listing, PriceEstimate, PriceVerdict, TraceStep } from '../types'
import { CONDITION_LABELS, money, relativeTime } from '../utils/format'
import { Badge } from './ui'

export function ConditionBadge({ condition }: { condition: string }) {
  const tone = condition === 'like_new' || condition === 'new' ? 'forest' : condition === 'very_good' || condition === 'good' ? 'sky' : condition === 'unknown' ? 'neutral' : 'gold'
  return <Badge tone={tone}>{CONDITION_LABELS[condition] ?? condition}</Badge>
}

export function StatusBadge({ status }: { status: string }) {
  const tone = status === 'active' ? 'forest' : status === 'sold' ? 'ink' : status === 'removed' ? 'rust' : 'neutral'
  return <Badge tone={tone}>{status[0].toUpperCase() + status.slice(1)}</Badge>
}

export function ListingImage({ listing, className = '' }: { listing: Listing; className?: string }) {
  const src = listing.images[0]?.url ?? listing.cover_url
  return (
    <div className={`relative aspect-[4/5] overflow-hidden rounded-xl bg-parchment ${className}`}>
      {src ? <img src={src} alt={listing.images[0] ? `Seller photo of ${listing.title}` : `Catalogue cover of ${listing.title}`} loading="lazy" className="h-full w-full object-cover" />
        : <div className="flex h-full items-center justify-center text-muted"><ImageIcon className="h-8 w-8" aria-hidden /></div>}
      {!listing.images[0] && src && <span className="absolute bottom-2 left-2 rounded bg-ink/70 px-1.5 py-0.5 text-[10px] text-paper">Catalogue cover, not seller photo</span>}
    </div>
  )
}

export function ListingCard({ listing, onFavorite }: { listing: Listing; onFavorite?: (l: Listing) => void }) {
  return (
    <article className="card group flex flex-col overflow-hidden p-3 transition-shadow hover:shadow-[var(--shadow-lift)]">
      <div className="relative">
        <Link to={`/marketplace/listings/${listing.id}`} aria-label={`${listing.title}, ${money(listing.price_amount, listing.currency)}`}>
          <ListingImage listing={listing} />
        </Link>
        {onFavorite && !listing.is_mine && (
          <button onClick={() => onFavorite(listing)} aria-pressed={listing.is_favorite}
            aria-label={listing.is_favorite ? 'Remove from saved listings' : 'Save listing'}
            className="absolute right-2 top-2 rounded-full bg-paper/90 p-1.5 shadow hover:bg-paper">
            <Heart className={`h-4 w-4 ${listing.is_favorite ? 'fill-rust text-rust' : 'text-ink-soft'}`} />
          </button>
        )}
      </div>
      <div className="mt-3 flex flex-1 flex-col">
        <div className="flex flex-wrap gap-1.5">
          <ConditionBadge condition={listing.condition} />
          {listing.status !== 'active' && <StatusBadge status={listing.status} />}
        </div>
        <Link to={`/marketplace/listings/${listing.id}`} className="mt-2 font-serif font-semibold leading-snug hover:text-forest line-clamp-2">{listing.title}</Link>
        <p className="text-xs text-muted line-clamp-1">{listing.author}{listing.edition_text ? ` · ${listing.edition_text}` : ''}</p>
        <div className="mt-auto pt-2">
          <p className="text-lg font-semibold">{money(listing.price_amount, listing.currency)}</p>
          <p className="text-xs text-muted">
            {listing.delivery === 'pickup' ? 'Pickup only' : listing.shipping_known
              ? `${listing.shipping_cost ? `+ ${money(listing.shipping_cost, listing.currency)} shipping` : 'Free shipping'}`
              : 'Shipping cost not stated'}
          </p>
          {listing.location_city && <p className="mt-1 inline-flex items-center gap-1 text-xs text-ink-soft"><MapPin className="h-3 w-3" aria-hidden />{listing.location_city}</p>}
        </div>
      </div>
    </article>
  )
}

const STEP_ORDER = ['understand', 'identify', 'search', 'validate', 'estimate', 'quality', 'rank', 'explain']

/** Shows only steps that have actually started (from the backend stream). */
export function WorkflowStatus({ steps, running }: { steps: TraceStep[]; running: boolean }) {
  const latest = new Map<string, TraceStep>()
  for (const s of steps) latest.set(s.step, s)
  const shown = STEP_ORDER.filter((k) => latest.has(k)).map((k) => latest.get(k)!)
  if (!shown.length && !running) return null
  return (
    <ol className="card space-y-2 p-4" aria-live="polite" aria-label="Search progress">
      {shown.map((s) => (
        <li key={s.step} className="flex items-start gap-3 text-sm">
          {s.status === 'running' ? <Loader2 className="mt-0.5 h-4 w-4 animate-spin text-gold-dark" aria-hidden />
            : s.status === 'failed' ? <XCircle className="mt-0.5 h-4 w-4 text-rust" aria-hidden />
              : <CheckCircle2 className="mt-0.5 h-4 w-4 text-forest" aria-hidden />}
          <div className="min-w-0 flex-1">
            <p className={s.status === 'running' ? 'font-medium text-ink' : 'text-ink-soft'}>
              {s.label}
              {s.duration_ms !== undefined && s.status !== 'running' && <span className="ml-2 text-xs text-muted">{s.duration_ms} ms</span>}
            </p>
            {s.summary && <p className="text-xs text-muted">{s.summary}</p>}
          </div>
        </li>
      ))}
      {running && !shown.some((s) => s.status === 'running') && (
        <li className="flex items-center gap-3 text-sm text-muted"><Circle className="h-4 w-4" aria-hidden /> Working…</li>
      )}
    </ol>
  )
}

export function VerdictBadge({ verdict }: { verdict: PriceVerdict | null | undefined }) {
  if (!verdict || verdict.verdict === 'unknown') return <Badge tone="neutral" title={verdict?.text}>Price: not enough data</Badge>
  const map = {
    well_below: ['gold', 'Well below typical'], below: ['forest', 'Below typical'], within: ['sky', 'Typical price'],
    above: ['gold', 'Above typical'], well_above: ['rust', 'Well above typical'],
  } as const
  const [tone, label] = map[verdict.verdict]
  return <Badge tone={tone} title={verdict.text}>{label}</Badge>
}

export function PriceEstimateCard({ estimate, title = 'Fair price estimate' }: { estimate: PriceEstimate; title?: string }) {
  const ok = estimate.status !== 'insufficient_data'
  return (
    <section className="card p-5" aria-label={title}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="eyebrow">{title}</p>
          {ok ? (
            <p className="mt-1 font-serif text-3xl font-semibold">{money(estimate.low, estimate.currency)} – {money(estimate.high, estimate.currency)}</p>
          ) : (
            <p className="mt-1 font-serif text-xl font-semibold">Insufficient data to estimate reliably</p>
          )}
          <p className="mt-1 text-sm text-muted">for a {CONDITION_LABELS[estimate.condition]?.toLowerCase()} copy · asking prices, not sale prices</p>
        </div>
        {ok && estimate.confidence && (
          <Badge tone={estimate.confidence === 'high' ? 'forest' : estimate.confidence === 'medium' ? 'sky' : 'gold'}
            title={estimate.confidence_score !== null ? `Based on how many comparable copies were found, how closely they match and how consistent their prices are (score ${estimate.confidence_score})` : undefined}>
            {estimate.confidence} confidence
          </Badge>
        )}
      </div>
      <p className="mt-3 text-sm text-ink-soft">{estimate.explanation}</p>
      {ok && (
        <p className="mt-2 text-xs text-muted">
          {estimate.n_comparables} comparable{estimate.n_comparables === 1 ? '' : 's'}
          {Object.keys(estimate.sources).length > 0 && ` · sources: ${Object.entries(estimate.sources).map(([k, v]) => `${k} (${v})`).join(', ')}`}
          {estimate.status === 'rule_based' && ' · rule-of-thumb from a new-copy price'}
        </p>
      )}
      {estimate.limitations.length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-line pt-3 text-xs text-muted">
          {estimate.limitations.map((l) => <li key={l} className="flex gap-1.5"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-gold-dark" aria-hidden />{l}</li>)}
        </ul>
      )}
    </section>
  )
}

export function DealCard({ deal, rank }: { deal: Deal; rank: number }) {
  const l = deal.listing
  const internal = l.url?.startsWith('/')
  const groupLabel = { match: 'Meets your constraints', near_match: 'Near match', other: 'Doesn’t meet constraints' }[deal.deal.group]
  return (
    <article className={`card flex flex-col gap-4 p-4 sm:flex-row ${deal.deal.group === 'match' && rank === 1 ? 'ring-2 ring-gold/60' : ''}`}>
      <div className="w-full shrink-0 sm:w-28">
        <div className="aspect-[4/5] overflow-hidden rounded-lg bg-parchment">
          {l.image_url ? <img src={l.image_url} alt={`Image for ${l.title}`} loading="lazy" className="h-full w-full object-cover" />
            : <div className="flex h-full items-center justify-center text-muted"><ImageIcon className="h-6 w-6" aria-hidden /></div>}
        </div>
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs font-semibold text-muted">#{rank}</span>
          <Badge tone={l.is_external ? 'sky' : 'forest'}>{l.provider_label}</Badge>
          <ConditionBadge condition={l.condition} />
          <VerdictBadge verdict={deal.deal.price_verdict} />
          <Badge tone={deal.deal.group === 'match' ? 'forest' : deal.deal.group === 'near_match' ? 'gold' : 'neutral'}>{groupLabel}</Badge>
        </div>
        <h3 className="mt-2 font-serif text-lg font-semibold leading-snug">{l.title}</h3>
        <p className="text-xs text-muted">
          {[l.author, l.edition_text, l.isbn && `ISBN ${l.isbn}`].filter(Boolean).join(' · ')}
          {' · '}match: {l.match.replace('_', ' ')}
        </p>
        <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <p className="text-xl font-semibold">{money(l.price, l.currency)}</p>
          <p className="text-sm text-ink-soft">
            <Truck className="mr-1 inline h-3.5 w-3.5" aria-hidden />
            {l.delivery === 'pickup' ? 'Pickup' : l.shipping_known ? (l.shipping_cost ? `+ ${money(l.shipping_cost, l.currency)}` : 'Free shipping') : 'Shipping unknown'}
          </p>
          <p className="text-sm">
            Total: <strong>{money(l.total_known_cost, l.currency)}</strong>
            {!l.total_cost_complete && <span className="ml-1 text-xs text-gold-dark">(incomplete)</span>}
          </p>
        </div>
        {deal.deal.reasons.length > 0 && (
          <ul className="mt-2 space-y-0.5 text-sm text-ink-soft">
            {deal.deal.reasons.slice(0, 4).map((r) => <li key={r} className="flex gap-1.5"><CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-forest" aria-hidden />{r}</li>)}
          </ul>
        )}
        {(deal.deal.unmet.length > 0 || deal.deal.cautions.length > 0) && (
          <ul className="mt-2 space-y-0.5 text-xs text-gold-dark">
            {deal.deal.unmet.map((r) => <li key={r} className="flex gap-1.5"><XCircle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />{r}</li>)}
            {deal.deal.cautions.map((r) => <li key={r} className="flex gap-1.5"><ShieldAlert className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />{r}</li>)}
          </ul>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-muted">
          {l.location && <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" aria-hidden />{l.location}{l.country && l.country !== 'IN' ? `, ${l.country}` : ''}</span>}
          {l.seller_name && <span>Seller: {l.seller_name}</span>}
          {deal.quality && <span title={Object.entries(deal.quality.breakdown).map(([k, v]) => `${k}: ${v}`).join(', ')}>Listing quality {deal.quality.score}/100</span>}
          <span>Checked {relativeTime(l.fetched_at)}</span>
        </div>
      </div>
      <div className="flex shrink-0 items-start sm:flex-col sm:items-end">
        {l.url && (internal
          ? <Link to={l.url} className="btn-primary btn-sm">View listing</Link>
          : <a href={l.url} target="_blank" rel="noopener noreferrer nofollow" className="btn-primary btn-sm">View on {l.provider_label} <ExternalLink className="h-3 w-3" aria-hidden /></a>)}
      </div>
    </article>
  )
}
