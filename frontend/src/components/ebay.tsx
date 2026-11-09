import { ExternalLink, Link2, RefreshCw, Store, Unplug } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useConfirm } from '../contexts/ConfirmContext'
import { useToast } from '../contexts/ToastContext'
import { TTL, queryKey, useGet } from '../hooks/useApi'
import { ApiError, api } from '../services/api'
import { invalidate, setQueryData } from '../services/queryCache'
import type { EbayMarketCheck, EbayPublication, EbaySetup, EbayStatus, Listing } from '../types'
import { CONDITION_LABELS, money } from '../utils/format'
import { Badge, EmptyState, ErrorState, Field, ListSkeleton, Modal, Notice, Skeleton, Spinner } from './ui'

const STATUS = '/api/ebay/status'
const SETUP = '/api/ebay/seller/setup'

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

function FieldErrorList({ fields }: { fields: Record<string, string> }) {
  const entries = Object.entries(fields)
  return entries.length ? <div className="space-y-1">{entries.map(([k, v]) => <p key={k} className="text-sm text-rust" role="alert">{v}</p>)}</div> : null
}

function PublishDialog({ listing, existing, status, onClose }: { listing: Listing; existing?: EbayPublication; status: EbayStatus; onClose: () => void }) {
  const { user } = useAuth()
  const toast = useToast()
  const setup = useGet<EbaySetup>(SETUP, undefined, { userId: user?.id, ttl: TTL.medium })
  const sameCurrency = listing.currency === status.currency
  const [price, setPrice] = useState(existing?.price_amount ? String(existing.price_amount) : sameCurrency ? String(listing.price_amount) : '')
  const [language, setLanguage] = useState('English')
  const [choice, setChoice] = useState({ fulfillment: '', payment: '', ret: '', location: '' })
  const [address, setAddress] = useState({ city: '', state: '', postal_code: '', country: '' })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)

  const data = setup.data
  const selected = {
    fulfillment: choice.fulfillment || data?.fulfillment_policies[0]?.id || '',
    payment: choice.payment || data?.payment_policies[0]?.id || '',
    ret: choice.ret || data?.return_policies[0]?.id || '',
    location: choice.location || data?.locations[0]?.key || '',
  }

  async function addLocation() {
    const missing = Object.entries(address).filter(([, v]) => !v.trim())
    if (missing.length) return setErrors({ address: 'Fill in every address field.' })
    setBusy(true)
    setErrors({})
    try {
      const created = await api.post<{ key: string; name: string }>('/api/ebay/seller/location', address)
      setup.setData((d) => d && { ...d, locations: [...d.locations, created] })
      setChoice((c) => ({ ...c, location: created.key }))
    } catch (e) {
      setErrors({ address: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  async function publish(e: FormEvent) {
    e.preventDefault()
    const amount = Number(price)
    const problems: Record<string, string> = {}
    if (!/^\d+(\.\d{1,2})?$/.test(price.trim()) || amount < 0.99) problems.price = `Enter a price of at least 0.99 ${status.currency}.`
    if (!selected.fulfillment || !selected.payment || !selected.ret) problems.policies = 'Choose a shipping, payment and return policy.'
    if (!selected.location) problems.location = 'Add the location the book ships from.'
    setErrors(problems)
    if (Object.keys(problems).length) return
    setBusy(true)
    try {
      const pub = await api.post<EbayPublication>(`/api/ebay/listings/${listing.id}/publish`, {
        price: amount, language, fulfillment_policy_id: selected.fulfillment, payment_policy_id: selected.payment,
        return_policy_id: selected.ret, merchant_location_key: selected.location,
      })
      setQueryData<EbayStatus>(queryKey(STATUS, undefined, user?.id), (s) => s ? { ...s, publications: [...s.publications.filter((p) => p.listing_id !== pub.listing_id), pub] } : s as unknown as EbayStatus)
      toast.success(existing?.status === 'published' ? 'eBay listing updated.' : 'Your book is live on eBay.')
      onClose()
    } catch (err) {
      const apiErr = err as ApiError
      const field = apiErr.fieldErrors?.[0]?.field
      setErrors(field ? { [field]: apiErr.message } : { form: apiErr.message })
      invalidate(STATUS)
    } finally {
      setBusy(false)
    }
  }

  const select = (id: string, label: string, value: string, options: { id: string; name: string }[], key: keyof typeof choice) => (
    <Field label={label} htmlFor={id}>
      <select id={id} className="input" value={value} onChange={(e) => setChoice((c) => ({ ...c, [key]: e.target.value }))}>
        {options.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
      </select>
    </Field>
  )

  return (
    <Modal open wide onClose={onClose} title={`List “${listing.title}” on eBay`}
      footer={<><button className="btn-ghost" onClick={onClose} type="button">Cancel</button><button className="btn-primary" form="ebay-publish" disabled={busy || setup.loading || !data?.ready && !selected.location}>{busy ? 'Working…' : existing?.status === 'published' ? 'Update on eBay' : 'Publish to eBay'}</button></>}>
      {setup.loading ? <ListSkeleton rows={3} /> : setup.error ? <ErrorState error={setup.error} onRetry={setup.reload} /> : data && (
        <form id="ebay-publish" onSubmit={publish} className="space-y-4" noValidate>
          <TestModeNotice show={status.test_environment} />
          {data.message && <Notice tone="warn" title="Finish setting up on eBay">{data.message} <a href={data.help_url} target="_blank" rel="noopener noreferrer" className="link inline-flex items-center gap-1">Open eBay policies<ExternalLink className="h-3 w-3" aria-hidden /></a> <button type="button" className="link" onClick={setup.reload}>Check again</button></Notice>}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={`Price on eBay (${status.currency})`} htmlFor="eb-price" error={errors.price} hint={sameCurrency ? undefined : `Your BookWorm price is ${money(listing.price_amount, listing.currency)}. Set the amount to charge in ${status.currency}.`}>
              <input id="eb-price" className="input" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} />
            </Field>
            <Field label="Language of the book" htmlFor="eb-lang">
              <select id="eb-lang" className="input" value={language} onChange={(e) => setLanguage(e.target.value)}>
                {['English', 'Hindi', 'Bengali', 'Tamil', 'Spanish', 'French', 'German'].map((l) => <option key={l}>{l}</option>)}
              </select>
            </Field>
            {data.fulfillment_policies.length > 0 && select('eb-ship', 'Shipping policy', selected.fulfillment, data.fulfillment_policies, 'fulfillment')}
            {data.payment_policies.length > 0 && select('eb-pay', 'Payment policy', selected.payment, data.payment_policies, 'payment')}
            {data.return_policies.length > 0 && select('eb-ret', 'Return policy', selected.ret, data.return_policies, 'ret')}
            {data.locations.length > 0 && select('eb-loc', 'Ships from', selected.location, data.locations.map((l) => ({ id: l.key, name: l.name })), 'location')}
          </div>
          {errors.policies && <p className="text-sm text-rust" role="alert">{errors.policies}</p>}
          {data.locations.length === 0 && (
            <fieldset className="rounded-xl border border-line p-3">
              <legend className="px-1 text-sm font-semibold">Where does this book ship from?</legend>
              <div className="grid gap-3 sm:grid-cols-2">
                <input aria-label="City" className="input" placeholder="City" value={address.city} onChange={(e) => setAddress({ ...address, city: e.target.value })} />
                <input aria-label="State or province" className="input" placeholder="State / province" value={address.state} onChange={(e) => setAddress({ ...address, state: e.target.value })} />
                <input aria-label="Postal code" className="input" placeholder="Postal code" value={address.postal_code} onChange={(e) => setAddress({ ...address, postal_code: e.target.value })} />
                <input aria-label="Country code" className="input" placeholder="Country code, e.g. IN" maxLength={2} value={address.country} onChange={(e) => setAddress({ ...address, country: e.target.value.toUpperCase() })} />
              </div>
              {errors.address && <p className="mt-2 text-sm text-rust" role="alert">{errors.address}</p>}
              <button type="button" className="btn-outline btn-sm mt-3" onClick={addLocation} disabled={busy}>Save location</button>
            </fieldset>
          )}
          <FieldErrorList fields={Object.fromEntries(Object.entries(errors).filter(([k]) => ['form', 'location', 'photos', 'condition', 'description'].includes(k)))} />
          <p className="text-xs text-muted">The listing goes on your own eBay account under your policies, and eBay’s fees and rules apply. If you mark it sold or hide it here, it ends on eBay too.</p>
        </form>
      )}
    </Modal>
  )
}

export function EbaySellerPanel({ listings }: { listings: Listing[] }) {
  const toast = useToast()
  const confirm = useConfirm()
  const { user } = useAuth()
  const status = useEbayStatus()
  const [publishing, setPublishing] = useState<Listing | null>(null)
  const [busy, setBusy] = useState(false)
  const [ending, setEnding] = useState<number | null>(null)

  if (status.loading) return <ListSkeleton rows={3} />
  if (status.error) return <ErrorState error={status.error} onRetry={status.reload} />
  const s = status.data
  if (!s) return null
  const byListing = new Map(s.publications.map((p) => [p.listing_id, p]))
  const active = listings.filter((l) => l.status === 'active' || byListing.has(l.id))

  async function connect() {
    setBusy(true)
    try {
      window.location.assign((await api.get<{ url: string }>('/api/ebay/connect')).url)
    } catch (e) {
      toast.error((e as Error).message)
      setBusy(false)
    }
  }

  async function disconnect() {
    if (!await confirm({ title: 'Disconnect your eBay account?', message: 'BookWorm will forget its access to your eBay account. You can reconnect at any time.', confirmLabel: 'Disconnect', danger: true })) return
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

  async function end(l: Listing) {
    if (!await confirm({ title: 'End this eBay listing?', message: `“${l.title}” will stop being for sale on eBay. It stays listed on BookWorm.`, confirmLabel: 'End listing', danger: true })) return
    setEnding(l.id)
    try {
      const pub = await api.post<EbayPublication>(`/api/ebay/listings/${l.id}/end`)
      setQueryData<EbayStatus>(queryKey(STATUS, undefined, user?.id), (cur) => cur ? { ...cur, publications: cur.publications.map((p) => (p.listing_id === pub.listing_id ? pub : p)) } : cur as unknown as EbayStatus)
      toast.info('eBay listing ended.')
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setEnding(null)
    }
  }

  if (!s.seller_tools) {
    return (
      <div className="space-y-4">
        <TestModeNotice show={s.test_environment} />
        <EmptyState icon={<Store className="h-6 w-6" />} title="Check eBay prices while you list">
          Use “Check eBay prices” on the listing form to compare what this book is going for before you set your price.
        </EmptyState>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <TestModeNotice show={s.test_environment} />
      <section className="card flex flex-wrap items-center justify-between gap-4 p-5">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-lg font-semibold"><Store className="h-5 w-5 text-gold-dark" aria-hidden />Your eBay account</h2>
          <p className="mt-1 text-sm text-muted">{s.connected ? 'Connected. You can publish your listings to eBay from here.' : 'Connect your own eBay account to publish your listings there as well.'}</p>
        </div>
        {s.connected
          ? <button className="btn-outline" onClick={disconnect} disabled={busy}><Unplug className="h-4 w-4" aria-hidden />Disconnect</button>
          : <button className="btn-forest" onClick={connect} disabled={busy}><Link2 className="h-4 w-4" aria-hidden />{busy ? 'Opening eBay…' : 'Connect eBay'}</button>}
      </section>
      {s.connected && (
        active.length === 0 ? <EmptyState title="No listings to publish">Create a listing first, then publish it to eBay from here.</EmptyState> : (
          <ul className="divide-y divide-line rounded-xl border border-line bg-paper">
            {active.map((l) => {
              const pub = byListing.get(l.id)
              const live = pub?.status === 'published'
              return (
                <li key={l.id} className="flex flex-wrap items-center gap-3 p-4">
                  <div className="min-w-0 flex-1">
                    <p className="user-text font-semibold">{l.title}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                      {live ? <Badge tone="forest">Live on eBay</Badge> : pub?.status === 'ended' ? <Badge tone="neutral">Ended on eBay</Badge> : <Badge tone="neutral">Not on eBay</Badge>}
                      {live && pub?.price_amount != null && <span>{money(pub.price_amount, pub.currency)}</span>}
                      {l.status !== 'active' && <span>This listing is {l.status} on BookWorm.</span>}
                    </div>
                    {pub?.last_error && <p className="mt-1 text-xs text-rust">eBay said: {pub.last_error}</p>}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {live && pub?.url && <a className="btn-ghost btn-sm" href={pub.url} target="_blank" rel="noopener noreferrer">View <ExternalLink className="h-3 w-3" aria-hidden /></a>}
                    {l.status === 'active' && <button className="btn-outline btn-sm" onClick={() => setPublishing(l)}>{live ? <><RefreshCw className="h-3.5 w-3.5" aria-hidden />Update</> : 'Publish'}</button>}
                    {live && <button className="btn-ghost btn-sm" onClick={() => end(l)} disabled={ending === l.id}>{ending === l.id ? <Spinner label="Ending" /> : 'End'}</button>}
                  </div>
                </li>
              )
            })}
          </ul>
        )
      )}
      {publishing && <PublishDialog listing={publishing} existing={byListing.get(publishing.id)} status={s} onClose={() => setPublishing(null)} />}
    </div>
  )
}
