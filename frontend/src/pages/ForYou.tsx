import { Bookmark, Info, RefreshCw, Sparkles, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { BookCard, BookGrid } from '../components/books'
import { Badge, BookGridSkeleton, EmptyState, ErrorState, Modal, Notice, PageHeader, StarInput } from '../components/ui'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { useApi, useDebounced } from '../hooks/useApi'
import { api } from '../services/api'
import type { BookSummary, Page, RecommendationItem, RecommendationResponse, User } from '../types'

const SIGNAL_LABEL: Record<string, string> = { content: 'Content similarity', collaborative: 'Similar readers', popularity: 'Popularity', preference: 'Your preferences' }

export default function ForYou() {
  const { user } = useAuth()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const genre = params.get('genre') ?? ''
  const recs = useApi(() => api.get<RecommendationResponse>('/api/recommendations', { limit: 15, genre }), [user?.id, genre])
  const facets = useApi(() => api.get<{ genres: { name: string; slug: string }[] }>('/api/books/facets'), [])
  const [onboarding, setOnboarding] = useState(false)
  const [rating, setRating] = useState<RecommendationItem | null>(null)
  const [hidden, setHidden] = useState<Set<number>>(new Set())
  const [showHow, setShowHow] = useState(false)

  useEffect(() => {
    if (user && params.get('onboarding') === '1') setOnboarding(true)
  }, [user, params])

  async function feedback(item: RecommendationItem, action: 'save' | 'dismiss' | 'not_interested', msg: string) {
    try {
      await api.post('/api/recommendations/feedback', { book_id: item.book.id, action })
      if (action === 'save') await api.post('/api/bookshelf', { book_id: item.book.id, status: 'want_to_read' })
      setHidden((h) => new Set(h).add(item.book.id))
      toast.success(msg)
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function recompute() {
    await api.post('/api/recommendations/recompute')
    setHidden(new Set())
    recs.reload()
    toast.info('Recommendations refreshed.')
  }

  const items = recs.data?.items.filter((i) => !hidden.has(i.book.id)) ?? []

  return (
    <div>
      <PageHeader eyebrow="Recommendations" title={user ? `For you, ${user.display_name}` : 'Popular picks'}
        actions={user && <>
          <button className="btn-outline" onClick={() => setOnboarding(true)}><Sparkles className="h-4 w-4" aria-hidden />{user.preferences.onboarding_completed ? 'Edit preferences' : 'Tell us your tastes'}</button>
          <button className="btn-ghost" onClick={recompute}><RefreshCw className="h-4 w-4" aria-hidden />Refresh</button>
        </>}>
        {user ? 'Every pick comes with the reason it was chosen. Save, dismiss or rate to steer what comes next.'
          : <>These are popular books in the catalogue. <Link to="/login?next=/for-you" className="link">Log in</Link> and rate a few books for personalised picks.</>}
      </PageHeader>

      {recs.data && (
        <div className="mb-6 space-y-3">
          <Notice tone={recs.data.mode === 'personalized' ? 'success' : 'info'} title={recs.data.mode === 'personalized' ? 'Personalised recommendations' : 'Starter recommendations'}>
            {recs.data.mode_label}
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="text-xs">Signals used:</span>
              {recs.data.signals_used.map((s) => <Badge key={s} tone="sky">{SIGNAL_LABEL[s] ?? s}</Badge>)}
              <button className="link ml-2 inline-flex items-center gap-1 text-xs" onClick={() => setShowHow((s) => !s)} aria-expanded={showHow}><Info className="h-3 w-3" aria-hidden />How this works</button>
            </div>
            {showHow && (
              <div className="mt-3 border-t border-current/10 pt-3 text-xs">
                <ul className="list-disc space-y-1 pl-4">{recs.data.how_it_works.map((h) => <li key={h}>{h}</li>)}</ul>
              </div>
            )}
          </Notice>
          {recs.data.notes.map((n) => <Notice key={n} tone="warn">{n}</Notice>)}
          {user && !user.preferences.onboarding_completed && recs.data.mode === 'cold_start' && (
            <Notice title="Want better starter picks?">Answer a few optional questions (genres, authors, length). <button className="link" onClick={() => setOnboarding(true)}>Get started</button> — or just rate a few books.</Notice>
          )}
        </div>
      )}

      <div className="mb-6 flex flex-wrap gap-2" role="group" aria-label="Filter by genre">
        <button className={`chip ${!genre ? 'border-ink bg-ink text-paper' : ''}`} onClick={() => setParams({})}>All</button>
        {facets.data?.genres.slice(0, 14).map((g) => (
          <button key={g.slug} className={`chip ${genre === g.slug ? 'border-ink bg-ink text-paper' : 'hover:border-ink-soft'}`} onClick={() => setParams({ genre: g.slug })}>{g.name}</button>
        ))}
      </div>

      {recs.loading ? <BookGridSkeleton count={10} /> : recs.error ? <ErrorState error={recs.error} onRetry={recs.reload} /> : items.length === 0 ? (
        <EmptyState title="Nothing new to recommend here" action={<Link to="/discover" className="btn-outline">Browse the catalogue</Link>}>
          You’ve seen or shelved everything that matches. Try another genre or import more books.
        </EmptyState>
      ) : (
        <BookGrid>
          {items.map((item) => (
            <BookCard key={item.book.id} book={item.book}
              why={<ul className="space-y-0.5">{item.reasons.map((r) => <li key={r.text}>• {r.text}</li>)}</ul>}
              footer={user && (
                <div className="flex flex-wrap gap-1">
                  <button className="btn-outline btn-sm" onClick={() => feedback(item, 'save', `Saved “${item.book.title}” to Want to Read.`)} title="Save to Want to Read"><Bookmark className="h-3.5 w-3.5" aria-hidden />Save</button>
                  <button className="btn-ghost btn-sm" onClick={() => setRating(item)}>Rate</button>
                  <button className="btn-ghost btn-sm" onClick={() => feedback(item, 'dismiss', 'Dismissed. We’ll adjust your picks.')} aria-label={`Dismiss ${item.book.title}`}><X className="h-3.5 w-3.5" aria-hidden /></button>
                </div>
              )} />
          ))}
        </BookGrid>
      )}

      {rating && <RateDialog item={rating} onClose={(done) => { if (done) setHidden((h) => new Set(h).add(rating.book.id)); setRating(null) }} />}
      {user && onboarding && <Onboarding user={user} onClose={() => { setOnboarding(false); params.delete('onboarding'); setParams(params); recs.reload() }} />}
    </div>
  )
}

function RateDialog({ item, onClose }: { item: RecommendationItem; onClose: (done: boolean) => void }) {
  const toast = useToast()
  const [value, setValue] = useState(0)
  async function save() {
    try {
      await api.post('/api/recommendations/feedback', { book_id: item.book.id, action: 'rate', rating: value })
      toast.success('Rating saved. Your recommendations will adapt.')
      onClose(true)
    } catch (e) {
      toast.error((e as Error).message)
    }
  }
  return (
    <Modal open onClose={() => onClose(false)} title={`Rate “${item.book.title}”`}
      footer={<><button className="btn-ghost" onClick={() => onClose(false)}>Cancel</button><button className="btn-primary" disabled={!value} onClick={save}>Save rating</button></>}>
      <p className="mb-3 text-sm text-muted">Already read it? Your rating helps tune future picks.</p>
      <StarInput value={value} onChange={setValue} />
    </Modal>
  )
}

const THEMES = ['adventure', 'friendship', 'mystery', 'habits', 'money', 'history', 'space', 'love', 'philosophy', 'technology', 'family', 'war', 'identity', 'mythology']
const LANGS = [['en', 'English'], ['hi', 'Hindi'], ['bn', 'Bengali'], ['ta', 'Tamil'], ['es', 'Spanish'], ['fr', 'French']]

function Onboarding({ user, onClose }: { user: User; onClose: () => void }) {
  const toast = useToast()
  const { setUser } = useAuth()
  const p = user.preferences
  const facets = useApi(() => api.get<{ genres: { name: string; slug: string }[] }>('/api/books/facets'), [])
  const [genres, setGenres] = useState<string[]>(p.favorite_genres)
  const [authors, setAuthors] = useState(p.favorite_authors.join(', '))
  const [languages, setLanguages] = useState<string[]>(p.preferred_languages)
  const [themes, setThemes] = useState<string[]>(p.favorite_themes)
  const [topics, setTopics] = useState(p.topics_to_explore.join(', '))
  const [length, setLength] = useState(p.preferred_length ?? 'any')
  const [goal, setGoal] = useState(p.reading_goal_text ?? '')
  const [enjoyed, setEnjoyed] = useState<BookSummary[]>([])
  const [bookQ, setBookQ] = useState('')
  const dq = useDebounced(bookQ)
  const found = useApi(() => api.get<Page<BookSummary>>('/api/books', { q: dq, page_size: 5 }), [dq], dq.length > 1)
  const [busy, setBusy] = useState(false)

  const toggle = (list: string[], set: (v: string[]) => void, v: string) => set(list.includes(v) ? list.filter((x) => x !== v) : [...list, v])
  const split = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean)

  async function save(completed: boolean) {
    setBusy(true)
    try {
      const u = await api.patch<User>('/api/users/me/preferences', {
        favorite_genres: genres, favorite_authors: split(authors), preferred_languages: languages, favorite_themes: themes,
        topics_to_explore: split(topics), preferred_length: length, reading_goal_text: goal.trim() || null,
        enjoyed_book_ids: [...new Set([...p.enjoyed_book_ids, ...enjoyed.map((b) => b.id)])], onboarding_completed: completed,
      })
      setUser(u)
      toast.success('Preferences saved.')
      onClose()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open wide onClose={onClose} title="What do you like to read?"
      footer={<><button className="btn-ghost" onClick={onClose}>Skip for now</button><button className="btn-primary" disabled={busy} onClick={() => save(true)}>Save preferences</button></>}>
      <div className="space-y-6">
        <p className="text-sm text-muted">Everything here is optional and you can change it any time in Settings.</p>
        <fieldset>
          <legend className="label">Favourite genres</legend>
          <div className="flex flex-wrap gap-2">
            {facets.data?.genres.map((g) => (
              <button type="button" key={g.slug} aria-pressed={genres.includes(g.name)} onClick={() => toggle(genres, setGenres, g.name)}
                className={`chip ${genres.includes(g.name) ? 'border-forest bg-forest-soft text-forest-dark' : ''}`}>{g.name}</button>
            ))}
          </div>
        </fieldset>
        <fieldset>
          <legend className="label">Themes you enjoy</legend>
          <div className="flex flex-wrap gap-2">
            {THEMES.map((t) => <button type="button" key={t} aria-pressed={themes.includes(t)} onClick={() => toggle(themes, setThemes, t)} className={`chip ${themes.includes(t) ? 'border-forest bg-forest-soft text-forest-dark' : ''}`}>{t}</button>)}
          </div>
        </fieldset>
        <div className="grid gap-4 sm:grid-cols-2">
          <div><label className="label" htmlFor="ob-authors">Favourite authors (comma-separated)</label><input id="ob-authors" className="input" value={authors} onChange={(e) => setAuthors(e.target.value)} placeholder="e.g. Agatha Christie, Andy Weir" /></div>
          <div><label className="label" htmlFor="ob-topics">Topics to explore</label><input id="ob-topics" className="input" value={topics} onChange={(e) => setTopics(e.target.value)} placeholder="e.g. machine learning, investing" /></div>
          <div>
            <label className="label" htmlFor="ob-length">Preferred length</label>
            <select id="ob-length" className="input" value={length} onChange={(e) => setLength(e.target.value as typeof length)}>
              <option value="any">No preference</option><option value="short">Short (≤ 250 pages)</option><option value="medium">Medium (250–450)</option><option value="long">Long (450+)</option>
            </select>
          </div>
          <div><label className="label" htmlFor="ob-goal">Reading goal</label><input id="ob-goal" className="input" maxLength={200} value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="e.g. learn data science, relax" /></div>
        </div>
        <fieldset>
          <legend className="label">Preferred languages</legend>
          <div className="flex flex-wrap gap-2">
            {LANGS.map(([c, l]) => <button type="button" key={c} aria-pressed={languages.includes(c)} onClick={() => toggle(languages, setLanguages, c)} className={`chip ${languages.includes(c) ? 'border-forest bg-forest-soft text-forest-dark' : ''}`}>{l}</button>)}
          </div>
        </fieldset>
        <div>
          <label className="label" htmlFor="ob-books">Books you’ve enjoyed</label>
          <input id="ob-books" className="input" value={bookQ} onChange={(e) => setBookQ(e.target.value)} placeholder="Search the catalogue" />
          {found.data && dq.length > 1 && (
            <ul className="mt-2 divide-y divide-line rounded-lg border border-line">
              {found.data.items.map((b) => (
                <li key={b.id}><button type="button" className="w-full px-3 py-2 text-left text-sm hover:bg-parchment" onClick={() => { if (!enjoyed.some((x) => x.id === b.id)) setEnjoyed([...enjoyed, b]); setBookQ('') }}>{b.title} <span className="text-muted">· {b.authors.join(', ')}</span></button></li>
              ))}
            </ul>
          )}
          <div className="mt-2 flex flex-wrap gap-2">
            {enjoyed.map((b) => <span key={b.id} className="chip">{b.title}<button type="button" aria-label={`Remove ${b.title}`} onClick={() => setEnjoyed(enjoyed.filter((x) => x.id !== b.id))}><X className="h-3 w-3" /></button></span>)}
            {p.enjoyed_book_ids.length > 0 && <span className="text-xs text-muted">+ {p.enjoyed_book_ids.length} saved earlier</span>}
          </div>
        </div>
      </div>
    </Modal>
  )
}
