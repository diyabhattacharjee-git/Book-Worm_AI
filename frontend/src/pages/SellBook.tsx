import { ImagePlus, Link2, Trash2, X } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { Field, Notice, PageHeader, Spinner } from '../components/ui'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { useApi, useDebounced } from '../hooks/useApi'
import { ApiError, api } from '../services/api'
import type { BookDetail, BookSummary, Condition, Listing, Page } from '../types'
import { CONDITION_HELP, CONDITION_LABELS } from '../utils/format'

const CONDITIONS: Condition[] = ['like_new', 'very_good', 'good', 'acceptable', 'poor']
const MAX_PHOTOS = 6
const MAX_MB = 5
const ALLOWED = ['image/jpeg', 'image/png', 'image/webp']

interface FormState {
  title: string; author: string; isbn: string; edition_text: string; published_year: string; description: string
  condition: Condition; price_amount: string; currency: string; delivery: 'pickup' | 'shipping' | 'both'
  shipping_cost: string; location_city: string; location_public: boolean; allow_inquiries: boolean; book_id: number | null
}

export default function SellBook() {
  const { id } = useParams()
  const editing = !!id
  const { user, refresh } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const existing = useApi(() => api.get<{ listing: Listing }>(`/api/marketplace/listings/${id}`), [id], editing)
  const [form, setForm] = useState<FormState>({
    title: '', author: '', isbn: '', edition_text: '', published_year: '', description: '', condition: 'good', price_amount: '',
    currency: 'INR', delivery: 'pickup', shipping_cost: '', location_city: user?.location_city ?? '', location_public: true,
    allow_inquiries: true, book_id: null,
  })
  const [linked, setLinked] = useState<BookSummary | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [q, setQ] = useState('')
  const dq = useDebounced(q)
  const found = useApi(() => api.get<Page<BookSummary>>('/api/books', { q: dq, page_size: 5 }), [dq], dq.length > 1)

  useEffect(() => {
    const l = existing.data?.listing
    if (!l) return
    if (!l.is_mine) {
      toast.error('You can only edit your own listings.')
      navigate(`/marketplace/listings/${l.id}`)
      return
    }
    setForm({
      title: l.title, author: l.author, isbn: l.isbn ?? '', edition_text: l.edition_text ?? '', published_year: l.published_year ? String(l.published_year) : '',
      description: l.description ?? '', condition: l.condition, price_amount: String(l.price_amount), currency: l.currency, delivery: l.delivery,
      shipping_cost: l.shipping_cost && l.delivery !== 'pickup' ? String(l.shipping_cost) : '', location_city: l.location_city ?? '',
      location_public: l.location_public ?? true, allow_inquiries: l.allow_inquiries, book_id: l.book_id,
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existing.data])

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setForm((f) => ({ ...f, [k]: v }))

  function pickBook(b: BookSummary) {
    api.get<BookDetail>(`/api/books/${b.id}`).then((d) => {
      setLinked(d)
      setForm((f) => ({ ...f, title: d.title, author: d.authors.join(', ') || f.author, isbn: d.isbn13 ?? f.isbn, book_id: d.id }))
    })
    setQ('')
  }

  function addFiles(list: FileList | null) {
    if (!list) return
    const next = [...files]
    for (const f of Array.from(list)) {
      if (!ALLOWED.includes(f.type)) { toast.error(`${f.name}: only JPEG, PNG or WEBP images.`); continue }
      if (f.size > MAX_MB * 1024 * 1024) { toast.error(`${f.name} is larger than ${MAX_MB} MB.`); continue }
      next.push(f)
    }
    const existingCount = existing.data?.listing.images.length ?? 0
    setFiles(next.slice(0, MAX_PHOTOS - existingCount))
  }

  function validate(): Record<string, string> {
    const e: Record<string, string> = {}
    if (!form.title.trim()) e.title = 'Enter the book title.'
    if (!form.author.trim()) e.author = 'Enter the author.'
    const price = Number(form.price_amount)
    if (!form.price_amount || !(price > 0)) e.price_amount = 'Enter a price greater than 0.'
    if (form.isbn && !/^[\d-xX ]{10,17}$/.test(form.isbn)) e.isbn = 'ISBN should be 10 or 13 digits.'
    if (form.delivery !== 'pickup' && form.shipping_cost && Number(form.shipping_cost) < 0) e.shipping_cost = 'Shipping can’t be negative.'
    return e
  }

  async function submit(ev: FormEvent) {
    ev.preventDefault()
    const e = validate()
    setErrors(e)
    if (Object.keys(e).length) return
    setBusy(true)
    const payload = {
      title: form.title.trim(), author: form.author.trim(), isbn: form.isbn.trim() || null, edition_text: form.edition_text.trim() || null,
      published_year: form.published_year ? Number(form.published_year) : null, description: form.description.trim() || null,
      condition: form.condition, price_amount: Number(form.price_amount), currency: form.currency, delivery: form.delivery,
      shipping_cost: form.delivery !== 'pickup' && form.shipping_cost !== '' ? Number(form.shipping_cost) : null,
      location_city: form.location_city.trim() || null, location_public: form.location_public, allow_inquiries: form.allow_inquiries,
      book_id: form.book_id,
    }
    try {
      const listing = editing
        ? await api.patch<Listing>(`/api/marketplace/listings/${id}`, payload)
        : await api.post<Listing>('/api/marketplace/listings', payload)
      let failed = 0
      for (const f of files) {
        try { await api.upload(`/api/marketplace/listings/${listing.id}/images`, f) } catch { failed++ }
      }
      if (failed) toast.error(`${failed} photo(s) couldn’t be uploaded.`)
      toast.success(editing ? 'Listing updated.' : 'Your book is listed!')
      if (!editing) await refresh()
      navigate(`/marketplace/listings/${listing.id}`)
    } catch (err) {
      if (err instanceof ApiError && err.fieldErrors.length) setErrors(Object.fromEntries(err.fieldErrors.map((f) => [f.field || 'form', f.message])))
      else setErrors({ form: (err as Error).message })
    } finally {
      setBusy(false)
    }
  }

  async function deleteImage(imageId: number) {
    await api.del(`/api/marketplace/listings/${id}/images/${imageId}`)
    existing.reload()
  }

  if (editing && existing.loading) return <Spinner />
  const existingImages = existing.data?.listing.images ?? []

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader eyebrow="Sell a book" title={editing ? 'Edit your listing' : 'List a book for sale'}>
        Describe the actual copy you have. Buyers contact you through BookWorm and you arrange payment and handover yourselves.
      </PageHeader>
      <form onSubmit={submit} className="space-y-8" noValidate>
        {!editing && (
          <section className="card p-5">
            <h2 className="text-lg font-semibold">Find it in the catalogue (recommended)</h2>
            <p className="text-sm text-muted">Linking fills in details and helps buyers and price checks match the right edition.</p>
            {linked ? (
              <div className="mt-3 flex items-center gap-3 rounded-lg border border-forest/30 bg-forest-soft px-3 py-2 text-sm">
                <Link2 className="h-4 w-4 text-forest" aria-hidden /><span className="flex-1">Linked to <strong>{linked.title}</strong></span>
                <button type="button" aria-label="Unlink" onClick={() => { setLinked(null); set('book_id', null) }}><X className="h-4 w-4" /></button>
              </div>
            ) : (
              <>
                <label htmlFor="sell-search" className="sr-only">Search catalogue</label>
                <input id="sell-search" className="input mt-3" placeholder="Search by title, author or ISBN" value={q} onChange={(e) => setQ(e.target.value)} />
                {found.data && dq.length > 1 && (
                  <ul className="mt-1 divide-y divide-line rounded-lg border border-line bg-white">
                    {found.data.items.map((b) => <li key={b.id}><button type="button" className="w-full px-3 py-2 text-left text-sm hover:bg-parchment" onClick={() => pickBook(b)}>{b.title} <span className="text-muted">· {b.authors.join(', ')}</span></button></li>)}
                    {found.data.items.length === 0 && <li className="px-3 py-2 text-sm text-muted">Not found. Just fill in the details below.</li>}
                  </ul>
                )}
              </>
            )}
          </section>
        )}

        <section className="card grid gap-4 p-5 sm:grid-cols-2">
          <h2 className="text-lg font-semibold sm:col-span-2">Book details</h2>
          <Field label="Title *" htmlFor="title" error={errors.title}><input id="title" className="input" value={form.title} onChange={(e) => set('title', e.target.value)} maxLength={300} /></Field>
          <Field label="Author *" htmlFor="author" error={errors.author}><input id="author" className="input" value={form.author} onChange={(e) => set('author', e.target.value)} maxLength={200} /></Field>
          <Field label="ISBN" htmlFor="isbn" error={errors.isbn} hint="On the back cover or copyright page."><input id="isbn" className="input" value={form.isbn} onChange={(e) => set('isbn', e.target.value)} maxLength={17} /></Field>
          <Field label="Edition / format" htmlFor="edition" hint="e.g. 2nd edition, paperback"><input id="edition" className="input" value={form.edition_text} onChange={(e) => set('edition_text', e.target.value)} maxLength={100} /></Field>
          <Field label="Publication year" htmlFor="year"><input id="year" type="number" className="input" value={form.published_year} onChange={(e) => set('published_year', e.target.value)} /></Field>
          <div className="sm:col-span-2">
            <Field label="Description of your copy" htmlFor="desc" hint="Mention markings, highlights, damage or anything a buyer should know.">
              <textarea id="desc" className="input" rows={4} maxLength={3000} value={form.description} onChange={(e) => set('description', e.target.value)} />
            </Field>
          </div>
        </section>

        <section className="card p-5">
          <h2 className="text-lg font-semibold">Condition</h2>
          <div className="mt-3 grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Condition">
            {CONDITIONS.map((c) => (
              <label key={c} className="flex cursor-pointer gap-3 rounded-lg border border-line px-3 py-2 has-[:checked]:border-forest has-[:checked]:bg-forest-soft">
                <input type="radio" name="condition" checked={form.condition === c} onChange={() => set('condition', c)} className="mt-1" />
                <span><span className="font-medium">{CONDITION_LABELS[c]}</span><span className="block text-xs text-muted">{CONDITION_HELP[c]}</span></span>
              </label>
            ))}
          </div>
        </section>

        <section className="card grid gap-4 p-5 sm:grid-cols-2">
          <h2 className="text-lg font-semibold sm:col-span-2">Price & delivery</h2>
          <Field label="Asking price *" htmlFor="price" error={errors.price_amount}>
            <div className="flex gap-2">
              <select aria-label="Currency" className="input w-24" value={form.currency} onChange={(e) => set('currency', e.target.value)}>
                {['INR', 'USD', 'EUR', 'GBP'].map((c) => <option key={c}>{c}</option>)}
              </select>
              <input id="price" type="number" min={1} step="0.01" className="input" value={form.price_amount} onChange={(e) => set('price_amount', e.target.value)} />
            </div>
          </Field>
          <Field label="Delivery" htmlFor="delivery">
            <select id="delivery" className="input" value={form.delivery} onChange={(e) => set('delivery', e.target.value as FormState['delivery'])}>
              <option value="pickup">Pickup only</option><option value="shipping">Shipping only</option><option value="both">Pickup or shipping</option>
            </select>
          </Field>
          {form.delivery !== 'pickup' && (
            <Field label="Shipping cost" htmlFor="ship" error={errors.shipping_cost} hint="Leave empty if unknown (buyers will see the total as incomplete). Use 0 for free shipping.">
              <input id="ship" type="number" min={0} step="0.01" className="input" value={form.shipping_cost} onChange={(e) => set('shipping_cost', e.target.value)} />
            </Field>
          )}
          <Field label="City / area" htmlFor="city" hint="Keep it approximate, e.g. “Salt Lake, Kolkata”.">
            <input id="city" className="input" value={form.location_city} onChange={(e) => set('location_city', e.target.value)} maxLength={80} />
          </Field>
          <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" checked={form.location_public} onChange={(e) => set('location_public', e.target.checked)} />Show my city on the listing</label>
          <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" checked={form.allow_inquiries} onChange={(e) => set('allow_inquiries', e.target.checked)} />Let buyers message me about this listing</label>
        </section>

        <section className="card p-5">
          <h2 className="text-lg font-semibold">Photos of your copy</h2>
          <p className="text-sm text-muted">Up to {MAX_PHOTOS} JPEG, PNG or WEBP images, {MAX_MB} MB each. Location metadata (EXIF) is removed automatically.</p>
          <div className="mt-3 flex flex-wrap gap-3">
            {existingImages.map((im) => (
              <div key={im.id} className="relative h-24 w-20 overflow-hidden rounded-lg border border-line">
                <img src={im.url} alt="Uploaded" className="h-full w-full object-cover" />
                <button type="button" onClick={() => deleteImage(im.id)} aria-label="Delete photo" className="absolute right-1 top-1 rounded-full bg-paper p-1"><Trash2 className="h-3 w-3" /></button>
              </div>
            ))}
            {files.map((f, i) => (
              <div key={i} className="relative h-24 w-20 overflow-hidden rounded-lg border border-line">
                <img src={URL.createObjectURL(f)} alt={`Selected ${f.name}`} className="h-full w-full object-cover" />
                <button type="button" onClick={() => setFiles(files.filter((_, j) => j !== i))} aria-label={`Remove ${f.name}`} className="absolute right-1 top-1 rounded-full bg-paper p-1"><X className="h-3 w-3" /></button>
              </div>
            ))}
            {existingImages.length + files.length < MAX_PHOTOS && (
              <label className="flex h-24 w-20 cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-line text-xs text-muted hover:border-ink-soft">
                <ImagePlus className="h-5 w-5" aria-hidden />Add
                <input type="file" accept={ALLOWED.join(',')} multiple className="sr-only" onChange={(e) => { addFiles(e.target.files); e.target.value = '' }} />
              </label>
            )}
          </div>
        </section>

        {errors.form && <Notice tone="warn">{errors.form}</Notice>}
        <Notice tone="info">No online payments: you and the buyer agree on payment and handover. BookWorm doesn’t guarantee transactions.</Notice>
        <div className="flex gap-2">
          <button className="btn-primary px-6" disabled={busy}>{busy ? 'Saving…' : editing ? 'Save changes' : 'Publish listing'}</button>
          <Link to={editing ? `/marketplace/listings/${id}` : '/marketplace'} className="btn-ghost">Cancel</Link>
        </div>
      </form>
    </div>
  )
}
