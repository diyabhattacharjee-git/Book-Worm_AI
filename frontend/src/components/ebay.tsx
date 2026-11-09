import { Search, Store, Unplug } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useConfirm } from '../contexts/ConfirmContext'
import { useToast } from '../contexts/ToastContext'
import { TTL, useGet } from '../hooks/useApi'
import { api } from '../services/api'
import { invalidate } from '../services/queryCache'
import type { EbayMarketCheck, EbayStatus, EbayUsedBooksResult, Listing } from '../types'
import { CONDITION_LABELS, money } from '../utils/format'
import { Badge, EmptyState, ErrorState, ListSkeleton, Notice, Skeleton } from './ui'

const STATUS = '/api/ebay/status'
const USED_BOOKS = '/api/ebay/used-books'
const SUGGESTED_TITLES = 6

export function useEbayStatus() {
  const { user } = useAuth()
  return useGet<EbayStatus>(STATUS, undefined, { userId: user?.id, ttl: TTL.long })
}

function TestModeNotice({ show }: { show: boolean }) {
  if (!show) return null
  return <Notice tone="warn" title="eBay test mode">This site is connected to eBay’s sandbox, so results are test data and nothing is really for sale.</Notice>
}

/** Live asking prices for one book. Only runs when the seller presses the button. */
export function EbayMarketCheck({ title, author, isbn, condition, currency, onUsePrice }: {
  title: string; author: string; isbn: string; condition: string; currency: string; onUsePrice?: (price: number) => void
}) {
  const status = useEbayStatus()
  const [result, setResult] = useState<EbayMarketCheck | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!status.data?.market_check) return null

  async function check() {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      setResult(await api.get<EbayMarketCheck>('/api/ebay/market-check', { title: title.trim(), author: author.trim() || undefined, isbn: isbn.trim() || undefined, condition }))
    } catch (e) {
      setResult(null)
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const estimate = result?.estimate
  const usable = estimate && estimate.status !== 'insufficient_data' && estimate.median !== null

  return (
    <div className="rounded-xl border border-line bg-white p-4 sm:col-span-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold">What’s it listed for on eBay?</p>
          <p className="text-xs text-muted">Compares current eBay asking prices for this book.</p>
        </div>
        <button type="button" className="btn-outline btn-sm" onClick={check} disabled={busy || !title.trim()}>{busy ? 'Checking…' : result ? 'Check again' : 'Check eBay prices'}</button>
      </div>
      {!title.trim() && <p className="mt-2 text-xs text-muted">Enter the title first.</p>}
      {error && <p className="mt-2 text-xs text-rust" role="alert">{error}</p>}
      {busy && !result && <Skeleton className="mt-3 h-16" />}
      {result && (
        <div className="mt-3 space-y-3">
          <TestModeNotice show={result.test_environment} />
          {result.total_found === 0 ? <p className="text-sm text-muted">No matching copies are listed on eBay right now.</p> : (
            <>
              {usable ? (
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm">Typical asking price for a {CONDITION_LABELS[condition]?.toLowerCase()} copy: <strong>{money(estimate.low, result.currency)} – {money(estimate.high, result.currency)}</strong></p>
                  {onUsePrice && result.currency === currency && estimate.median !== null && <button type="button" className="btn-ghost btn-sm" onClick={() => onUsePrice(estimate.median as number)}>Use {money(estimate.median, result.currency)}</button>}
                </div>
              ) : <p className="text-sm text-muted">Too few comparable copies to suggest a price{result.lowest !== null ? `; the lowest is ${money(result.lowest, result.currency)}` : ''}.</p>}
              {result.currency !== currency && <p className="text-xs text-muted">eBay prices are in {result.currency}, so they’re shown for reference only.</p>}
              <ul className="divide-y divide-line text-sm">
                {result.items.map((item) => (
                  <li key={item.url} className="flex items-center justify-between gap-3 py-1.5">
                    <a href={item.url} target="_blank" rel="noopener noreferrer nofollow" className="link min-w-0 flex-1 truncate" title={item.title}>{item.title}</a>
                    <span className="shrink-0 text-xs text-muted">{CONDITION_LABELS[item.condition] ?? item.condition}</span>
                    <span className="shrink-0 font-medium">{money(item.price, item.currency)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function EbayBook({ item }: { item: EbayUsedBooksResult['items'][number] }) {
  const shipping = !item.shipping_known ? 'Shipping shown on eBay' : item.shipping_cost ? `+ ${money(item.shipping_cost, item.currency)} shipping` : 'Free shipping'
  const place = [item.location, item.country].filter(Boolean).join(', ')
  return (
    <li className="card flex gap-3 p-3">
      <div className="h-24 w-16 shrink-0 overflow-hidden rounded bg-parchment">{item.image_url && <img src={item.image_url} alt="" loading="lazy" decoding="async" className="h-full w-full object-cover" />}</div>
      <div className="min-w-0 flex-1">
        <a href={item.url} target="_blank" rel="noopener noreferrer nofollow" className="user-text line-clamp-2 font-medium hover:text-forest">{item.title}</a>
        <div className="mt-1"><Badge>{item.condition === 'unknown' ? 'Used' : CONDITION_LABELS[item.condition] ?? 'Used'}</Badge></div>
        <p className="mt-1 font-semibold">{money(item.price, item.currency)}</p>
        <p className="text-xs text-muted">{shipping}{place ? ` · ${place}` : ''}</p>
      </div>
    </li>
  )
}

/** Second-hand books for sale on eBay. Read-only: nothing is ever sent to eBay from here. */
export function EbayUsedBooks({ listings }: { listings: Listing[] }) {
  const { user } = useAuth()
  const toast = useToast()
  const confirm = useConfirm()
  const status = useEbayStatus()
  const titles = [...new Set(listings.filter((l) => l.status === 'active').map((l) => l.title))].slice(0, SUGGESTED_TITLES)
  const [term, setTerm] = useState('')
  const [chosen, setChosen] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const query = chosen ?? titles[0] ?? ''
  const books = useGet<EbayUsedBooksResult>(USED_BOOKS, query ? { q: query } : undefined, { userId: user?.id, ttl: TTL.long, keepPrevious: true })

  function search(e: FormEvent) {
    e.preventDefault()
    setChosen(term.trim() || null)
  }

  async function disconnect() {
    if (!await confirm({ title: 'Disconnect your eBay account?', message: 'BookWorm will forget its access to your eBay account.', confirmLabel: 'Disconnect', danger: true })) return
    setBusy(true)
    try {
      await api.del('/api/ebay/account')
      invalidate(STATUS)
      toast.info('eBay account disconnected.')
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold"><Store className="h-5 w-5 text-gold-dark" aria-hidden />Second-hand books on eBay</h2>
        <p className="mt-1 text-sm text-muted">Live listings from eBay sellers. Prices are their asking prices, and buying happens on eBay.</p>
      </div>
      <TestModeNotice show={!!books.data?.test_environment} />
      <form onSubmit={search} className="flex gap-2" role="search">
        <label htmlFor="ebay-search" className="sr-only">Search second-hand books on eBay</label>
        <input id="ebay-search" className="input" maxLength={200} value={term} onChange={(e) => setTerm(e.target.value)} placeholder="Title, author or ISBN" />
        <button className="btn-primary"><Search className="h-4 w-4" aria-hidden />Search</button>
      </form>
      {titles.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted">Your listings:</span>
          {titles.map((t) => <button key={t} type="button" aria-pressed={query === t} className={`chip max-w-xs truncate hover:border-ink-soft ${query === t ? 'border-ink-soft' : ''}`} onClick={() => { setTerm(''); setChosen(t) }}>{t}</button>)}
        </div>
      )}
      {books.loading ? <ListSkeleton rows={4} />
        : books.error ? <ErrorState error={books.error} onRetry={books.reload} />
          : !books.data?.items.length ? <EmptyState title="No second-hand copies found">Try a different title or author.</EmptyState>
            : (
              <div className={`transition-opacity ${books.refreshing ? 'opacity-60' : ''}`}>
                <p className="mb-3 text-sm text-muted">{query ? `Results for “${query}”` : 'Second-hand books for sale now'}</p>
                <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{books.data.items.map((item) => <EbayBook key={item.url} item={item} />)}</ul>
              </div>
            )}
      {status.data?.connected && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
          <p className="text-sm text-muted">Your eBay account is still connected, but BookWorm doesn’t need it to show these books.</p>
          <button className="btn-outline btn-sm" onClick={disconnect} disabled={busy}><Unplug className="h-4 w-4" aria-hidden />Disconnect</button>
        </div>
      )}
    </div>
  )
}
