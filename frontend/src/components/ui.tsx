import { AlertCircle, ChevronLeft, ChevronRight, Loader2, Star, X } from 'lucide-react'
import { useEffect, useId, useRef, type ReactNode } from 'react'
import type { ApiError } from '../services/api'

export function Spinner({ label = 'Loading', className = '' }: { label?: string; className?: string }) {
  return (
    <span role="status" className={`inline-flex items-center gap-2 text-sm text-muted ${className}`}>
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      <span>{label}…</span>
    </span>
  )
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`skeleton rounded-lg ${className}`} aria-hidden />
}

export function BookGridSkeleton({ count = 8 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 gap-5 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5" aria-busy="true" aria-label="Loading books">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="space-y-2">
          <Skeleton className="aspect-[2/3] w-full rounded-xl" />
          <Skeleton className="h-4 w-4/5" />
          <Skeleton className="h-3 w-1/2" />
        </div>
      ))}
    </div>
  )
}

export function EmptyState({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="card flex flex-col items-center px-6 py-12 text-center">
      {icon && <div className="mb-3 rounded-full bg-parchment p-3 text-gold-dark">{icon}</div>}
      <h3 className="text-lg font-semibold">{title}</h3>
      {children && <div className="mt-1 max-w-md text-sm text-muted">{children}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: ApiError | Error | null; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-xl border border-rust/30 bg-rust-soft px-4 py-3 text-sm text-rust">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="flex-1">
        <p className="font-medium">Something went wrong</p>
        <p className="opacity-90">{error?.message ?? 'Unknown error'}</p>
      </div>
      {onRetry && <button className="btn-outline btn-sm" onClick={onRetry}>Try again</button>}
    </div>
  )
}

export function Notice({ tone = 'info', children, title }: { tone?: 'info' | 'warn' | 'success'; title?: string; children: ReactNode }) {
  const styles = {
    info: 'border-line bg-sky-soft text-ink-soft',
    warn: 'border-gold/40 bg-gold-soft text-gold-dark',
    success: 'border-forest/30 bg-forest-soft text-forest-dark',
  }
  return (
    <div className={`rounded-xl border px-4 py-3 text-sm ${styles[tone]}`}>
      {title && <p className="mb-0.5 font-semibold">{title}</p>}
      <div>{children}</div>
    </div>
  )
}

export function Badge({ children, tone = 'neutral', title }: { children: ReactNode; tone?: 'neutral' | 'forest' | 'gold' | 'rust' | 'ink' | 'sky'; title?: string }) {
  const styles = {
    neutral: 'border-line bg-paper text-ink-soft',
    forest: 'border-forest/25 bg-forest-soft text-forest-dark',
    gold: 'border-gold/40 bg-gold-soft text-gold-dark',
    rust: 'border-rust/30 bg-rust-soft text-rust',
    ink: 'border-ink bg-ink text-paper',
    sky: 'border-ink-soft/20 bg-sky-soft text-ink-soft',
  }
  return <span title={title} className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium ${styles[tone]}`}>{children}</span>
}

export function Stars({ value, size = 'sm', label }: { value: number | null; size?: 'sm' | 'md'; label?: string }) {
  const px = size === 'sm' ? 'h-3.5 w-3.5' : 'h-5 w-5'
  const v = value ?? 0
  return (
    <span className="inline-flex items-center" role="img" aria-label={label ?? (value ? `${value.toFixed(1)} out of 5 stars` : 'No rating')}>
      {[1, 2, 3, 4, 5].map((i) => (
        <Star key={i} aria-hidden className={`${px} ${i <= Math.round(v) ? 'fill-gold text-gold' : 'text-line'}`} />
      ))}
    </span>
  )
}

export function StarInput({ value, onChange, label = 'Your rating' }: { value: number; onChange: (v: number) => void; label?: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map((i) => (
        <button key={i} type="button" role="radio" aria-checked={value === i} aria-label={`${i} star${i > 1 ? 's' : ''}`}
          onClick={() => onChange(i)} className="rounded p-0.5 transition-transform hover:scale-110">
          <Star className={`h-6 w-6 ${i <= value ? 'fill-gold text-gold' : 'text-line'}`} aria-hidden />
        </button>
      ))}
    </div>
  )
}

export function Pagination({ page, total, pageSize, onPage }: { page: number; total: number; pageSize: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (pages <= 1) return null
  return (
    <nav className="mt-8 flex items-center justify-center gap-3" aria-label="Pagination">
      <button className="btn-outline btn-sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        <ChevronLeft className="h-4 w-4" aria-hidden /> Previous
      </button>
      <span className="text-sm text-muted">Page {page} of {pages}</span>
      <button className="btn-outline btn-sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next <ChevronRight className="h-4 w-4" aria-hidden />
      </button>
    </nav>
  )
}

export function Modal({ open, onClose, title, children, footer, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) d.showModal?.()
    if (!open && d.open) d.close?.()
  }, [open])
  if (!open) return null
  return (
    <dialog ref={ref} aria-labelledby={titleId} onCancel={(e) => { e.preventDefault(); onClose() }}
      onClick={(e) => { if (e.target === ref.current) onClose() }}
      className={`m-auto w-[calc(100%-2rem)] ${wide ? 'max-w-3xl' : 'max-w-lg'} rounded-2xl border border-line bg-paper p-0 text-ink shadow-[var(--shadow-lift)] backdrop:bg-ink/40`}>
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <h2 id={titleId} className="text-lg font-semibold">{title}</h2>
        <button onClick={onClose} className="btn-ghost btn-sm" aria-label="Close dialog"><X className="h-4 w-4" /></button>
      </div>
      <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>
      {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
    </dialog>
  )
}

export function Field({ label, error, hint, children, htmlFor }: { label: string; error?: string; hint?: ReactNode; children: ReactNode; htmlFor?: string }) {
  return (
    <div>
      <label className="label" htmlFor={htmlFor}>{label}</label>
      {children}
      {hint && !error && <p className="mt-1 text-xs text-muted">{hint}</p>}
      {error && <p className="mt-1 text-xs text-rust" role="alert">{error}</p>}
    </div>
  )
}

export function Tabs<T extends string>({ tabs, value, onChange, label }: { tabs: { value: T; label: string; count?: number }[]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <div role="tablist" aria-label={label} className="flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((t) => (
        <button key={t.value} role="tab" aria-selected={value === t.value} onClick={() => onChange(t.value)}
          className={`-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors ${value === t.value ? 'border-gold text-ink' : 'border-transparent text-muted hover:text-ink'}`}>
          {t.label}{t.count !== undefined && <span className="ml-1.5 rounded-full bg-parchment px-1.5 text-xs">{t.count}</span>}
        </button>
      ))}
    </div>
  )
}

export function PageHeader({ eyebrow, title, children, actions }: { eyebrow?: string; title: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        {eyebrow && <p className="eyebrow mb-2">{eyebrow}</p>}
        <h1 className="font-serif text-3xl font-semibold sm:text-4xl">{title}</h1>
        {children && <div className="mt-2 max-w-2xl text-muted">{children}</div>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  )
}
