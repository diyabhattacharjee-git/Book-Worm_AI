import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RequireAuth } from '../components/guards'
import { AuthProvider } from '../contexts/AuthContext'
import { ConfirmProvider } from '../contexts/ConfirmContext'
import { ToastProvider } from '../contexts/ToastContext'
import Assistant from '../pages/Assistant'
import BookDetail from '../pages/BookDetail'
import Discover from '../pages/Discover'
import SellBook from '../pages/SellBook'
import SmartSearch from '../pages/SmartSearch'
import Todos from '../pages/Todos'
import { clearCache } from '../services/queryCache'
import { REVIEW_MAX_LENGTH } from '../utils/validation'

const USER = { id: 1, email: 'a@b.com', username: 'ana', display_name: 'Ana', role: 'user', is_seller: false, location_city: null, preferences: {} }

function json(status: number, body: unknown) {
  return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

type Handler = (url: string, method: string, body: unknown) => Response | undefined

function server(handler: Handler, user: unknown = USER) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url.endsWith('/api/auth/session')) return json(200, { user })
    if (url.includes('/api/ebay/status')) return json(200, { market_check: false, seller_tools: false, connected: false, test_environment: false, marketplace: 'EBAY_US', currency: 'USD', publications: [] })
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
    return handler(url, method, body) ?? json(404, { detail: `unhandled ${method} ${url}` })
  })
}

function show(path: string, route: string, element: ReactNode) {
  const router = createMemoryRouter([{ path: route, element }], { initialEntries: [path] })
  render(<ToastProvider><ConfirmProvider><AuthProvider><RouterProvider router={router} /></AuthProvider></ConfirmProvider></ToastProvider>)
}

const calls = (spy: ReturnType<typeof server>, fragment: string, method = 'GET') =>
  spy.mock.calls.filter(([u, i]) => String(u).includes(fragment) && (i?.method ?? 'GET') === method).length

beforeEach(() => {
  vi.restoreAllMocks()
  clearCache()
  HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) { this.removeAttribute('open') }
})

const task = (id: number, title: string, completed = false) => ({ id, title, notes: null, due_date: null, completed, completed_at: null, created_at: '2026-11-09T10:00:00Z', updated_at: '2026-11-09T10:00:00Z' })

