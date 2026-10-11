const SYMBOLS: Record<string, string> = { INR: '₹', USD: '$', EUR: '€', GBP: '£' }

export function money(amount: number | null | undefined, currency?: string | null): string {
  if (amount === null || amount === undefined) return 'Unknown'
  const cur = (currency ?? '').toUpperCase()
  const locale = cur === 'INR' ? 'en-IN' : 'en-US'
  const digits = cur === 'INR' || Number.isInteger(amount) ? 0 : 2
  const formatted = amount.toLocaleString(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits })
  return `${SYMBOLS[cur] ?? (cur ? `${cur} ` : '')}${formatted}`
}

export const CONDITION_LABELS: Record<string, string> = {
  new: 'New',
  like_new: 'Like New',
  very_good: 'Very Good',
  good: 'Good',
  acceptable: 'Acceptable',
  poor: 'Poor',
  unknown: 'Not stated',
}

export const CONDITION_HELP: Record<string, string> = {
  like_new: 'No visible wear; looks unread.',
  very_good: 'Minimal wear, no markings or damage to pages.',
  good: 'Normal wear; may have a few markings or a creased spine.',
  acceptable: 'Readable copy with obvious wear, stains or notes.',
  poor: 'Heavy wear or damage, but complete.',
}

export const SHELF_LABELS: Record<string, string> = {
  want_to_read: 'Want to Read',
  reading: 'Currently Reading',
  read: 'Read',
  abandoned: 'Paused / Abandoned',
}

export const LANGUAGE_NAMES: Record<string, string> = {
  en: 'English', hi: 'Hindi', bn: 'Bengali', ta: 'Tamil', te: 'Telugu', mr: 'Marathi', es: 'Spanish',
  fr: 'French', de: 'German', ja: 'Japanese', it: 'Italian', pt: 'Portuguese',
}

export function languageName(code: string | null | undefined): string {
  if (!code) return 'Not available'
  return LANGUAGE_NAMES[code] ?? code.toUpperCase()
}

export function date(value: string | null | undefined, opts: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short', year: 'numeric' }): string {
  if (!value) return '—'
  const d = new Date(value.length === 10 ? `${value}T00:00:00` : value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString('en-IN', opts)
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return 'unknown'
  const diff = Date.now() - new Date(value).getTime()
  const mins = Math.round(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs} h ago`
  const days = Math.round(hrs / 24)
  if (days < 30) return `${days} day${days === 1 ? '' : 's'} ago`
  return date(value)
}

export function authorsText(authors: string[]): string {
  if (!authors.length) return 'Unknown author'
  if (authors.length <= 2) return authors.join(' & ')
  return `${authors[0]} and others`
}

export function plural(n: number, word: string, pluralWord?: string): string {
  return `${n} ${n === 1 ? word : (pluralWord ?? `${word}s`)}`
}
