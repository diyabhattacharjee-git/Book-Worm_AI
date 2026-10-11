import { BookOpen, ListPlus, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { BookCover, BookRow } from '../components/books'
import { EmptyState, ErrorState, Modal, PageHeader, Spinner, Tabs } from '../components/ui'
import { useToast } from '../contexts/ToastContext'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import type { BookSummary, ShelfEntry, ShelfStatus } from '../types'
import { SHELF_LABELS, date } from '../utils/format'

type Tab = ShelfStatus | 'lists'
interface ReadingList { id: number; name: string; description: string | null; books: BookSummary[] }

export default function Bookshelf() {
  const [tab, setTab] = useState<Tab>('reading')
  const shelf = useApi(() => api.get<{ items: ShelfEntry[]; counts: Record<string, number> }>('/api/bookshelf'), [])
  const counts = shelf.data?.counts ?? {}
  return (
    <div>
      <PageHeader eyebrow="Bookshelf" title="My bookshelf" actions={<Link to="/history" className="btn-outline">History & goals</Link>}>
        Track what you’re reading, what’s next and what you’ve finished.
      </PageHeader>
      <Tabs<Tab> label="Shelves" value={tab} onChange={setTab} tabs={[
        ...(['reading', 'want_to_read', 'read', 'abandoned'] as ShelfStatus[]).map((s) => ({ value: s as Tab, label: SHELF_LABELS[s], count: counts[s] ?? 0 })),
        { value: 'lists', label: 'Custom lists' },
      ]} />
      <div className="mt-6">
        {tab === 'lists' ? <Lists /> : shelf.loading ? <Spinner /> : shelf.error ? <ErrorState error={shelf.error} onRetry={shelf.reload} /> : (
          <ShelfList entries={shelf.data!.items.filter((e) => e.status === tab)} status={tab} onChange={shelf.reload} />
        )}
      </div>
    </div>
  )
}

function ShelfList({ entries, status, onChange }: { entries: ShelfEntry[]; status: ShelfStatus; onChange: () => void }) {
  const toast = useToast()
  const [pages, setPages] = useState<Record<number, string>>({})

  async function patch(e: ShelfEntry, body: Record<string, unknown>, msg?: string) {
    try {
      await api.patch(`/api/bookshelf/${e.id}`, body)
      if (msg) toast.success(msg)
      onChange()
    } catch (err) {
      toast.error((err as Error).message)
    }
  }
  async function remove(e: ShelfEntry) {
    await api.del(`/api/bookshelf/${e.id}`)
    toast.info(`Removed “${e.book.title}”.`)
    onChange()
  }

  if (!entries.length) {
    const copy: Record<ShelfStatus, string> = {
      reading: 'Nothing in progress. Pick something from your Want to Read shelf.',
      want_to_read: 'Save books you’d like to read from recommendations or search.',
      read: 'Books you finish will collect here.',
      abandoned: 'Books you’ve paused or put down live here.',
    }
    return <EmptyState icon={<BookOpen className="h-6 w-6" />} title={`No books in “${SHELF_LABELS[status]}”`} action={<Link to="/for-you" className="btn-outline">Find something to read</Link>}>{copy[status]}</EmptyState>
  }

  return (
    <ul className="space-y-4">
      {entries.map((e) => (
        <li key={e.id} className="card p-4">
          <BookRow book={e.book} right={
            <div className="flex items-center gap-2">
              <label className="sr-only" htmlFor={`st-${e.id}`}>Status</label>
              <select id={`st-${e.id}`} className="input w-auto py-1.5" value={e.status} onChange={(ev) => patch(e, { status: ev.target.value }, `Moved to ${SHELF_LABELS[ev.target.value]}.`)}>
                {Object.entries(SHELF_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
              <button className="btn-ghost btn-sm" onClick={() => remove(e)} aria-label={`Remove ${e.book.title} from shelf`}><Trash2 className="h-4 w-4" /></button>
            </div>
          } />
          {(e.status === 'reading' || e.status === 'abandoned') && (
            <div className="mt-4 border-t border-line pt-3">
              {e.total_pages ? (
                <>
                  <div className="h-2 overflow-hidden rounded-full bg-parchment" role="progressbar" aria-valuenow={e.percent ?? 0} aria-valuemin={0} aria-valuemax={100} aria-label={`Progress in ${e.book.title}`}>
                    <div className="h-full bg-forest" style={{ width: `${e.percent ?? 0}%` }} />
                  </div>
                  <p className="mt-1 text-xs text-muted">{e.pages_read} of {e.total_pages} pages · {e.percent}%</p>
                </>
              ) : <p className="text-xs text-muted">{e.pages_read} pages read · total page count unknown, so no percentage is shown.</p>}
              <form className="mt-2 flex flex-wrap items-center gap-2" onSubmit={(ev) => { ev.preventDefault(); const n = Number(pages[e.id]); if (n >= 0) patch(e, { pages_read: n }, 'Progress updated.') }}>
                <label htmlFor={`pg-${e.id}`} className="text-sm">I’m on page</label>
                <input id={`pg-${e.id}`} type="number" min={0} max={e.total_pages ?? undefined} className="input w-24 py-1.5" placeholder={String(e.pages_read)} value={pages[e.id] ?? ''} onChange={(ev) => setPages({ ...pages, [e.id]: ev.target.value })} />
                <button className="btn-outline btn-sm">Update</button>
                <button type="button" className="btn-forest btn-sm" onClick={() => patch(e, { status: 'read' }, 'Finished! Nice work.')}>Mark finished</button>
              </form>
            </div>
          )}
          <div className="mt-3 flex flex-wrap gap-4 text-xs text-muted">
            <label className="flex items-center gap-1">Started <input type="date" className="input w-auto py-1 text-xs" value={e.started_on ?? ''} onChange={(ev) => patch(e, { started_on: ev.target.value || null })} /></label>
            {e.status === 'read' && <label className="flex items-center gap-1">Finished <input type="date" className="input w-auto py-1 text-xs" value={e.finished_on ?? ''} onChange={(ev) => patch(e, { finished_on: ev.target.value || null })} /></label>}
            <span>Updated {date(e.updated_at)}</span>
          </div>
        </li>
      ))}
    </ul>
  )
}

function Lists() {
  const toast = useToast()
  const lists = useApi(() => api.get<ReadingList[]>('/api/reading-lists'), [])
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  async function create() {
    try {
      await api.post('/api/reading-lists', { name: name.trim(), description: description.trim() || null })
      setOpen(false)
      setName('')
      setDescription('')
      lists.reload()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }
  async function del(l: ReadingList) {
    if (!confirm(`Delete the list “${l.name}”?`)) return
    await api.del(`/api/reading-lists/${l.id}`)
    lists.reload()
  }
  async function removeBook(l: ReadingList, b: BookSummary) {
    await api.del(`/api/reading-lists/${l.id}/items/${b.id}`)
    lists.reload()
  }

  return (
    <div>
      <button className="btn-primary" onClick={() => setOpen(true)}><ListPlus className="h-4 w-4" aria-hidden />New list</button>
      <div className="mt-6 space-y-6">
        {lists.loading ? <Spinner /> : lists.data?.length === 0 ? <EmptyState title="No custom lists">Group books however you like: “Summer reads”, “For my exam”… Add books from any book page.</EmptyState>
          : lists.data?.map((l) => (
            <section key={l.id} className="card p-5">
              <div className="flex items-start justify-between gap-3">
                <div><h3 className="text-lg font-semibold">{l.name}</h3>{l.description && <p className="text-sm text-muted">{l.description}</p>}</div>
                <button className="btn-ghost btn-sm" onClick={() => del(l)}><Trash2 className="h-4 w-4" aria-hidden />Delete list</button>
              </div>
              {l.books.length === 0 ? <p className="mt-3 text-sm text-muted">Empty. Use “Add to list” on a book page.</p> : (
                <div className="mt-4 flex gap-4 overflow-x-auto pb-2">
                  {l.books.map((b) => (
                    <div key={b.id} className="relative w-24 shrink-0">
                      <Link to={`/books/${b.id}`}><BookCover title={b.title} authors={b.authors} url={b.cover_url} size="sm" /></Link>
                      <p className="mt-1 text-xs line-clamp-2">{b.title}</p>
                      <button onClick={() => removeBook(l, b)} aria-label={`Remove ${b.title} from ${l.name}`} className="absolute -right-1 -top-1 rounded-full bg-paper p-1 shadow"><X className="h-3 w-3" /></button>
                    </div>
                  ))}
                </div>
              )}
            </section>
          ))}
      </div>
      <Modal open={open} onClose={() => setOpen(false)} title="New reading list" footer={<><button className="btn-ghost" onClick={() => setOpen(false)}>Cancel</button><button className="btn-primary" disabled={!name.trim()} onClick={create}>Create</button></>}>
        <div className="space-y-3">
          <div><label className="label" htmlFor="list-name">Name</label><input id="list-name" className="input" maxLength={80} value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div><label className="label" htmlFor="list-desc">Description (optional)</label><input id="list-desc" className="input" maxLength={300} value={description} onChange={(e) => setDescription(e.target.value)} /></div>
        </div>
      </Modal>
    </div>
  )
}
