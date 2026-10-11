import { Lightbulb } from 'lucide-react'
import { Link } from 'react-router'
import type { ComparisonData } from '../types'
import { languageName } from '../utils/format'
import { BookCover } from './books'

export function ComparisonTable({ data, compact = false }: { data: ComparisonData; compact?: boolean }) {
  const fields = compact ? data.fields.filter(([k]) => ['authors', 'genres', 'page_count', 'first_published_year', 'app_rating', 'difficulty', 'used_copies'].includes(k)) : data.fields
  return (
    <div className="space-y-4">
      <div className="overflow-x-auto rounded-xl border border-line bg-paper">
        <table className="w-full min-w-[560px] text-left text-sm">
          <thead>
            <tr className="border-b border-line">
              <th className="w-40 p-3 text-xs uppercase tracking-wide text-muted"><span className="sr-only">Attribute</span></th>
              {data.rows.map((r) => (
                <th key={r.book_id} className="p-3 align-bottom">
                  <Link to={`/books/${r.book_id}`} className="flex items-end gap-3 hover:text-forest">
                    {!compact && <div className="w-12 shrink-0"><BookCover title={r.title} url={r.cover_url} size="sm" /></div>}
                    <span className="font-serif text-base font-semibold leading-snug">{r.title}</span>
                  </Link>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {fields.map(([key, label]) => (
              <tr key={key}>
                <th scope="row" className="p-3 align-top text-xs font-medium uppercase tracking-wide text-muted">{label}</th>
                {data.rows.map((r) => {
                  const v = r[key]
                  const text = key === 'language' && typeof v === 'string' && v !== 'Not available' ? languageName(v) : v ?? 'Not available'
                  return <td key={r.book_id} className={`p-3 align-top ${text === 'Not available' ? 'text-muted' : 'text-ink-soft'}`}>{String(text)}</td>
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.advice.length > 0 && (
        <div className="rounded-xl border border-gold/40 bg-gold-soft p-4">
          <p className="mb-2 flex items-center gap-2 text-sm font-semibold text-gold-dark"><Lightbulb className="h-4 w-4" aria-hidden />What the evidence suggests</p>
          <ul className="space-y-2 text-sm text-ink">
            {data.advice.map((a) => (
              <li key={a.text}>{a.text}{a.evidence && <span className="block text-xs text-muted">Evidence: {a.evidence}</span>}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
