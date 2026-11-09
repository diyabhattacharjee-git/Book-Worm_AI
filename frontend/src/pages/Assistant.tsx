import { Bot, ChevronDown, MessageSquarePlus, RotateCcw, Send, Trash2, User as UserIcon } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Link } from 'react-router'
import { BookCard } from '../components/books'
import { ComparisonTable } from '../components/ComparisonTable'
import { DealCard, PriceEstimateCard } from '../components/marketplace'
import { CharCounter, Skeleton, Spinner } from '../components/ui'
import { useAuth } from '../contexts/AuthContext'
import { useConfirm } from '../contexts/ConfirmContext'
import { useToast } from '../contexts/ToastContext'
import { TTL, queryKey, useGet } from '../hooks/useApi'
import { ApiError, api } from '../services/api'
import { invalidate, optimistic } from '../services/queryCache'
import type { AssistantPayload, AssistantReply, ComparisonData, UsedSearchResult } from '../types'

interface Msg { id: string; role: 'user' | 'assistant'; content: string; reply?: AssistantReply; failed?: boolean }
interface ConversationRow { id: number; title: string; updated_at: string; messages: number }
interface ChatResponse { conversation_id: number | null; reply: AssistantReply; context: Record<string, unknown> | null }

const CONVERSATIONS = '/api/assistant/conversations'
const MESSAGE_MAX = 1000
const NEAR_BOTTOM_PX = 200
const COMPOSER_MAX_HEIGHT_PX = 160

const STARTERS = [
  'What should I read next?',
  'Suggest a book for a beginner in machine learning',
  'Compare Deep Work and Atomic Habits for a busy student',
  'Help me find a used copy of Atomic Habits under ₹250',
  'Find books similar to The Alchemist',
  'Create a reading plan for The Little Prince over 7 days',
]

function isNearBottom(el: HTMLElement | null): boolean {
  return !el || el.scrollTop + el.clientHeight >= el.scrollHeight - NEAR_BOTTOM_PX
}

