export interface RatingSummary {
  app_average: number | null
  app_count: number
  external_average: number | null
  external_count: number | null
  external_source: string | null
}

export interface BookSummary {
  id: number
  title: string
  subtitle: string | null
  authors: string[]
  cover_url: string | null
  genres: string[]
  first_published_year: number | null
  page_count: number | null
  language: string | null
  ratings: RatingSummary
  is_sample: boolean
  used_listing_count: number
  lowest_used_price: number | null
  lowest_used_currency: string | null
}

export interface Edition {
  id: number | null
  isbn13: string | null
  format: string | null
  edition_label?: string | null
  publisher: string | null
  published_year: number | null
  page_count: number | null
  language: string | null
  source: string
  source_url?: string | null
}

export interface BookDetail extends BookSummary {
  description: string | null
  publisher: string | null
  series: string | null
  subjects: string[]
  isbn13: string | null
  editions: Edition[]
  source: string
  metadata_fetched_at: string | null
  external_links: { label: string; url: string }[]
  difficulty_signal: string | null
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface Preferences {
  favorite_genres: string[]
  favorite_authors: string[]
  preferred_languages: string[]
  favorite_themes: string[]
  topics_to_explore: string[]
  enjoyed_book_ids: number[]
  reading_goal_text: string | null
  preferred_length: 'short' | 'medium' | 'long' | 'any' | null
  onboarding_completed: boolean
}

export interface User {
  id: number
  email: string
  username: string | null
  has_password: boolean
  email_verified: boolean
  display_name: string
  role: 'user' | 'admin'
  is_seller: boolean
  is_demo: boolean
  created_at: string
  bio: string | null
  avatar_url: string | null
  location_city: string | null
  location_public: boolean
  allow_inquiries: boolean
  contact_note: string | null
  preferences: Preferences
}

export interface Review {
  id: number
  book_id: number
  user_id: number
  user_display_name: string
  rating: number
  body: string | null
  helpful_count: number
  status: string
  created_at: string
  updated_at: string
  is_mine: boolean
  voted_helpful: boolean
}

export interface Reason {
  signal: 'content' | 'collaborative' | 'popularity' | 'preference'
  text: string
  evidence: Record<string, unknown>
}

export interface RecommendationItem {
  book: BookSummary
  score: number
  strategy: string
  contributions: Record<string, number>
  reasons: Reason[]
}

export interface RecommendationResponse {
  mode: 'personalized' | 'cold_start'
  mode_label: string
  signals_used: string[]
  collaborative_status: { reliable: boolean; users_with_enough_data: number; required_users: number }
  notes: string[]
  weights: Record<string, number>
  content_backend: string
  how_it_works: string[]
  items: RecommendationItem[]
}

export type ShelfStatus = 'want_to_read' | 'reading' | 'read' | 'abandoned'

export interface ShelfEntry {
  id: number
  book: BookSummary
  status: ShelfStatus
  pages_read: number
  total_pages: number | null
  percent: number | null
  started_on: string | null
  finished_on: string | null
  notes: string | null
  updated_at: string
}

export type Condition = 'like_new' | 'very_good' | 'good' | 'acceptable' | 'poor'

export interface Listing {
  id: number
  book_id: number | null
  title: string
  author: string
  isbn: string | null
  edition_text: string | null
  published_year: number | null
  description: string | null
  condition: Condition
  condition_label: string
  price_amount: number
  currency: string
  shipping_cost: number | null
  shipping_known: boolean
  total_known_cost: number
  total_cost_complete: boolean
  delivery: 'pickup' | 'shipping' | 'both'
  location_city: string | null
  allow_inquiries: boolean
  status: 'active' | 'inactive' | 'sold' | 'removed'
  is_sample: boolean
  images: { id: number; url: string }[]
  cover_url: string | null
  seller: { id: number; display_name: string; member_since: string; completed_sales: number; is_demo: boolean }
  created_at: string
  updated_at: string
  sold_at: string | null
  is_mine: boolean
  is_favorite: boolean
  view_count?: number | null
  inquiry_count?: number | null
  favorite_count?: number | null
  location_public?: boolean | null
  moderation_note?: string | null
}

export interface Inquiry {
  id: number
  listing_id: number
  listing_title: string
  listing_status: string
  buyer: { id: number; display_name: string }
  seller: { id: number; display_name: string }
  message: string
  seller_reply: string | null
  replied_at: string | null
  status: 'open' | 'answered' | 'closed'
  created_at: string
  role: 'buyer' | 'seller'
}

// ---- Used-book intelligence workflow ----
export interface NormalizedListing {
  uid: string
  provider: string
  provider_label: string
  is_external: boolean
  is_sample: boolean
  title: string
  author: string | null
  isbn: string | null
  edition_text: string | null
  condition: string
  price: number | null
  currency: string | null
  shipping_cost: number | null
  shipping_known: boolean
  total_known_cost: number | null
  total_cost_complete: boolean
  delivery: string | null
  location: string | null
  country: string | null
  seller_name: string | null
  seller_id: number | null
  image_url: string | null
  url: string | null
  status: string
  listed_at: string | null
  fetched_at: string
  match: 'exact' | 'same_work' | 'approximate' | 'unmatched'
  match_confidence: number
  validation_issues: string[]
}

export interface PriceVerdict {
  verdict: 'well_below' | 'below' | 'within' | 'above' | 'well_above' | 'unknown'
  text: string
  range_low?: number | null
  range_high?: number | null
  n_comparables?: number
  price?: number
}

export interface Deal {
  listing: NormalizedListing
  deal: {
    uid: string
    score: number
    group: 'match' | 'near_match' | 'other'
    components: Record<string, number>
    reasons: string[]
    cautions: string[]
    unmet: string[]
    price_verdict: PriceVerdict | null
  }
  quality: { score: number; level: string; flags: string[]; breakdown: Record<string, number> } | null
}

export interface PriceEstimate {
  status: 'ok' | 'rule_based' | 'insufficient_data'
  currency: string
  condition: string
  low: number | null
  median: number | null
  high: number | null
  n_comparables: number
  tier: string | null
  confidence: 'low' | 'medium' | 'high' | null
  confidence_score: number | null
  sources: Record<string, number>
  comparables: { uid: string; title: string; price: number; currency: string; condition: string; match: string; provider: string; is_sample: boolean; url: string }[]
  excluded_other_currency: number
  limitations: string[]
  explanation: string
}

export interface ProviderSummary {
  provider: string
  label: string
  ok: boolean
  count: number
  error: string | null
  skipped: string | null
  duration_ms?: number
  fetched_at?: string | null
}

export interface TraceStep {
  step: string
  label: string
  status: 'running' | 'completed' | 'failed'
  duration_ms?: number
  summary?: string | null
  method?: string
}

export interface UsedSearchResult {
  status: 'ok' | 'needs_clarification' | 'no_results'
  summary: { text: string; source: string; deterministic_text: string }
  params: Record<string, unknown> & { title?: string | null; currency?: string; max_price?: number | null; extraction_method?: string }
  book: {
    found: boolean
    confidence: number
    method: string
    book_id: number | null
    title: string | null
    authors: string[]
    isbns: string[]
    cover_url: string | null
    ambiguous: boolean
    candidates: { book_id?: number; title: string; authors: string[]; score: number }[]
    notes: string[]
  } | null
  providers: ProviderSummary[]
  estimate: PriceEstimate | null
  asking_price_verdict: PriceVerdict | null
  deals: Deal[]
  excluded: { uid: string; title: string; provider: string; reason: string }[]
  errors: string[]
  disclaimers: string[]
  trace: TraceStep[]
  generated_at: string
}

export interface ComparisonData {
  fields: [string, string][]
  rows: (Record<string, string | number | null> & { book_id: number; title: string; cover_url: string | null })[]
  advice: { pick_book_id: number | null; text: string; evidence: string | null }[]
  generated_by: string
}

export interface AssistantPayload {
  type: 'books' | 'comparison' | 'deals' | 'plan' | 'action'
  items?: { book: BookSummary; why: string | null }[]
  data?: unknown
  plan_id?: number
  pages_per_day?: number
  estimated_finish?: string | null
  action?: string
  book_ids?: number[]
}

export interface AssistantReply {
  text: string
  tool: string
  routed_by: string
  source: string
  payloads: AssistantPayload[]
  suggestions: string[]
}

export interface ReadingPlan {
  id: number
  title: string
  status: string
  start_date: string
  target_date: string | null
  minutes_per_day: number
  pages_per_minute: number
  reading_days: number[]
  book_ids: number[]
  books: { id: number; title: string }[]
  feasibility_note: string | null
  progress: {
    planned_pages_to_date: number
    actual_pages: number
    planned_total: number
    difference: number
    status: 'ahead' | 'behind' | 'on_track'
    scheduled_finish: string | null
    percent_complete: number | null
  }
  items: { id: number; day: string; book_id: number; title: string; start_page: number; end_page: number; completed: boolean; actual_pages: number | null }[]
  reminders: string
}
