import { BookOpen, Tag } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import type { BookSummary } from '../types'
import { authorsText, money } from '../utils/format'
import { Stars } from './ui'

const PALETTE = ['#1b2a41', '#2f5d50', '#8c6a38', '#5b3a4a', '#3a4a63', '#4a5d3a']

function hash(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return Math.abs(h)
}

/** Real cover from the metadata provider; a designed typographic placeholder if missing or broken. */
export function BookCover({ title, authors = [], url, className = '', size = 'md' }: { title: string; authors?: string[]; url: string | null; className?: string; size?: 'sm' | 'md' | 'lg' }) {
  const [failed, setFailed] = useState(false)
  const showImg = url && !failed
  const bg = PALETTE[hash(title) % PALETTE.length]
  const text = size === 'sm' ? 'text-[10px]' : size === 'lg' ? 'text-xl' : 'text-sm'
  return (
    <div className={`relative aspect-[2/3] overflow-hidden rounded-xl bg-parchment shadow-[var(--shadow-card)] ${className}`}>
      {showImg ? (
        <img src={url} alt={`Cover of ${title}`} loading="lazy" onError={() => setFailed(true)}
          onLoad={(e) => { if ((e.target as HTMLImageElement).naturalWidth <= 1) setFailed(true) }}
          className="h-full w-full object-cover" />
      ) : (
        <div className="flex h-full w-full flex-col justify-between p-3 text-paper" style={{ backgroundColor: bg }}
          role="img" aria-label={`No cover available for ${title}`}>
          <div className="h-px w-8 bg-gold" />
          <p className={`font-serif font-semibold leading-tight ${text} line-clamp-5`}>{title}</p>
          <p className="text-[10px] uppercase tracking-wider opacity-75 line-clamp-2">{authorsText(authors)}</p>
        </div>
      )}
      <div className="pointer-events-none absolute inset-y-0 left-0 w-1.5 bg-gradient-to-r from-black/15 to-transparent" />
    </div>
  )
}

export function RatingLine({ book }: { book: BookSummary }) {
  const r = book.ratings
  if (r.app_count > 0) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-ink-soft" title="BookWorm reader ratings">
        <Stars value={r.app_average} /> {r.app_average?.toFixed(1)} <span className="text-muted">({r.app_count})</span>
      </span>
    )
  }
  if (r.external_average) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted" title={`Rating from ${r.external_source?.replace('_', ' ')} (not BookWorm readers)`}>
        <Stars value={r.external_average} /> {r.external_average.toFixed(1)} <span>ext.</span>
      </span>
    )
  }
  return <span className="text-xs text-muted">No ratings yet</span>
}

export function BookCard({ book, footer, why }: { book: BookSummary; footer?: ReactNode; why?: ReactNode }) {
  return (
    <article className="group flex flex-col">
      <Link to={`/books/${book.id}`} className="block rounded-xl transition-transform duration-200 group-hover:-translate-y-0.5" aria-label={`${book.title} by ${authorsText(book.authors)}`}>
        <BookCover title={book.title} authors={book.authors} url={book.cover_url} />
      </Link>
      <div className="mt-2.5 flex flex-1 flex-col">
        <Link to={`/books/${book.id}`} className="font-serif text-[15px] font-semibold leading-snug text-ink hover:text-forest line-clamp-2">{book.title}</Link>
        <p className="text-xs text-muted line-clamp-1">{authorsText(book.authors)}</p>
        <div className="mt-1"><RatingLine book={book} /></div>
        {book.used_listing_count > 0 && (
          <p className="mt-1 inline-flex items-center gap-1 text-xs text-forest">
            <Tag className="h-3 w-3" aria-hidden /> Used from {money(book.lowest_used_price, book.lowest_used_currency)}
          </p>
        )}
        {why && <div className="mt-1.5 text-xs leading-snug text-ink-soft">{why}</div>}
        {footer && <div className="mt-auto pt-2">{footer}</div>}
      </div>
    </article>
  )
}

export function BookGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-x-5 gap-y-8 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">{children}</div>
}

export function BookRow({ book, right }: { book: BookSummary; right?: ReactNode }) {
  return (
    <div className="flex gap-4">
      <Link to={`/books/${book.id}`} className="w-16 shrink-0"><BookCover title={book.title} authors={book.authors} url={book.cover_url} size="sm" /></Link>
      <div className="min-w-0 flex-1">
        <Link to={`/books/${book.id}`} className="font-serif font-semibold hover:text-forest">{book.title}</Link>
        <p className="text-sm text-muted">{authorsText(book.authors)}</p>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <RatingLine book={book} />
          {book.page_count && <span className="text-xs text-muted">{book.page_count} pages</span>}
        </div>
      </div>
      {right && <div className="shrink-0">{right}</div>}
    </div>
  )
}

export function EmptyShelfIcon() {
  return <BookOpen className="h-6 w-6" aria-hidden />
}
