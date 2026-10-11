import { Bot, MessageSquarePlus, Send, Trash2, User as UserIcon } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { BookCard } from '../components/books'
import { ComparisonTable } from '../components/ComparisonTable'
import { DealCard, PriceEstimateCard } from '../components/marketplace'
import { Spinner } from '../components/ui'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import type { AssistantPayload, AssistantReply, ComparisonData, UsedSearchResult } from '../types'

interface Msg { id: string; role: 'user' | 'assistant'; content: string; reply?: AssistantReply }

const STARTERS = [
  'What should I read next?',
  'Suggest a book for a beginner in machine learning',
  'Compare Deep Work and Atomic Habits for a busy student',
  'Help me find a used copy of Atomic Habits under ₹250',
  'Find books similar to The Alchemist',
  'Create a reading plan for The Little Prince over 7 days',
]

export default function Assistant() {
  const { user } = useAuth()
  const toast = useToast()
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [context, setContext] = useState<Record<string, unknown> | null>(null)
  const convs = useApi(() => api.get<{ id: number; title: string; updated_at: string; messages: number }[]>('/api/assistant/conversations'), [user?.id, conversationId], !!user)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => { endRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'end' }) }, [messages, busy])

  async function send(text: string, e?: FormEvent) {
    e?.preventDefault()
    const message = text.trim()
    if (!message || busy) return
    setInput('')
    setMessages((m) => [...m, { id: crypto.randomUUID(), role: 'user', content: message }])
    setBusy(true)
    try {
      const r = await api.post<{ conversation_id: number | null; reply: AssistantReply; context: Record<string, unknown> | null }>(
        '/api/assistant/chat', { message, conversation_id: conversationId, context: user ? null : context })
      setConversationId(r.conversation_id)
      setContext(r.context)
      setMessages((m) => [...m, { id: crypto.randomUUID(), role: 'assistant', content: r.reply.text, reply: r.reply }])
    } catch (err) {
      setMessages((m) => [...m, { id: crypto.randomUUID(), role: 'assistant', content: `Sorry — ${(err as Error).message}` }])
    } finally {
      setBusy(false)
    }
  }

  async function openConversation(id: number) {
    const c = await api.get<{ id: number; messages: { id: number; role: 'user' | 'assistant'; content: string; payload: AssistantReply }[] }>(`/api/assistant/conversations/${id}`)
    setConversationId(c.id)
    setMessages(c.messages.map((m) => ({ id: String(m.id), role: m.role, content: m.content, reply: m.role === 'assistant' && m.payload?.payloads ? { ...m.payload, text: m.content } : undefined })))
  }

  function newChat() {
    setConversationId(null)
    setContext(null)
    setMessages([])
  }

  async function remove(id: number) {
    await api.del(`/api/assistant/conversations/${id}`)
    if (id === conversationId) newChat()
    convs.reload()
  }

  async function clearAll() {
    if (!confirm('Delete all saved conversations?')) return
    await api.del('/api/assistant/conversations')
    newChat()
    convs.reload()
    toast.info('Conversation history cleared.')
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[240px_1fr]">
      <aside className="space-y-4">
        <button className="btn-primary w-full" onClick={newChat}><MessageSquarePlus className="h-4 w-4" aria-hidden />New chat</button>
        {user ? (
          <div className="card p-3">
            <div className="mb-2 flex items-center justify-between"><p className="text-sm font-semibold">Saved chats</p>
              {!!convs.data?.length && <button className="text-xs text-rust hover:underline" onClick={clearAll}>Clear all</button>}</div>
            {convs.data?.length ? (
              <ul className="space-y-1">
                {convs.data.map((c) => (
                  <li key={c.id} className={`group flex items-center gap-1 rounded-lg ${c.id === conversationId ? 'bg-parchment' : 'hover:bg-parchment'}`}>
                    <button className="flex-1 truncate px-2 py-1.5 text-left text-sm" onClick={() => openConversation(c.id)} title={c.title}>{c.title}</button>
                    <button className="p-1 opacity-60 hover:opacity-100" aria-label={`Delete conversation ${c.title}`} onClick={() => remove(c.id)}><Trash2 className="h-3.5 w-3.5" /></button>
                  </li>
                ))}
              </ul>
            ) : <p className="text-xs text-muted">No saved chats yet.</p>}
          </div>
        ) : <p className="text-xs text-muted"><Link to="/login?next=/assistant" className="link">Log in</Link> to save chats and let the assistant manage your shelf and plans.</p>}
      </aside>

      <section className="card flex min-h-[70vh] flex-col" aria-label="Chat with the reading assistant">
        <div className="flex-1 space-y-6 overflow-y-auto p-4 sm:p-6" aria-live="polite">
          {messages.length === 0 && (
            <div className="py-8 text-center">
              <Bot className="mx-auto h-10 w-10 text-gold-dark" aria-hidden />
              <h1 className="mt-3 text-2xl font-semibold">Your reading assistant</h1>
              <p className="mx-auto mt-1 max-w-md text-sm text-muted">Answers come from the catalogue, recommendation engine and marketplace, so books and prices are real records.</p>
              <div className="mx-auto mt-6 grid max-w-2xl gap-2 sm:grid-cols-2">
                {STARTERS.map((s) => <button key={s} className="rounded-xl border border-line bg-white px-3 py-2 text-left text-sm hover:border-ink-soft" onClick={() => send(s)}>{s}</button>)}
              </div>
            </div>
          )}
          {messages.map((m) => (
            <div key={m.id} className={`flex gap-3 ${m.role === 'user' ? 'justify-end' : ''}`}>
              {m.role === 'assistant' && <span className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-ink text-gold"><Bot className="h-4 w-4" aria-hidden /></span>}
              <div className={`min-w-0 ${m.role === 'user' ? 'max-w-[80%] rounded-2xl rounded-tr-sm bg-ink px-4 py-2 text-paper' : 'flex-1'}`}>
                <p className={m.role === 'assistant' ? 'text-ink' : ''}>{m.content}</p>
                {m.reply && <ReplyPayloads reply={m.reply} onSuggest={(s) => send(s)} />}
              </div>
              {m.role === 'user' && <span className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gold-soft text-gold-dark"><UserIcon className="h-4 w-4" aria-hidden /></span>}
            </div>
          ))}
          {busy && <div className="pl-11"><Spinner label="Thinking" /></div>}
          <div ref={endRef} />
        </div>
        <form onSubmit={(e) => send(input, e)} className="flex gap-2 border-t border-line p-3">
          <label htmlFor="chat-input" className="sr-only">Message</label>
          <input id="chat-input" className="input" value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask about books, prices or plans…" maxLength={1000} disabled={busy} />
          <button className="btn-primary" disabled={busy || !input.trim()} aria-label="Send message"><Send className="h-4 w-4" /></button>
        </form>
      </section>
    </div>
  )
}

function ReplyPayloads({ reply, onSuggest }: { reply: AssistantReply; onSuggest: (s: string) => void }) {
  return (
    <div className="mt-3 space-y-4">
      {reply.payloads.map((p, i) => <Payload key={i} p={p} />)}
      <div className="flex flex-wrap items-center gap-2">
        {reply.suggestions.map((s) => <button key={s} className="chip hover:border-ink-soft" onClick={() => onSuggest(s)}>{s}</button>)}
      </div>
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
