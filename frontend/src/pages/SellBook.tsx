import { ImagePlus, Link2, Trash2, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { BookSearch } from '../components/BookSearch'
import { EbayMarketCheck } from '../components/ebay'
import { CharCounter, ErrorState, Field, ListSkeleton, Notice, PageHeader } from '../components/ui'
import { useAuth } from '../contexts/AuthContext'
import { useConfirm } from '../contexts/ConfirmContext'
import { useToast } from '../contexts/ToastContext'
import { TTL, useGet } from '../hooks/useApi'
import { ApiError, api } from '../services/api'
import { invalidate } from '../services/queryCache'
import type { BookDetail, BookSummary, Condition, Listing } from '../types'
import { CONDITION_HELP, CONDITION_LABELS } from '../utils/format'
import { LISTING_DESCRIPTION_MAX, LISTING_DESCRIPTION_MIN, MAX_PHOTOS, MAX_PHOTO_MB, MAX_PRICE, MAX_SHIPPING, PHOTO_TYPES, amountProblem, canDecodeImage, hasText, isValidIsbn, photoProblem } from '../utils/validation'

const CONDITIONS: Condition[] = ['like_new', 'very_good', 'good', 'acceptable', 'poor']
const OLDEST_YEAR = 1450
const LISTINGS = '/api/marketplace/listings'

interface FormState {
  title: string; author: string; isbn: string; edition_text: string; published_year: string; description: string
  condition: Condition; price_amount: string; currency: string; delivery: 'pickup' | 'shipping' | 'both'
  shipping_cost: string; location_city: string; location_public: boolean; allow_inquiries: boolean; book_id: number | null
}
type Errors = Partial<Record<keyof FormState | 'photos' | 'form', string>>

function validate(f: FormState): Errors {
  const e: Errors = {}
  const title = f.title.trim()
  if (!title) e.title = 'Enter the book title.'
  else if (!hasText(title)) e.title = 'Enter a real title.'
  else if (title.length > 300) e.title = 'Keep the title under 300 characters.'
  const author = f.author.trim()
  if (!author) e.author = 'Enter the author.'
  else if (!hasText(author)) e.author = 'Enter a real author name.'
  else if (author.length > 200) e.author = 'Keep the author under 200 characters.'
  if (f.isbn.trim() && !isValidIsbn(f.isbn)) e.isbn = 'That ISBN isn’t valid. Check the 10 or 13 digits on the back cover.'
  if (f.edition_text.length > 100) e.edition_text = 'Keep this under 100 characters.'
  if (f.published_year) {
    const y = Number(f.published_year)
    if (!Number.isInteger(y) || y < OLDEST_YEAR || y > new Date().getFullYear() + 1) e.published_year = `Enter a year between ${OLDEST_YEAR} and ${new Date().getFullYear() + 1}.`
  }
  const description = f.description.trim()
  if (description.length < LISTING_DESCRIPTION_MIN) e.description = `Describe your copy in at least ${LISTING_DESCRIPTION_MIN} characters.`
  else if (description.length > LISTING_DESCRIPTION_MAX) e.description = `Keep the description under ${LISTING_DESCRIPTION_MAX} characters.`
  else if (!hasText(description)) e.description = 'Describe your copy in words.'
  const price = f.price_amount.trim()
  if (!price) e.price_amount = 'Enter your asking price.'
  else e.price_amount = amountProblem(price) ?? (Number(price) < 1 ? 'The price must be at least 1.' : Number(price) > MAX_PRICE ? 'That price is too high.' : undefined)
  if (f.delivery !== 'pickup' && f.shipping_cost.trim()) {
    e.shipping_cost = amountProblem(f.shipping_cost) ?? (Number(f.shipping_cost) > MAX_SHIPPING ? 'That shipping cost is too high.' : undefined)
  }
  const city = f.location_city.trim()
  if (!city) e.location_city = 'Enter your city or area so buyers know where the book is.'
  else if (!hasText(city)) e.location_city = 'Enter a real place name.'
  return Object.fromEntries(Object.entries(e).filter(([, v]) => v)) as Errors
}

function Section({ title, children, className = '' }: { title?: string; children: ReactNode; className?: string }) {
  return <section className={`card p-5 ${className}`}>{title && <h2 className="text-lg font-semibold sm:col-span-2">{title}</h2>}{children}</section>
}

export default function SellBook() {
  const { id } = useParams()
  const editing = !!id
  const { user, setUser } = useAuth()
  const toast = useToast()
  const confirm = useConfirm()
  const navigate = useNavigate()
  const existing = useGet<{ listing: Listing }>(editing ? `${LISTINGS}/${id}` : null, undefined, { userId: user?.id, ttl: TTL.short })
  const [form, setForm] = useState<FormState>({
    title: '', author: '', isbn: '', edition_text: '', published_year: '', description: '', condition: 'good', price_amount: '',
    currency: 'INR', delivery: 'pickup', shipping_cost: '', location_city: user?.location_city ?? '', location_public: true,
    allow_inquiries: true, book_id: null,
  })
  const [linked, setLinked] = useState<BookSummary | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [errors, setErrors] = useState<Errors>({})
  const [busy, setBusy] = useState(false)
  const submittingRef = useRef(false)
  const loadedRef = useRef(false)
  const formRef = useRef<HTMLFormElement>(null)

  const previews = useMemo(() => files.map((f) => ({ file: f, url: URL.createObjectURL(f) })), [files])
  useEffect(() => () => previews.forEach((p) => URL.revokeObjectURL(p.url)), [previews])

  const data = existing.data?.listing
  useEffect(() => {
    if (!data || loadedRef.current) return
    if (!data.is_mine) {
      toast.error('You can only edit your own listings.')
      navigate(`/marketplace/listings/${data.id}`, { replace: true })
      return
    }
    loadedRef.current = true
    setForm({
      title: data.title, author: data.author, isbn: data.isbn ?? '', edition_text: data.edition_text ?? '', published_year: data.published_year ? String(data.published_year) : '',
      description: data.description ?? '', condition: data.condition, price_amount: String(data.price_amount), currency: data.currency, delivery: data.delivery,
      shipping_cost: data.shipping_cost && data.delivery !== 'pickup' ? String(data.shipping_cost) : '', location_city: data.location_city ?? '',
      location_public: data.location_public ?? true, allow_inquiries: data.allow_inquiries, book_id: data.book_id,
    })
  }, [data, navigate, toast])

  function set<K extends keyof FormState>(k: K, v: FormState[K]) {
    setForm((f) => ({ ...f, [k]: v }))
    setErrors((e) => (e[k] ? { ...e, [k]: undefined } : e))
  }

  async function pickBook(b: BookSummary) {
    setLinked(b)
    setForm((f) => ({ ...f, title: b.title, author: b.authors.join(', ') || f.author, book_id: b.id }))
    try {
      const d = await api.get<BookDetail>(`/api/books/${b.id}`, { track: false })
      setForm((f) => (f.book_id === d.id ? { ...f, isbn: d.isbn13 ?? f.isbn, published_year: f.published_year || (d.first_published_year ? String(d.first_published_year) : '') } : f))
    } catch { /* the title and author are already filled in */ }
  }

  async function addFiles(list: FileList | null) {
    if (!list) return
    const room = MAX_PHOTOS - (data?.images.length ?? 0) - files.length
    const accepted: File[] = []
    const problems: string[] = []
    const selected = Array.from(list)
    for (const f of selected) {
      if (accepted.length >= room) {
        problems.push(`You can add up to ${MAX_PHOTOS} photos.`)
        break
      }
      const problem = photoProblem(f) ?? (await canDecodeImage(f) ? null : `${f.name} doesn’t look like a valid image.`)
      if (problem) problems.push(problem)
      else if (!files.some((x) => x.name === f.name && x.size === f.size)) accepted.push(f)
    }
    if (accepted.length) setFiles((cur) => [...cur, ...accepted])
    setErrors((e) => ({ ...e, photos: problems.join(' ') || undefined }))
  }

  async function submit(ev: FormEvent) {
    ev.preventDefault()
    if (submittingRef.current) return
    const e = validate(form)
    setErrors(e)
    if (Object.keys(e).length) {
      window.setTimeout(() => formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus(), 0)
      return
    }
    submittingRef.current = true
    setBusy(true)
    const payload = {
      title: form.title.trim(), author: form.author.trim(), isbn: form.isbn.trim() || null, edition_text: form.edition_text.trim() || null,
      published_year: form.published_year ? Number(form.published_year) : null, description: form.description.trim(),
      condition: form.condition, price_amount: Number(form.price_amount), currency: form.currency, delivery: form.delivery,
      shipping_cost: form.delivery !== 'pickup' && form.shipping_cost.trim() !== '' ? Number(form.shipping_cost) : null,
      location_city: form.location_city.trim(), location_public: form.location_public, allow_inquiries: form.allow_inquiries,
      book_id: form.book_id,
    }
    try {
      const listing = editing
        ? await api.patch<Listing>(`${LISTINGS}/${id}`, payload)
        : await api.post<Listing>(LISTINGS, payload)
      let failed = 0
      for (const f of files) {
        try { await api.upload(`${LISTINGS}/${listing.id}/images`, f) } catch { failed++ }
      }
      if (failed) toast.error(`${failed} photo${failed === 1 ? '' : 's'} couldn’t be uploaded. You can add them by editing the listing.`)
      toast.success(editing ? 'Listing updated.' : 'Your book is listed!')
      if (!editing && user && !user.is_seller) setUser({ ...user, is_seller: true })
      invalidate(LISTINGS, '/api/marketplace/seller-dashboard', '/api/marketplace/sellers')
      navigate(`/marketplace/listings/${listing.id}`)
    } catch (err) {
      if (err instanceof ApiError && err.fieldErrors.length) setErrors(Object.fromEntries(err.fieldErrors.map((f) => [f.field || 'form', f.message])) as Errors)
      else setErrors({ form: (err as Error).message })
      window.setTimeout(() => formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"], [data-form-error]')?.focus(), 0)
    } finally {
      submittingRef.current = false
      setBusy(false)
    }
  }

  async function deleteImage(imageId: number) {
    if (!await confirm({ title: 'Delete this photo?', confirmLabel: 'Delete', danger: true })) return
    try {
      await api.del(`${LISTINGS}/${id}/images/${imageId}`)
      existing.setData((d) => d && { ...d, listing: { ...d.listing, images: d.listing.images.filter((i) => i.id !== imageId) } })
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  if (editing && existing.loading) return <div className="mx-auto max-w-3xl"><ListSkeleton rows={4} /></div>
  if (editing && existing.error) return <ErrorState error={existing.error} onRetry={existing.reload} />
  const existingImages = data?.images ?? []
  const inv = (k: keyof Errors) => (errors[k] ? { 'aria-invalid': true as const, 'aria-describedby': `${k}-err` } : {})

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader eyebrow="Sell a book" title={editing ? 'Edit your listing' : 'List a book for sale'}>
        Describe the actual copy you have. Buyers contact you through BookWorm and you arrange payment and handover yourselves.
      </PageHeader>
      <form ref={formRef} onSubmit={submit} className="space-y-8" noValidate>
        {!editing && (
          <Section title="Find it in the catalogue (recommended)">
            <p className="text-sm text-muted">Linking fills in details and helps buyers and price checks match the right edition.</p>
            {linked ? (
              <div className="mt-3 flex items-center gap-3 rounded-lg border border-forest/30 bg-forest-soft px-3 py-2 text-sm">
                <Link2 className="h-4 w-4 shrink-0 text-forest" aria-hidden /><span className="user-text min-w-0 flex-1">Linked to <strong>{linked.title}</strong></span>
                <button type="button" aria-label="Unlink" onClick={() => { setLinked(null); set('book_id', null) }}><X className="h-4 w-4" /></button>
              </div>
            ) : <div className="mt-3"><BookSearch id="sell-search" onPick={pickBook} emptyText="Not found. Just fill in the details below." /></div>}
          </Section>
        )}

        <Section title="Book details" className="grid gap-4 sm:grid-cols-2">
          <Field label="Title *" htmlFor="title" error={errors.title} errorId="title-err"><input id="title" className="input" value={form.title} onChange={(e) => set('title', e.target.value)} required {...inv('title')} /></Field>
          <Field label="Author *" htmlFor="author" error={errors.author} errorId="author-err"><input id="author" className="input" value={form.author} onChange={(e) => set('author', e.target.value)} required {...inv('author')} /></Field>
          <Field label="ISBN" htmlFor="isbn" error={errors.isbn} errorId="isbn-err" hint="On the back cover or copyright page."><input id="isbn" className="input" inputMode="numeric" value={form.isbn} onChange={(e) => set('isbn', e.target.value)} {...inv('isbn')} /></Field>
          <Field label="Edition / format" htmlFor="edition" error={errors.edition_text} errorId="edition_text-err" hint="e.g. 2nd edition, paperback"><input id="edition" className="input" value={form.edition_text} onChange={(e) => set('edition_text', e.target.value)} {...inv('edition_text')} /></Field>
          <Field label="Publication year" htmlFor="year" error={errors.published_year} errorId="published_year-err"><input id="year" inputMode="numeric" className="input" value={form.published_year} onChange={(e) => set('published_year', e.target.value)} {...inv('published_year')} /></Field>
          <div className="sm:col-span-2">
            <Field label="Description of your copy *" htmlFor="desc" error={errors.description} errorId="description-err" hint="Mention markings, highlights, damage or anything a buyer should know.">
              <textarea id="desc" className="input" rows={4} value={form.description} onChange={(e) => set('description', e.target.value)} required {...inv('description')} />
            </Field>
            <div className="mt-1 text-right"><CharCounter value={form.description.length} max={LISTING_DESCRIPTION_MAX} warnAt={0.9} /></div>
          </div>
        </Section>

        <Section title="Condition *">
          <div className="mt-3 grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Condition">
            {CONDITIONS.map((c) => (
              <label key={c} className="flex cursor-pointer gap-3 rounded-lg border border-line px-3 py-2 transition-colors has-[:checked]:border-forest has-[:checked]:bg-forest-soft">
                <input type="radio" name="condition" checked={form.condition === c} onChange={() => set('condition', c)} className="mt-1" />
                <span><span className="font-medium">{CONDITION_LABELS[c]}</span><span className="block text-xs text-muted">{CONDITION_HELP[c]}</span></span>
              </label>
            ))}
          </div>
        </Section>

        <Section title="Price & delivery" className="grid gap-4 sm:grid-cols-2">
          <Field label="Asking price *" htmlFor="price" error={errors.price_amount} errorId="price_amount-err">
            <div className="flex gap-2">
              <select aria-label="Currency" className="input w-24 shrink-0" value={form.currency} onChange={(e) => set('currency', e.target.value)}>
                {['INR', 'USD', 'EUR', 'GBP'].map((c) => <option key={c}>{c}</option>)}
              </select>
              <input id="price" inputMode="decimal" className="input" value={form.price_amount} onChange={(e) => set('price_amount', e.target.value)} required {...inv('price_amount')} />
            </div>
          </Field>
          <Field label="Delivery" htmlFor="delivery">
            <select id="delivery" className="input" value={form.delivery} onChange={(e) => set('delivery', e.target.value as FormState['delivery'])}>
              <option value="pickup">Pickup only</option><option value="shipping">Shipping only</option><option value="both">Pickup or shipping</option>
            </select>
          </Field>
          <EbayMarketCheck title={form.title} author={form.author} isbn={form.isbn} condition={form.condition} currency={form.currency} onUsePrice={(p) => set('price_amount', String(p))} />
          {form.delivery !== 'pickup' && (
            <Field label="Shipping cost" htmlFor="ship" error={errors.shipping_cost} errorId="shipping_cost-err" hint="Leave empty if unknown (buyers will see the total as incomplete). Use 0 for free shipping.">
              <input id="ship" inputMode="decimal" className="input" value={form.shipping_cost} onChange={(e) => set('shipping_cost', e.target.value)} {...inv('shipping_cost')} />
            </Field>
          )}
          <Field label="City / area *" htmlFor="city" error={errors.location_city} errorId="location_city-err" hint="Keep it approximate, e.g. “Salt Lake, Kolkata”.">
            <input id="city" className="input" maxLength={80} value={form.location_city} onChange={(e) => set('location_city', e.target.value)} required {...inv('location_city')} />
          </Field>
          <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" checked={form.location_public} onChange={(e) => set('location_public', e.target.checked)} />Show my city on the listing</label>
          <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" checked={form.allow_inquiries} onChange={(e) => set('allow_inquiries', e.target.checked)} />Let buyers message me about this listing</label>
        </Section>

        <Section title="Photos of your copy">
          <p className="text-sm text-muted">Up to {MAX_PHOTOS} JPEG, PNG or WEBP images, {MAX_PHOTO_MB} MB each. Location metadata (EXIF) is removed automatically.</p>
          <div className="mt-3 flex flex-wrap gap-3">
            {existingImages.map((im) => (
              <div key={im.id} className="relative h-24 w-20 overflow-hidden rounded-lg border border-line">
                <img src={im.url} alt="Uploaded" loading="lazy" className="h-full w-full object-cover" />
                <button type="button" onClick={() => deleteImage(im.id)} aria-label="Delete photo" className="absolute right-1 top-1 rounded-full bg-paper p-1"><Trash2 className="h-3 w-3" /></button>
              </div>
            ))}
            {previews.map((p) => (
              <div key={p.url} className="relative h-24 w-20 overflow-hidden rounded-lg border border-line">
                <img src={p.url} alt={`Selected ${p.file.name}`} className="h-full w-full object-cover" />
                <button type="button" onClick={() => setFiles((cur) => cur.filter((f) => f !== p.file))} aria-label={`Remove ${p.file.name}`} className="absolute right-1 top-1 rounded-full bg-paper p-1"><X className="h-3 w-3" /></button>
              </div>
            ))}
            {existingImages.length + files.length < MAX_PHOTOS && (
              <label className="flex h-24 w-20 cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-line text-xs text-muted transition-colors hover:border-ink-soft">
                <ImagePlus className="h-5 w-5" aria-hidden />Add
                <input type="file" accept={PHOTO_TYPES.join(',')} multiple className="sr-only" onChange={(e) => { void addFiles(e.target.files); e.target.value = '' }} />
              </label>
            )}
          </div>
          {errors.photos && <p className="mt-2 text-xs text-rust" role="alert">{errors.photos}</p>}
        </Section>

        {Object.keys(errors).some((k) => errors[k as keyof Errors]) && !errors.form && <Notice tone="warn">Please fix the highlighted fields.</Notice>}
        {errors.form && <div tabIndex={-1} data-form-error><Notice tone="warn">{errors.form}</Notice></div>}
        <Notice tone="info">No online payments: you and the buyer agree on payment and handover. BookWorm doesn’t guarantee transactions.</Notice>
        <div className="flex gap-2">
          <button className="btn-primary px-6" disabled={busy}>{busy ? 'Saving…' : editing ? 'Save changes' : 'Publish listing'}</button>
          <Link to={editing ? `/marketplace/listings/${id}` : '/marketplace'} className="btn-ghost">Cancel</Link>
        </div>
      </form>
    </div>
  )
}
