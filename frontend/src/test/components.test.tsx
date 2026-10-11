import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { BookCover } from '../components/books'
import { DealCard, PriceEstimateCard, WorkflowStatus } from '../components/marketplace'
import type { Deal, PriceEstimate } from '../types'

const deal: Deal = {
  listing: {
    uid: 'ebay:1', provider: 'ebay', provider_label: 'eBay', is_external: true, is_sample: false, title: 'Atomic Habits (Hardcover)',
    author: null, isbn: '9780735211292', edition_text: null, condition: 'very_good', price: 12.5, currency: 'USD', shipping_cost: null,
    shipping_known: false, total_known_cost: 12.5, total_cost_complete: false, delivery: 'shipping', location: 'Austin', country: 'US',
    seller_name: 'bookshop', seller_id: null, image_url: null, url: 'https://www.ebay.com/itm/1', status: 'active', listed_at: null,
    fetched_at: new Date().toISOString(), match: 'exact', match_confidence: 1, validation_issues: [],
  },
  deal: { uid: 'ebay:1', score: 0.7, group: 'near_match', components: {}, reasons: ['Exact edition match (ISBN)'], cautions: ['No photos'], unmet: ['Shipping unknown: may exceed budget'], price_verdict: { verdict: 'unknown', text: 'n/a' } },
  quality: { score: 60, level: 'fair', flags: ['No photos'], breakdown: { completeness: 20 } },
}

describe('BookCover', () => {
  it('renders a designed placeholder when there is no cover URL', () => {
    render(<BookCover title="Dune" authors={['Frank Herbert']} url={null} />)
    expect(screen.getByRole('img', { name: /no cover available for dune/i })).toBeInTheDocument()
    expect(screen.getByText('Dune')).toBeInTheDocument()
  })
  it('uses the real cover image when available', () => {
    render(<BookCover title="Dune" url="https://covers.openlibrary.org/b/isbn/1-L.jpg" />)
    expect(screen.getByAltText('Cover of Dune')).toHaveAttribute('src', 'https://covers.openlibrary.org/b/isbn/1-L.jpg')
  })
})

describe('WorkflowStatus', () => {
  it('shows only steps that actually started, with their state', () => {
    render(<WorkflowStatus running steps={[
      { step: 'understand', label: 'Understanding your request', status: 'running' },
      { step: 'understand', label: 'Understanding your request', status: 'completed', duration_ms: 12, summary: 'book: Dune' },
      { step: 'identify', label: 'Identifying the book', status: 'running' },
    ]} />)
    expect(screen.getByText('Understanding your request')).toBeInTheDocument()
    expect(screen.getByText('book: Dune')).toBeInTheDocument()
    expect(screen.getByText('Identifying the book')).toBeInTheDocument()
    expect(screen.queryByText('Ranking deals')).not.toBeInTheDocument()
  })
})

describe('DealCard', () => {
  it('marks incomplete totals, cautions and opens external links safely', () => {
    render(<MemoryRouter><DealCard deal={deal} rank={1} /></MemoryRouter>)
    expect(screen.getByText('(incomplete)')).toBeInTheDocument()
    expect(screen.getByText('Shipping unknown: may exceed budget')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: /view on ebay/i })
    expect(link).toHaveAttribute('href', 'https://www.ebay.com/itm/1')
    expect(link.getAttribute('rel')).toContain('noopener')
    expect(screen.getByText(/price: not enough data/i)).toBeInTheDocument()
  })
})

describe('PriceEstimateCard', () => {
  it('refuses to show a range when data is insufficient', () => {
    const est: PriceEstimate = {
      status: 'insufficient_data', currency: 'INR', condition: 'good', low: null, median: null, high: null, n_comparables: 1, tier: null,
      confidence: null, confidence_score: null, sources: {}, comparables: [], excluded_other_currency: 0,
      limitations: ['Based on current asking prices, not completed sales.'], explanation: 'Insufficient data to estimate reliably: found 1.',
    }
    render(<PriceEstimateCard estimate={est} />)
    expect(screen.getByText('Insufficient data to estimate reliably')).toBeInTheDocument()
    expect(screen.queryByText(/confidence$/)).not.toBeInTheDocument()
  })
})