describe('To-do list', () => {
  it('adds a task straight away and swaps in the saved one', async () => {
    const spy = server((url, method, body) => {
      if (url.endsWith('/api/todos') && method === 'GET') return json(200, [])
      if (url.endsWith('/api/todos') && method === 'POST') return json(201, task(7, (body as { title: string }).title))
    })
    show('/todos', '/todos', <RequireAuth><Todos /></RequireAuth>)
    const user = userEvent.setup()
    await screen.findByText('Your list is empty')
    await user.type(screen.getByLabelText('New task'), 'Finish chapter 3')
    await user.click(screen.getByRole('button', { name: 'Add' }))
    expect(await screen.findByText('Finish chapter 3')).toBeInTheDocument()
    expect(calls(spy, '/api/todos', 'POST')).toBe(1)
    expect(calls(spy, '/api/todos')).toBe(1)
  })

  it('refuses a duplicate without calling the server', async () => {
    const spy = server((_url, method) => (method === 'GET' ? json(200, [task(1, 'Read Dune')]) : undefined))
    show('/todos', '/todos', <Todos />)
    const user = userEvent.setup()
    await screen.findByText('Read Dune')
    await user.type(screen.getByLabelText('New task'), '  read   dune ')
    await user.click(screen.getByRole('button', { name: 'Add' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('already have this task')
    expect(calls(spy, '/api/todos', 'POST')).toBe(0)
  })

  it('rolls back a task the server rejects and gives the text back', async () => {
    server((_url, method) => {
      if (method === 'GET') return json(200, [])
      if (method === 'POST') return json(500, { detail: 'Could not save' })
    })
    show('/todos', '/todos', <Todos />)
    const user = userEvent.setup()
    await screen.findByText('Your list is empty')
    await user.type(screen.getByLabelText('New task'), 'Lost task')
    await user.click(screen.getByRole('button', { name: 'Add' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not save')
    expect(screen.getByLabelText('New task')).toHaveValue('Lost task')
  })

  it('moves a ticked task to Finished and undoes it on failure', async () => {
    let fail = false
    let stored = task(1, 'Read Dune')
    server((_url, method, body) => {
      if (method === 'GET') return json(200, [stored])
      if (method === 'PATCH') {
        if (fail) return json(500, { detail: 'nope' })
        stored = { ...stored, ...(body as object) }
        return json(200, stored)
      }
    })
    show('/todos', '/todos', <Todos />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('checkbox', { name: /mark as done/i }))
    await waitFor(() => expect(screen.queryByText('Read Dune')).not.toBeInTheDocument())
    await user.click(screen.getByRole('tab', { name: /finished/i }))
    fail = true
    await user.click(await screen.findByRole('checkbox', { name: /not done/i }))
    await waitFor(() => expect(screen.getByRole('checkbox', { name: /not done/i })).toBeInTheDocument())
  })
})

const BOOK = { id: 5, title: 'Dune', subtitle: null, authors: ['Frank Herbert'], cover_url: null, genres: [], first_published_year: 1965, page_count: 500, language: 'en', ratings: { app_average: null, app_count: 0, external_average: null, external_count: null, external_source: null }, is_sample: false, used_listing_count: 0, lowest_used_price: null, lowest_used_currency: null, description: null, publisher: null, series: null, subjects: [], isbn13: null, editions: [], source: 'open_library', metadata_fetched_at: null, external_links: [], difficulty_signal: null }

function bookServer(extra?: Handler) {
  return server((url, method, body) => {
    const custom = extra?.(url, method, body)
    if (custom) return custom
    if (url.includes('/reviews')) return json(200, { items: [], total: 0, my_review: null, distribution: {} })
    if (url.includes('/similar')) return json(200, [])
    if (url.includes('/api/bookshelf')) return json(200, { items: [] })
    if (url.endsWith('/api/books/5')) return json(200, BOOK)
  })
}

describe('Review form', () => {
  it('counts characters and blocks a review over the limit', async () => {
    const spy = bookServer()
    show('/books/5', '/books/:id', <BookDetail />)
    const box = await screen.findByLabelText(/your review/i) as HTMLTextAreaElement
    fireEvent.click(screen.getByRole('radio', { name: '4 stars' }))
    fireEvent.change(box, { target: { value: 'x'.repeat(REVIEW_MAX_LENGTH + 12) } })
    expect(screen.getByText(`${(REVIEW_MAX_LENGTH + 12).toLocaleString()} / ${REVIEW_MAX_LENGTH.toLocaleString()}`)).toBeInTheDocument()
    expect(screen.getByText(/12 characters over the limit/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Post' })).toBeDisabled()
    expect(box).not.toHaveAttribute('maxLength')
    expect(calls(spy, '/reviews', 'POST')).toBe(0)
  })

  it('posting shows the review at once without reloading the rest of the page', async () => {
    const saved = { id: 9, book_id: 5, user_id: 1, user_display_name: 'Ana', rating: 4, body: 'Great', helpful_count: 0, status: 'visible', created_at: 'x', updated_at: '2026-11-09T10:00:00Z', is_mine: true, voted_helpful: false }
    let posted = false
    const spy = bookServer((url, method) => {
      if (!url.includes('/reviews')) return undefined
      if (method === 'POST') { posted = true; return json(201, saved) }
      return posted ? json(200, { items: [saved], total: 1, my_review: saved, distribution: { 4: 1 } }) : undefined
    })
    show('/books/5', '/books/:id', <BookDetail />)
    const box = await screen.findByLabelText(/your review/i)
    fireEvent.click(screen.getByRole('radio', { name: '4 stars' }))
    fireEvent.change(box, { target: { value: 'Great' } })
    fireEvent.click(screen.getByRole('button', { name: 'Post' }))
    expect(await screen.findByText('Your rating')).toBeInTheDocument()
    expect(calls(spy, '/similar')).toBe(1)
    expect(calls(spy, '/api/bookshelf')).toBe(1)
  })

  it('restores the draft when posting fails', async () => {
    bookServer((url, method) => (url.includes('/reviews') && method === 'POST' ? json(500, { detail: 'Server trouble' }) : undefined))
    show('/books/5', '/books/:id', <BookDetail />)
    const box = await screen.findByLabelText(/your review/i)
    fireEvent.click(screen.getByRole('radio', { name: '5 stars' }))
    fireEvent.change(box, { target: { value: 'Keep this text' } })
    fireEvent.click(screen.getByRole('button', { name: 'Post' }))
    expect(await screen.findByText('Server trouble')).toBeInTheDocument()
    expect(screen.getByLabelText(/your review/i)).toHaveValue('Keep this text')
  })

  it('collapses very long reviews', async () => {
    const long = 'y'.repeat(4000)
    bookServer((url, method) => (url.includes('/reviews') && method === 'GET' ? json(200, { items: [{ id: 3, book_id: 5, user_id: 2, user_display_name: 'Sam', rating: 3, body: long, helpful_count: 0, status: 'visible', created_at: 'x', updated_at: '2026-11-09T10:00:00Z', is_mine: false, voted_helpful: false }], total: 1, my_review: null, distribution: {} }) : undefined))
    show('/books/5', '/books/:id', <BookDetail />)
    await screen.findByText('Sam')
    expect(screen.queryByText(long)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Read more' }))
    expect(screen.getByText(new RegExp(`^${long}`))).toBeInTheDocument()
  })
})

describe('Sell a book', () => {
  it('shows field errors and sends nothing for an empty form', async () => {
    const spy = server(() => undefined)
    show('/sell', '/sell', <SellBook />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Publish listing' }))
    expect(await screen.findByText('Enter the book title.')).toBeInTheDocument()
    expect(screen.getByText('Enter the author.')).toBeInTheDocument()
    expect(screen.getByText('Enter your asking price.')).toBeInTheDocument()
    expect(screen.getByText(/Describe your copy in at least/)).toBeInTheDocument()
    expect(screen.getByText(/Enter your city or area/)).toBeInTheDocument()
    expect(calls(spy, '/api/marketplace/listings', 'POST')).toBe(0)
  })

  it('rejects a bad ISBN and a negative price', async () => {
    const spy = server(() => undefined)
    show('/sell', '/sell', <SellBook />)
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('ISBN'), '9780735211293')
    await user.type(screen.getByLabelText('Asking price *'), '-20')
    await user.click(screen.getByRole('button', { name: 'Publish listing' }))
    expect(await screen.findByText(/That ISBN isn’t valid/)).toBeInTheDocument()
    expect(screen.getByText(/Enter an amount like/)).toBeInTheDocument()
    expect(calls(spy, '/api/marketplace/listings', 'POST')).toBe(0)
  })

  it('maps server errors to their fields and submits once', async () => {
    let n = 0
    let release: () => void = () => undefined
    const gate = new Promise<void>((r) => { release = r })
    vi.restoreAllMocks()
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/auth/session')) return json(200, { user: USER })
      if (url.includes('/api/ebay/status')) return json(200, { market_check: false, seller_tools: false, connected: false, test_environment: false, marketplace: 'EBAY_US', currency: 'USD', publications: [] })
      if (init?.method === 'POST') {
        n += 1
        await gate
        return json(422, { detail: 'Validation failed', errors: [{ field: 'title', message: 'Server says no' }] })
      }
      return json(404, {})
    })
    show('/sell', '/sell', <SellBook />)
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Title *'), 'Dune')
    await user.type(screen.getByLabelText('Author *'), 'Frank Herbert')
    await user.type(screen.getByLabelText('Description of your copy *'), 'A clean paperback copy.')
    await user.type(screen.getByLabelText('Asking price *'), '250')
    await user.type(screen.getByLabelText('City / area *'), 'Pune')
    const publish = screen.getByRole('button', { name: 'Publish listing' })
    await user.dblClick(publish)
    release()
    expect(await screen.findByText('Server says no')).toBeInTheDocument()
    expect(n).toBe(1)
  })
})

describe('Assistant', () => {
  const reply = (text: string) => ({ conversation_id: null, context: { history: [] }, reply: { text, tool: 'chat', routed_by: 'llm', source: 'llm', payloads: [], suggestions: [] } })

  it('sends once, shows the answer and passes context back', async () => {
    const bodies: unknown[] = []
    server((url, method, body) => {
      if (url.includes('/assistant/chat') && method === 'POST') {
        bodies.push(body)
        return json(200, reply(`Answer ${bodies.length}`))
      }
    }, null)
    show('/assistant', '/assistant', <Assistant />)
    const user = userEvent.setup()
    const box = await screen.findByLabelText('Message')
    await user.type(box, 'What is Dune about?{Enter}')
    await screen.findByText('Answer 1')
    await user.type(screen.getByLabelText('Message'), 'Is it long?{Enter}')
    await screen.findByText('Answer 2')
    expect(bodies).toHaveLength(2)
    expect((bodies[1] as { context: unknown }).context).toEqual({ history: [] })
  })

  it('offers a retry after a failure without duplicating the message', async () => {
    let attempt = 0
    server((url, method) => {
      if (url.includes('/assistant/chat') && method === 'POST') {
        attempt += 1
        return attempt === 1 ? new Response(JSON.stringify({ detail: 'The assistant is unavailable right now.' }), { status: 503, headers: { 'Retry-After': '30', 'Content-Type': 'application/json' } }) : json(200, reply('Recovered'))
      }
    }, null)
    show('/assistant', '/assistant', <Assistant />)
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Message'), 'Hello there{Enter}')
    const retry = await screen.findByRole('button', { name: /not sent/i })
    expect(screen.getByRole('alert')).toHaveTextContent('about 30 seconds')
    await user.click(retry)
    await screen.findByText('Recovered')
    const section = screen.getByRole('region', { name: /chat with/i })
    expect(within(section).getAllByText('Hello there')).toHaveLength(1)
    expect(attempt).toBe(2)
  })

  it('scrolls the conversation inside the chat panel and keeps the message box outside it', async () => {
    server(() => undefined, null)
    show('/assistant', '/assistant', <Assistant />)
    const section = await screen.findByRole('region', { name: /chat with/i })
    const conversation = screen.getByLabelText('Conversation')
    expect(conversation.className).toContain('overflow-y-auto')
    expect(conversation.contains(section.querySelector('form'))).toBe(false)
  })

  it('blocks a message over the limit', async () => {
    const spy = server(() => undefined, null)
    show('/assistant', '/assistant', <Assistant />)
    const box = await screen.findByLabelText('Message')
    fireEvent.change(box, { target: { value: 'x'.repeat(1001) } })
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled()
    fireEvent.keyDown(box, { key: 'Enter' })
    expect(calls(spy, '/assistant/chat', 'POST')).toBe(0)
  })
})

describe('Books the catalogue does not hold', () => {
  const book = (id: number, title: string, authors = ['Someone Else'], genres: string[] = []) => ({
    id, title, subtitle: null, authors, cover_url: null, genres, first_published_year: null, page_count: null, language: null,
    ratings: { app_average: null, app_count: 0, external_average: null, external_count: null, external_source: null },
    is_sample: false, used_listing_count: 0, lowest_used_price: null, lowest_used_currency: null,
  })
  const LOOSE = [book(1, 'Deep Work'), book(2, 'Dune'), book(3, 'The Alchemist')]
  const LIVE = '/api/books/external-search'
  const live = { results: [{ title: 'Piranesi', authors: ['Susanna Clarke'], published_year: 2020, isbns: ['9781635577808'], cover_url: null, source: 'google_books', info_url: null, in_catalogue_book_id: null }], errors: [] }

  function discover(items: ReturnType<typeof book>[]) {
    return server((url) => {
      if (url.includes(LIVE)) return json(200, live)
      if (url.includes('/api/books/facets')) return json(200, { genres: [], languages: [], formats: [], year_range: [null, null] })
      if (url.includes('/api/books')) return json(200, { items, total: items.length, page: 1, page_size: 20 })
    }, null)
  }

  function smart(items: ReturnType<typeof book>[]) {
    return server((url, method) => {
      if (url.includes(LIVE)) return json(200, live)
      if (url.includes('/api/books/nl-search') && method === 'POST') return json(200, { query: {}, interpreted_as: [], results: items.map((b) => ({ book: b, score: 1, semantic_similarity: 1, why: [] })), search_backend: 'x', notes: [] })
    }, null)
  }

  it('Discover searches live when the results are only loose matches', async () => {
    discover(LOOSE)
    show('/discover?q=piranesi', '/discover', <Discover />)
    expect(await screen.findByText('Google Books')).toBeInTheDocument()
  })

  it('Discover spends no live search when the title is already there', async () => {
    const spy = discover([book(1, "Harry Potter and the Philosopher's Stone", ['J. K. Rowling'])])
    show('/discover?q=harry%20potter%20philosophers%20stone', '/discover', <Discover />)
    expect(await screen.findByRole('button', { name: /Search Google Books/ })).toBeInTheDocument()
    expect(calls(spy, LIVE)).toBe(0)
  })

  it('Discover treats an author or genre as a match', async () => {
    const spy = discover([book(1, 'Thinking, Fast and Slow', ['Daniel Kahneman'], ['Psychology'])])
    show('/discover?q=kahneman', '/discover', <Discover />)
    await screen.findByRole('button', { name: /Search Google Books/ })
    expect(calls(spy, LIVE)).toBe(0)
  })

  it('Smart Search looks up a book name it does not hold', async () => {
    smart(LOOSE)
    show('/search', '/search', <SmartSearch />)
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Your request'), 'Piranesi')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    expect(await screen.findByText('Google Books')).toBeInTheDocument()
  })

  it('Smart Search does not send a plain-language request to public catalogues by itself', async () => {
    const spy = smart(LOOSE)
    show('/search', '/search', <SmartSearch />)
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Your request'), 'I want a short inspiring book')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    expect(await screen.findByRole('button', { name: /Search Google Books/ })).toBeInTheDocument()
    expect(calls(spy, LIVE)).toBe(0)
  })
})