export default function Assistant() {
  const { user } = useAuth()
  const toast = useToast()
  const confirm = useConfirm()
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [context, setContext] = useState<Record<string, unknown> | null>(null)
  const [opening, setOpening] = useState<number | null>(null)
  const [chatsOpen, setChatsOpen] = useState(false)
  const convs = useGet<ConversationRow[]>(user ? CONVERSATIONS : null, undefined, { userId: user?.id, ttl: TTL.medium })
  const scrollRef = useRef<HTMLDivElement>(null)
  const composerRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const sendingRef = useRef(false)
  const followRef = useRef(false)

  useEffect(() => () => abortRef.current?.abort(), [])

  // Follow the conversation only if the reader is already at the end of it; never pull them away from history.
  useEffect(() => {
    if (!followRef.current) return
    followRef.current = false
    const smooth = !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    const el = scrollRef.current
    el?.scrollTo?.({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  }, [messages, busy])

  useEffect(() => {
    const el = composerRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, COMPOSER_MAX_HEIGHT_PX)}px`
  }, [input])

  async function deliver(text: string, userMsgId: string) {
    if (sendingRef.current) return
    sendingRef.current = true
    setBusy(true)
    const controller = new AbortController()
    abortRef.current = controller
    const startedNew = conversationId === null
    try {
      const r = await api.post<ChatResponse>('/api/assistant/chat', { message: text, conversation_id: conversationId, context: user ? null : context }, { signal: controller.signal })
      setConversationId(r.conversation_id)
      setContext(r.context)
      followRef.current = isNearBottom(scrollRef.current)
      setMessages((m) => [...m.map((x) => (x.id === userMsgId ? { ...x, failed: false } : x)), { id: crypto.randomUUID(), role: 'assistant', content: r.reply.text, reply: r.reply }])
      if (user && startedNew) invalidate(CONVERSATIONS)
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      setMessages((m) => m.map((x) => (x.id === userMsgId ? { ...x, failed: true } : x)))
      const wait = err instanceof ApiError && err.retryAfter ? ` You can try again in about ${err.retryAfter} seconds.` : ''
      toast.error(`${(err as Error).message}${wait}`)
    } finally {
      sendingRef.current = false
      setBusy(false)
    }
  }

  function send(text: string, e?: FormEvent) {
    e?.preventDefault()
    const message = text.trim()
    if (!message || message.length > MESSAGE_MAX || sendingRef.current) return
    setInput('')
    const id = crypto.randomUUID()
    followRef.current = true
    setMessages((m) => [...m, { id, role: 'user', content: message }])
    void deliver(message, id)
  }

  function retry(m: Msg) {
    if (sendingRef.current) return
    setMessages((all) => all.map((x) => (x.id === m.id ? { ...x, failed: false } : x)))
    void deliver(m.content, m.id)
  }

  function onComposerKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      send(input)
    }
  }

  async function openConversation(id: number) {
    if (id === conversationId || opening !== null) return
    abortRef.current?.abort()
    setOpening(id)
    try {
      const c = await api.get<{ id: number; messages: { id: number; role: 'user' | 'assistant'; content: string; payload: AssistantReply }[] }>(`${CONVERSATIONS}/${id}`)
      setConversationId(c.id)
      setMessages(c.messages.map((m) => ({ id: String(m.id), role: m.role, content: m.content, reply: m.role === 'assistant' && m.payload?.payloads ? { ...m.payload, text: m.content } : undefined })))
      setChatsOpen(false)
      if (scrollRef.current) scrollRef.current.scrollTop = 0
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setOpening(null)
    }
  }

  function newChat() {
    abortRef.current?.abort()
    setConversationId(null)
    setContext(null)
    setMessages([])
    setInput('')
    composerRef.current?.focus()
  }

  async function remove(id: number) {
    try {
      await optimistic<ConversationRow[], void>(queryKey(CONVERSATIONS, undefined, user?.id), (rows) => rows.filter((c) => c.id !== id), () => api.del(`${CONVERSATIONS}/${id}`))
      if (id === conversationId) newChat()
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  async function clearAll() {
    if (!await confirm({ title: 'Delete all saved conversations?', message: 'This can’t be undone.', confirmLabel: 'Delete all', danger: true })) return
    try {
      await optimistic<ConversationRow[], void>(queryKey(CONVERSATIONS, undefined, user?.id), () => [], () => api.del(CONVERSATIONS))
      newChat()
      toast.info('Conversation history cleared.')
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  const tooLong = input.length > MESSAGE_MAX

  return (
    <div className="grid min-h-0 flex-1 grid-rows-[auto_minmax(0,1fr)] gap-3 lg:grid-cols-[240px_minmax(0,1fr)] lg:grid-rows-[minmax(0,1fr)] lg:gap-6">
      <aside className="space-y-3 lg:self-start">
        <button className="btn-primary w-full" onClick={newChat}><MessageSquarePlus className="h-4 w-4" aria-hidden />New chat</button>
        {user ? (
          <div className="card p-3">
            <div className="flex items-center justify-between gap-2">
              <button className="flex flex-1 items-center gap-1 text-left text-sm font-semibold lg:pointer-events-none" onClick={() => setChatsOpen((o) => !o)} aria-expanded={chatsOpen}>
                Saved chats{convs.data?.length ? <span className="font-normal text-muted"> ({convs.data.length})</span> : null}
                <ChevronDown className={`h-4 w-4 transition-transform lg:hidden ${chatsOpen ? 'rotate-180' : ''}`} aria-hidden />
              </button>
              {!!convs.data?.length && <button className="text-xs text-rust hover:underline" onClick={clearAll}>Clear all</button>}
            </div>
            <div className={`${chatsOpen ? 'block' : 'hidden'} mt-2 lg:block`}>
              {convs.loading ? <div className="space-y-2"><Skeleton className="h-7" /><Skeleton className="h-7" /></div>
                : convs.error ? <p className="text-xs text-rust">{convs.error.message}</p>
                  : convs.data?.length ? (
                    <ul className="max-h-[25dvh] space-y-1 overflow-y-auto overscroll-contain lg:max-h-[calc(100dvh-14rem)]">
                      {convs.data.map((c) => (
                        <li key={c.id} className={`group flex items-center gap-1 rounded-lg ${c.id === conversationId ? 'bg-parchment' : 'hover:bg-parchment'}`}>
                          <button className="min-w-0 flex-1 truncate px-2 py-1.5 text-left text-sm disabled:opacity-60" disabled={opening === c.id} onClick={() => openConversation(c.id)} title={c.title}>{c.title}</button>
                          <button className="p-1 opacity-60 hover:opacity-100" aria-label={`Delete conversation ${c.title}`} onClick={() => remove(c.id)}><Trash2 className="h-3.5 w-3.5" /></button>
                        </li>
                      ))}
                    </ul>
                  ) : <p className="text-xs text-muted">No saved chats yet.</p>}
            </div>
          </div>
        ) : <p className="text-xs text-muted"><Link to="/login?next=/assistant" className="link">Log in</Link> to save chats and let the assistant manage your shelf and plans.</p>}
      </aside>

      <section className="card flex min-h-0 min-w-0 flex-col" aria-label="Chat with the reading assistant">
        <div ref={scrollRef} tabIndex={0} className="min-h-0 flex-1 space-y-6 overflow-y-auto overscroll-contain p-4 sm:p-6" aria-live="polite" aria-label="Conversation">
          {messages.length === 0 && (
            <div className="py-8 text-center">
              <Bot className="mx-auto h-10 w-10 text-gold-dark" aria-hidden />
              <h1 className="mt-3 text-2xl font-semibold">Your reading assistant</h1>
              <p className="mx-auto mt-1 max-w-md text-sm text-muted">Ask about any book, get suggestions, compare titles or find a used copy. Books and prices shown come from real records.</p>
              <div className="mx-auto mt-6 grid max-w-2xl gap-2 sm:grid-cols-2">
                {STARTERS.map((s) => <button key={s} className="rounded-xl border border-line bg-white px-3 py-2 text-left text-sm transition-colors hover:border-ink-soft" onClick={() => send(s)} disabled={busy}>{s}</button>)}
              </div>
            </div>
          )}
          {messages.map((m) => (
            <div key={m.id} className={`flex gap-3 ${m.role === 'user' ? 'justify-end' : ''}`}>
              {m.role === 'assistant' && <span className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-ink text-gold"><Bot className="h-4 w-4" aria-hidden /></span>}
              <div className={`min-w-0 ${m.role === 'user' ? 'max-w-[80%]' : 'flex-1'}`}>
                <div className={m.role === 'user' ? `rounded-2xl rounded-tr-sm px-4 py-2 text-paper ${m.failed ? 'bg-rust' : 'bg-ink'}` : ''}>
                  <p className={`user-text ${m.role === 'assistant' ? 'text-ink' : ''}`}>{m.content}</p>
                </div>
                {m.failed && (
                  <button className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-rust hover:underline disabled:opacity-60" onClick={() => retry(m)} disabled={busy}>
                    <RotateCcw className="h-3 w-3" aria-hidden />Not sent. Try again
                  </button>
                )}
                {m.reply && <ReplyPayloads reply={m.reply} disabled={busy} onSuggest={(s) => send(s)} />}
              </div>
              {m.role === 'user' && <span className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gold-soft text-gold-dark"><UserIcon className="h-4 w-4" aria-hidden /></span>}
            </div>
          ))}
          {busy && <div className="pl-11"><Spinner label="Thinking" /></div>}
        </div>
        <form onSubmit={(e) => send(input, e)} className="shrink-0 rounded-b-2xl border-t border-line bg-paper p-3">
          <div className="flex items-end gap-2">
            <label htmlFor="chat-input" className="sr-only">Message</label>
            <textarea id="chat-input" ref={composerRef} rows={1} className="input resize-none" value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={onComposerKey}
              placeholder="Ask about books, prices or plans…" aria-invalid={tooLong} aria-describedby="chat-counter" />
            <button className="btn-primary" disabled={busy || !input.trim() || tooLong} aria-label="Send message"><Send className="h-4 w-4" /></button>
          </div>
          <div className="mt-1 flex items-center justify-between gap-3 text-xs">
            <span className="text-muted">Enter to send · Shift+Enter for a new line</span>
            <CharCounter id="chat-counter" value={input.length} max={MESSAGE_MAX} warnAt={0.8} />
          </div>
        </form>
      </section>
    </div>
  )
}

function ReplyPayloads({ reply, onSuggest, disabled }: { reply: AssistantReply; onSuggest: (s: string) => void; disabled: boolean }) {
  return (
    <div className="mt-3 space-y-4">
      {reply.payloads.map((p, i) => <Payload key={i} p={p} />)}
      {reply.suggestions.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          {reply.suggestions.map((s) => <button key={s} className="chip hover:border-ink-soft disabled:opacity-60" disabled={disabled} onClick={() => onSuggest(s)}>{s}</button>)}
        </div>
      )}
    </div>
  )
}

function Payload({ p }: { p: AssistantPayload }) {
  if (p.type === 'books' && p.items?.length) {
    return (
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-6">
        {p.items.map((it) => <BookCard key={it.book.id} book={it.book} why={it.why ?? undefined} />)}
      </div>
    )
  }
  if (p.type === 'comparison' && p.data) return <ComparisonTable data={p.data as ComparisonData} compact />
  if (p.type === 'deals' && p.data) {
    const d = p.data as UsedSearchResult
    return (
      <div className="space-y-3">
        {d.estimate && d.deals.length > 0 && <PriceEstimateCard estimate={d.estimate} />}
        {d.deals.slice(0, 3).map((deal, i) => <DealCard key={deal.listing.uid} deal={deal} rank={i + 1} />)}
        {d.deals.length > 3 && <Link to={`/marketplace/find?q=${encodeURIComponent(String(d.params?.raw_query ?? d.book?.title ?? ''))}`} className="link text-sm">See all {d.deals.length} options</Link>}
      </div>
    )
  }
  if (p.type === 'plan' && p.plan_id) return <Link to="/plans" className="btn-outline btn-sm">Open your reading plan</Link>
  if (p.type === 'action' && p.action === 'save') return <Link to="/shelf" className="btn-outline btn-sm">View your shelf</Link>
  return null
}
