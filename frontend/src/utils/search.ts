import type { BookSummary } from '../types'

const IGNORED_WORDS = new Set(['a', 'an', 'and', 'by', 'for', 'of', 'the', 'to'])
const ISBN = /^[\d\s-]{10,17}x?$/i
const REQUEST_START = /^(i\b|suggest|recommend|find|show|give|looking|want|need|books?\b|something|anything|what|which|any\b)/i
const TITLE_MAX_WORDS = 6

function words(text: string): string[] {
  return text.toLowerCase().replace(/['’]/g, '').split(/[^\p{L}\p{N}]+/u).filter(Boolean)
}

/** True when a result is really what was typed, rather than a loose keyword hit in some description. */
export function hasCloseMatch(query: string, books: BookSummary[]): boolean {
  if (ISBN.test(query.trim())) return books.length > 0
  const wanted = words(query).filter((w) => !IGNORED_WORDS.has(w))
  return books.some((b) => {
    const known = new Set(words([b.title, b.subtitle ?? '', ...b.authors, ...b.genres].join(' ')))
    return wanted.every((w) => known.has(w))
  })
}

/** A plain-language request makes a poor query for a public catalogue; a short name of a book doesn't. */
export function looksLikeBookName(query: string): boolean {
  const text = query.trim()
  return text.length > 0 && !REQUEST_START.test(text) && words(text).length <= TITLE_MAX_WORDS
}
