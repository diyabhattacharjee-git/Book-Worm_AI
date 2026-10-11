"""Second-hand marketplace intelligence endpoints (LangGraph workflow + price tools)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import llm, used_book_graph
from app.core.ratelimit import rate_limit
from app.db.session import get_db
from app.marketplace.identify import identify
from app.marketplace.pricing import estimate_price, interpret_price
from app.marketplace.providers import (
    SearchRequest,
    community_to_normalized,
    providers_status,
    search_all,
)
from app.marketplace.quality import assess
from app.marketplace.validate import validate_and_dedupe
from app.models.marketplace import MarketplaceListing
from app.schemas.marketplace import CompareListingsIn, EstimateIn, UsedSearchIn
from app.services.listings import seller_sales

router = APIRouter(prefix="/marketplace", tags=["marketplace intelligence"])


def _form(body: UsedSearchIn) -> dict:
    return {"title": body.title, "author": body.author, "isbn": body.isbn, "edition": body.edition,
            "max_price": body.max_price, "currency": body.currency, "min_condition": body.min_condition,
            "location": body.location, "delivery": body.delivery, "include_external": body.include_external}


@router.post("/search-used-books", dependencies=[Depends(rate_limit("used_search", 30, 60))])
def search_used_books(body: UsedSearchIn):
    """Run the multi-step used-book workflow and return the final result with its trace."""
    return used_book_graph.run(body.query, _form(body))


@router.post("/search-used-books/stream", dependencies=[Depends(rate_limit("used_search", 30, 60))])
def search_used_books_stream(body: UsedSearchIn):
    """Same workflow, streamed as NDJSON: one event per step as it starts and finishes, then the result."""
    return StreamingResponse(used_book_graph.stream(body.query, _form(body)), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/estimate-price", dependencies=[Depends(rate_limit("estimate", 30, 60))])
def estimate(body: EstimateIn, db: Session = Depends(get_db)):
    book = identify(db, isbn=body.isbn, title=body.title, author=body.author)
    req = SearchRequest(title=book.title or body.title, author=(book.authors or [body.author])[0] if (book.authors or body.author) else None,
                        isbn=book.requested_isbn, isbns=book.isbns, book_id=book.book_id, currency=body.currency)
    results = search_all(req)
    items = [it for r in results for it in r.listings]
    kept, excluded = validate_and_dedupe(items, book)
    cond = body.condition or "good"
    exclude_uid = f"community:{body.exclude_listing_id}" if body.exclude_listing_id else None
    est = estimate_price(kept, body.currency, cond, new_price_reference=body.new_price_reference, exclude_uid=exclude_uid)
    return {
        "book": book.to_dict(),
        "estimate": est.to_dict(),
        "asking_price": body.asking_price,
        "asking_price_verdict": interpret_price(body.asking_price, est) if body.asking_price else None,
        "providers": [{"provider": r.provider, "label": r.label, "ok": r.ok, "count": len(r.listings),
                       "error": r.error, "skipped": r.skipped} for r in results],
        "excluded_count": len(excluded),
        "method_note": "Deterministic statistics over comparable asking prices; no machine-learning or LLM price prediction.",
    }


@router.post("/compare-listings")
def compare_listings(body: CompareListingsIn, db: Session = Depends(get_db)):
    """Compare specific community listings side by side, with quality signals and price verdicts."""
    rows = list(db.scalars(select(MarketplaceListing).where(MarketplaceListing.id.in_(body.listing_ids))).unique())
    rows = [r for r in rows if r.status != "removed"]
    if len(rows) < 2:
        raise HTTPException(status_code=422, detail="Choose at least two available listings")
    sales = seller_sales(db, list({r.seller_id for r in rows}))
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        it = community_to_normalized(r, sales, now)
        book = identify(db, isbn=r.isbn, title=r.title, author=r.author, allow_network=False)
        comps = search_all(SearchRequest(title=book.title or r.title, isbn=book.requested_isbn, isbns=book.isbns,
                                         book_id=book.book_id, currency=r.currency, include_external=False))
        kept, _ = validate_and_dedupe([c for res in comps for c in res.listings], book)
        me = next((k for k in kept if k.uid == it.uid), it)
        est = estimate_price(kept, r.currency, r.condition, exclude_uid=it.uid)
        q = assess(me, est)
        out.append({
            "listing_id": r.id, "title": r.title, "author": r.author, "edition": r.edition_text or ("ISBN " + r.isbn if r.isbn else None),
            "condition": r.condition, "price": float(r.price_amount), "currency": r.currency,
            "shipping_cost": me.shipping_cost, "total_known_cost": me.total_known_cost,
            "total_cost_complete": me.total_cost_complete, "delivery": r.delivery,
            "location": me.location, "seller": r.seller.display_name, "is_sample": r.is_sample,
            "match_to_catalogue": me.match, "quality": q.to_dict(), "price_verdict": interpret_price(me.price, est),
            "typical_range": [est.low, est.high] if est.status != "insufficient_data" else None,
            "comparables": est.n_comparables,
        })
    same_book = len({(o["title"].lower()) for o in out}) == 1
    best = None
    complete = [o for o in out if o["total_cost_complete"]]
    if same_book and complete:
        best = min(complete, key=lambda o: (o["total_known_cost"] or 1e12) - 0.5 * o["quality"]["score"])
    return {"rows": out, "same_book": same_book,
            "suggestion": ({"listing_id": best["listing_id"],
                            "text": "Lowest known total cost after weighing listing completeness."} if best else None),
            "note": None if same_book else "These listings are for different books, so prices aren't directly comparable."}


@router.get("/providers/status")
def provider_status(db: Session = Depends(get_db)):
    return {"providers": providers_status(db), "llm": llm.status()}
