// Client-side checks that mirror the server's rules, so people get instant, field-level feedback.

export const REVIEW_MAX_LENGTH = 5000
export const LISTING_DESCRIPTION_MIN = 10
export const LISTING_DESCRIPTION_MAX = 3000
export const MAX_PRICE = 1_000_000
export const MAX_SHIPPING = 100_000
export const PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/webp']
export const MAX_PHOTOS = 6
export const MAX_PHOTO_MB = 5
export const TASK_TITLE_MAX = 200
export const TASK_NOTES_MAX = 1000

function isbn10CheckOk(d: string): boolean {
  const sum = [...d].reduce((acc, ch, i) => acc + (ch === 'X' ? 10 : Number(ch)) * (10 - i), 0)
  return sum % 11 === 0
}

function isbn13CheckOk(d: string): boolean {
  const sum = [...d].reduce((acc, ch, i) => acc + Number(ch) * (i % 2 ? 3 : 1), 0)
  return sum % 10 === 0
}

/** Validates the check digit of an ISBN-10 or ISBN-13, ignoring spaces and hyphens. */
export function isValidIsbn(raw: string): boolean {
  const d = raw.replace(/[\s-]/g, '').toUpperCase()
  if (/^\d{9}[\dX]$/.test(d)) return isbn10CheckOk(d)
  if (/^97[89]\d{10}$/.test(d)) return isbn13CheckOk(d)
  return false
}

export function hasText(s: string): boolean {
  return /[\p{L}\p{N}]/u.test(s)
}

/** Null when `raw` is an amount with at most two decimals, otherwise what's wrong with it. */
export function amountProblem(raw: string): string | null {
  if (!/^\d+(\.\d{1,2})?$/.test(raw.trim())) return 'Enter an amount like 250 or 249.50.'
  return null
}

export function photoProblem(file: File): string | null {
  if (!PHOTO_TYPES.includes(file.type)) return `${file.name}: only JPEG, PNG or WEBP images can be uploaded.`
  if (file.size > MAX_PHOTO_MB * 1024 * 1024) return `${file.name} is larger than ${MAX_PHOTO_MB} MB.`
  if (file.size === 0) return `${file.name} is empty.`
  return null
}

/** True if the browser can actually decode the file as an image (a renamed text file fails here). */
export async function canDecodeImage(file: File): Promise<boolean> {
  if (typeof createImageBitmap !== 'function') return true
  try {
    const bitmap = await createImageBitmap(file)
    bitmap.close()
    return true
  } catch {
    return false
  }
}
