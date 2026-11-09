import { CalendarDays, Check, ListTodo, Pencil, Plus, Trash2 } from 'lucide-react'
import { useRef, useState, type FormEvent } from 'react'
import { CharCounter, EmptyState, ErrorState, ListSkeleton, PageHeader, Tabs } from '../components/ui'
import { useAuth } from '../contexts/AuthContext'
import { useConfirm } from '../contexts/ConfirmContext'
import { useToast } from '../contexts/ToastContext'
import { TTL, queryKey, useGet } from '../hooks/useApi'
import { api } from '../services/api'
import { optimistic, setQueryData } from '../services/queryCache'
import type { Todo } from '../types'
import { date } from '../utils/format'
import { TASK_NOTES_MAX, TASK_TITLE_MAX } from '../utils/validation'

const TODOS = '/api/todos'
type Filter = 'active' | 'done' | 'all'

const normalize = (title: string) => title.trim().replace(/\s+/g, ' ').toLocaleLowerCase()

function sortTasks(tasks: Todo[]): Todo[] {
  return [...tasks].sort((a, b) => Number(a.completed) - Number(b.completed) || (b.created_at > a.created_at ? 1 : b.created_at < a.created_at ? -1 : b.id - a.id))
}

export default function Todos() {
  const { user } = useAuth()
  const toast = useToast()
  const confirm = useConfirm()
  const key = queryKey(TODOS, undefined, user?.id)
  const todos = useGet<Todo[]>(TODOS, undefined, { userId: user?.id, ttl: TTL.long })
  const [filter, setFilter] = useState<Filter>('active')
  const [title, setTitle] = useState('')
  const [notes, setNotes] = useState('')
  const [due, setDue] = useState('')
  const [showDetails, setShowDetails] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [pending, setPending] = useState<Set<number>>(new Set())
  const tempId = useRef(-1)

  const tasks = todos.data ?? []
  const activeCount = tasks.filter((t) => !t.completed).length
  const doneCount = tasks.length - activeCount
  const visible = tasks.filter((t) => filter === 'all' || (filter === 'done' ? t.completed : !t.completed))

  const hasDuplicate = (text: string, except?: number) => tasks.some((t) => !t.completed && t.id !== except && normalize(t.title) === normalize(text))

  function setBusy(id: number, on: boolean) {
    setPending((p) => {
      const next = new Set(p)
      if (on) next.add(id)
      else next.delete(id)
      return next
    })
  }

  async function add(e: FormEvent) {
    e.preventDefault()
    const clean = title.trim().replace(/\s+/g, ' ')
    if (!clean) return setFormError('Write what you want to do first.')
    if (clean.length > TASK_TITLE_MAX) return setFormError(`Keep it under ${TASK_TITLE_MAX} characters.`)
    if (notes.length > TASK_NOTES_MAX) return setFormError(`Notes can be up to ${TASK_NOTES_MAX} characters.`)
    if (hasDuplicate(clean)) return setFormError('You already have this task on your list.')
    setFormError(null)
    const id = tempId.current--
    const now = new Date().toISOString()
    const draft: Todo = { id, title: clean, notes: notes.trim() || null, due_date: due || null, completed: false, completed_at: null, created_at: now, updated_at: now }
    const saved = { title, notes, due }
    setTitle('')
    setNotes('')
    setDue('')
    setBusy(id, true)
    try {
      const created = await optimistic<Todo[], Todo>(key, (prev) => sortTasks([draft, ...prev]), () => api.post<Todo>(TODOS, { title: clean, notes: draft.notes, due_date: draft.due_date }))
      setQueryData<Todo[]>(key, (prev) => sortTasks((prev ?? []).map((t) => (t.id === id ? created : t))))
    } catch (err) {
      setTitle(saved.title)
      setNotes(saved.notes)
      setDue(saved.due)
      setFormError((err as Error).message)
    } finally {
      setBusy(id, false)
    }
  }

  async function patch(task: Todo, changes: Partial<Todo>, errorPrefix = '') {
    if (pending.has(task.id) || task.id < 0) return false
    setBusy(task.id, true)
    try {
      const updated = await optimistic<Todo[], Todo>(key, (prev) => sortTasks(prev.map((t) => (t.id === task.id ? { ...t, ...changes } : t))), () => api.patch<Todo>(`${TODOS}/${task.id}`, changes))
      setQueryData<Todo[]>(key, (prev) => sortTasks((prev ?? []).map((t) => (t.id === task.id ? updated : t))))
      return true
    } catch (err) {
      toast.error(`${errorPrefix}${(err as Error).message}`)
      return false
    } finally {
      setBusy(task.id, false)
    }
  }

  async function toggle(task: Todo) {
    await patch(task, { completed: !task.completed, completed_at: task.completed ? null : new Date().toISOString() })
  }

  async function remove(task: Todo) {
    if (pending.has(task.id) || task.id < 0) return
    setBusy(task.id, true)
    try {
      await optimistic<Todo[], void>(key, (prev) => prev.filter((t) => t.id !== task.id), () => api.del(`${TODOS}/${task.id}`))
      toast.info('Task deleted.')
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setBusy(task.id, false)
    }
  }

  async function clearDone() {
    if (!await confirm({ title: `Delete ${doneCount} finished task${doneCount === 1 ? '' : 's'}?`, message: 'They’ll be removed permanently.', confirmLabel: 'Delete', danger: true })) return
    try {
      await optimistic<Todo[], void>(key, (prev) => prev.filter((t) => !t.completed), () => api.del(`${TODOS}/completed`))
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader eyebrow="To-do list" title="What’s next on your reading list">Note the things you don’t want to forget: a chapter to finish, a book to return, a review to write.</PageHeader>

      <form onSubmit={add} className="card space-y-3 p-4 sm:p-5" noValidate>
        <div className="flex flex-col gap-2 sm:flex-row">
          <label htmlFor="todo-title" className="sr-only">New task</label>
          <input id="todo-title" className="input py-2.5" placeholder="Add a task…" value={title} autoComplete="off" aria-invalid={!!formError} aria-describedby={formError ? 'todo-error' : undefined}
            onChange={(e) => { setTitle(e.target.value); setFormError(null) }} />
          <button className="btn-primary sm:w-28" disabled={!title.trim()}><Plus className="h-4 w-4" aria-hidden />Add</button>
        </div>
        {formError && <p id="todo-error" className="text-xs text-rust" role="alert">{formError}</p>}
        {title.length > TASK_TITLE_MAX * 0.8 && <CharCounter value={title.length} max={TASK_TITLE_MAX} warnAt={0.8} />}
        <button type="button" className="text-xs font-medium text-ink-soft hover:text-ink" onClick={() => setShowDetails((s) => !s)} aria-expanded={showDetails}>{showDetails ? 'Hide details' : 'Add a due date or notes'}</button>
        {showDetails && (
          <div className="grid gap-3 sm:grid-cols-[auto_minmax(0,1fr)]">
            <div><label htmlFor="todo-due" className="label">Due date</label><input id="todo-due" type="date" className="input" value={due} onChange={(e) => setDue(e.target.value)} /></div>
            <div>
              <label htmlFor="todo-notes" className="label">Notes</label>
              <textarea id="todo-notes" className="input" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
              <div className="mt-1 text-right"><CharCounter value={notes.length} max={TASK_NOTES_MAX} warnAt={0.8} /></div>
            </div>
          </div>
        )}
      </form>

      <div className="mt-8 flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0 flex-1">
          <Tabs label="Filter tasks" value={filter} onChange={setFilter} tabs={[
            { value: 'active', label: 'To do', count: activeCount }, { value: 'done', label: 'Finished', count: doneCount }, { value: 'all', label: 'All', count: tasks.length },
          ]} />
        </div>
        {doneCount > 0 && <button className="btn-ghost btn-sm" onClick={clearDone}>Clear finished</button>}
      </div>

      <div className="mt-5">
        {todos.loading ? <ListSkeleton rows={4} />
          : todos.error ? <ErrorState error={todos.error} onRetry={todos.reload} />
            : visible.length === 0 ? (
              <EmptyState icon={<ListTodo className="h-6 w-6" />} title={filter === 'done' ? 'Nothing finished yet' : tasks.length ? 'All done!' : 'Your list is empty'}>
                {filter === 'done' ? 'Tasks you tick off will show up here.' : tasks.length ? 'You’ve finished everything on your list.' : 'Add your first task above.'}
              </EmptyState>
            ) : (
              <ul className="space-y-2">
                {visible.map((t) => <TaskRow key={t.id} task={t} busy={pending.has(t.id)} onToggle={() => toggle(t)} onRemove={() => remove(t)} onSave={(c) => patch(t, c)} isDuplicate={(text) => hasDuplicate(text, t.id)} />)}
              </ul>
            )}
      </div>
    </div>
  )
}

function TaskRow({ task, busy, onToggle, onRemove, onSave, isDuplicate }: {
  task: Todo; busy: boolean; onToggle: () => void; onRemove: () => void
  onSave: (c: Partial<Todo>) => Promise<boolean>; isDuplicate: (title: string) => boolean
}) {
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(task.title)
  const [notes, setNotes] = useState(task.notes ?? '')
  const [due, setDue] = useState(task.due_date ?? '')
  const [error, setError] = useState<string | null>(null)

  function startEditing() {
    setTitle(task.title)
    setNotes(task.notes ?? '')
    setDue(task.due_date ?? '')
    setError(null)
    setEditing(true)
  }

  async function save(e: FormEvent) {
    e.preventDefault()
    const clean = title.trim().replace(/\s+/g, ' ')
    if (!clean) return setError('A task needs a title.')
    if (clean.length > TASK_TITLE_MAX) return setError(`Keep it under ${TASK_TITLE_MAX} characters.`)
    if (notes.length > TASK_NOTES_MAX) return setError(`Notes can be up to ${TASK_NOTES_MAX} characters.`)
    if (!task.completed && isDuplicate(clean)) return setError('You already have this task on your list.')
    setEditing(false)
    const ok = await onSave({ title: clean, notes: notes.trim() || null, due_date: due || null })
    if (!ok) setEditing(true)
  }

  if (editing) {
    return (
      <li className="card p-3">
        <form onSubmit={save} className="space-y-2" noValidate>
          <label className="sr-only" htmlFor={`t-${task.id}`}>Task title</label>
          <input id={`t-${task.id}`} className="input" value={title} autoFocus onChange={(e) => { setTitle(e.target.value); setError(null) }} onKeyDown={(e) => { if (e.key === 'Escape') setEditing(false) }} />
          <div className="grid gap-2 sm:grid-cols-[auto_minmax(0,1fr)]">
            <input aria-label="Due date" type="date" className="input" value={due} onChange={(e) => setDue(e.target.value)} />
            <textarea aria-label="Notes" className="input" rows={2} placeholder="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
          {error && <p className="text-xs text-rust" role="alert">{error}</p>}
          <div className="flex gap-2"><button className="btn-primary btn-sm">Save</button><button type="button" className="btn-ghost btn-sm" onClick={() => setEditing(false)}>Cancel</button></div>
        </form>
      </li>
    )
  }

  const overdue = !task.completed && task.due_date && task.due_date < new Date().toISOString().slice(0, 10)
  return (
    <li className={`card flex items-start gap-3 p-3 transition-opacity ${task.id < 0 ? 'opacity-60' : ''}`}>
      <button onClick={onToggle} disabled={busy} role="checkbox" aria-checked={task.completed} aria-label={`${task.completed ? 'Mark as not done' : 'Mark as done'}: ${task.title}`}
        className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-colors ${task.completed ? 'border-forest bg-forest text-paper' : 'border-ink-soft/50 bg-white hover:border-forest'}`}>
        {task.completed && <Check className="h-3.5 w-3.5" aria-hidden />}
      </button>
      <div className="min-w-0 flex-1">
        <p className={`user-text text-sm font-medium ${task.completed ? 'text-muted line-through' : 'text-ink'}`}>{task.title}</p>
        {task.notes && <p className="user-text mt-0.5 text-xs text-muted">{task.notes}</p>}
        {task.due_date && <p className={`mt-1 inline-flex items-center gap-1 text-xs ${overdue ? 'font-medium text-rust' : 'text-muted'}`}><CalendarDays className="h-3 w-3" aria-hidden />{overdue ? 'Overdue · ' : 'Due '}{date(task.due_date)}</p>}
      </div>
      <div className="flex shrink-0 gap-0.5">
        <button className="rounded-md p-1.5 text-ink-soft hover:bg-parchment disabled:opacity-40" onClick={startEditing} disabled={task.id < 0} aria-label={`Edit ${task.title}`}><Pencil className="h-3.5 w-3.5" /></button>
        <button className="rounded-md p-1.5 text-ink-soft hover:bg-parchment disabled:opacity-40" onClick={onRemove} disabled={busy} aria-label={`Delete ${task.title}`}><Trash2 className="h-3.5 w-3.5" /></button>
      </div>
    </li>
  )
}

