"""Administrator dashboard & moderation. Every route requires role=admin."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.db.session import get_db
from app.marketplace.providers import community_to_normalized
from app.marketplace.quality import assess
from app.models.book import Book
from app.models.marketplace import ListingInquiry, ListingReport, MarketplaceListing
from app.models.social import AuditLog, RecommendationEvent, Review, ReviewReport
from app.models.user import User
from app.repositories.books import summaries
from app.security.deps import require_admin
from app.services.listings import listings_out, seller_sales
from app.services.users import audit

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview")
def overview(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    week = now - timedelta(days=7)

    def count(model, *where):
        return db.scalar(select(func.count(model.id)).where(*where)) or 0

    listing_status = dict(db.execute(select(MarketplaceListing.status, func.count(MarketplaceListing.id))
                                     .group_by(MarketplaceListing.status)).all())
    prices = db.execute(select(MarketplaceListing.currency, func.count(MarketplaceListing.id),
                               func.avg(MarketplaceListing.price_amount))
                        .where(MarketplaceListing.status == "active", MarketplaceListing.is_sample.is_(False))
                        .group_by(MarketplaceListing.currency)).all()
    return {
        "users": {"total": count(User), "real": count(User, User.is_demo.is_(False)), "demo": count(User, User.is_demo.is_(True)),
                  "sellers": count(User, User.is_seller.is_(True)), "admins": count(User, User.role == "admin"),
                  "new_last_7_days": count(User, User.created_at >= week)},
        "catalogue": {"books": count(Book), "sample_books": count(Book, Book.is_sample.is_(True))},
        "marketplace": {"listings_by_status": listing_status,
                        "sample_listings": count(MarketplaceListing, MarketplaceListing.is_sample.is_(True)),
                        "inquiries": count(ListingInquiry), "new_listings_7d": count(MarketplaceListing, MarketplaceListing.created_at >= week),
                        "real_active_avg_price": [{"currency": c, "count": n, "average": round(float(a), 2)} for c, n, a in prices]},
        "reviews": {"total": count(Review), "hidden": count(Review, Review.status == "hidden")},
        "reports": {"open_listing_reports": count(ListingReport, ListingReport.status == "open"),
                    "open_review_reports": count(ReviewReport, ReviewReport.status == "open")},
        "recommendations": {"events_7d": count(RecommendationEvent, RecommendationEvent.created_at >= week),
                            "by_event": dict(db.execute(select(RecommendationEvent.event, func.count(RecommendationEvent.id))
                                                        .group_by(RecommendationEvent.event)).all())},
    }


@router.get("/users")
def list_users(q: str | None = Query(None, max_length=100), page: int = Query(1, ge=1), page_size: int = Query(25, le=100),
               _: User = Depends(require_admin), db: Session = Depends(get_db)):
    stmt = select(User)
    if q:
        stmt = stmt.where((User.email.ilike(f"%{q}%")) | (User.display_name.ilike(f"%{q}%")))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).unique()
    return {"total": total, "items": [{"id": u.id, "email": u.email, "username": u.username, "display_name": u.display_name, "role": u.role,
                                       "is_seller": u.is_seller, "is_active": u.is_active, "is_demo": u.is_demo,
                                       "created_at": u.created_at, "last_login_at": u.last_login_at} for u in rows]}


class UserAdminUpdate(BaseModel):
    is_active: bool


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserAdminUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise not_found("User")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="You can't suspend your own account")
    user.is_active = body.is_active
    user.token_version += 1  # sign the user out
    audit(db, admin, "user_suspended" if not body.is_active else "user_reactivated", "user", user.id)
    db.commit()
    return {"id": user.id, "is_active": user.is_active}


@router.get("/books")
def admin_books(q: str | None = Query(None, max_length=100), page: int = Query(1, ge=1), _: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    stmt = select(Book)
    if q:
        stmt = stmt.where(Book.title.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    books = list(db.scalars(stmt.order_by(Book.created_at.desc()).offset((page - 1) * 25).limit(25)).unique())
    sums = summaries(db, books)
    return {"total": total, "items": [{**s.model_dump(), "source": b.source, "has_description": bool(b.description)}
                                      for s, b in zip(sums, books)]}


class BookAdminUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=6000)
    page_count: int | None = Field(default=None, ge=1, le=10000)
    language: str | None = Field(default=None, max_length=12)
    difficulty: Literal["beginner", "intermediate", "advanced"] | None = None


@router.patch("/books/{book_id}")
def update_book(book_id: int, body: BookAdminUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    book = db.get(Book, book_id)
    if not book:
        raise not_found("Book")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(book, k, v)
    audit(db, admin, "book_updated", "book", book.id, fields=list(changes))
    db.commit()
    return {"id": book.id, "updated": list(changes)}


@router.delete("/books/{book_id}", status_code=204)
def delete_book(book_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    book = db.get(Book, book_id)
    if not book:
        raise not_found("Book")
    audit(db, admin, "book_deleted", "book", book.id, title=book.title)
    db.delete(book)
    db.commit()


@router.get("/listings")
def admin_listings(status: str | None = None, suspicious: bool = False, page: int = Query(1, ge=1),
                   admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    stmt = select(MarketplaceListing)
    if status:
        stmt = stmt.where(MarketplaceListing.status == status)
    rows = list(db.scalars(stmt.order_by(MarketplaceListing.created_at.desc()).limit(500)).unique())
    sales = seller_sales(db, list({r.seller_id for r in rows}))
    now = datetime.now(timezone.utc)
    reports = dict(db.execute(select(ListingReport.listing_id, func.count(ListingReport.id))
                              .where(ListingReport.status == "open").group_by(ListingReport.listing_id)).all())
    enriched = []
    for r, out in zip(rows, listings_out(db, rows, admin)):
        q = assess(community_to_normalized(r, sales, now), None)
        item = {**out.model_dump(), "quality": q.to_dict(), "open_reports": reports.get(r.id, 0)}
        if suspicious and not (q.level == "limited" or reports.get(r.id)):
            continue
        enriched.append(item)
    start = (page - 1) * 25
    return {"total": len(enriched), "items": enriched[start:start + 25],
            "note": "'Suspicious' means limited listing information or open reports; it is not a finding of wrongdoing."}


class ListingModeration(BaseModel):
    status: Literal["active", "inactive", "removed"]
    note: str | None = Field(default=None, max_length=300)


@router.patch("/listings/{listing_id}")
def moderate_listing(listing_id: int, body: ListingModeration, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    listing = db.get(MarketplaceListing, listing_id)
    if not listing:
        raise not_found("Listing")
    previous = listing.status
    listing.status = body.status
    listing.moderation_note = body.note
    if body.status in ("removed", "inactive"):
        for rep in db.scalars(select(ListingReport).where(ListingReport.listing_id == listing_id, ListingReport.status == "open")):
            rep.status, rep.resolved_at = "resolved", datetime.now(timezone.utc)
    audit(db, admin, "listing_moderated", "listing", listing.id, previous=previous, new=body.status, note=body.note)
    db.commit()
    return {"id": listing.id, "status": listing.status}


@router.get("/reviews")
def admin_reviews(status: Literal["visible", "hidden"] | None = None, _: User = Depends(require_admin),
                  db: Session = Depends(get_db)):
    stmt = select(Review).where(Review.body.is_not(None))
    if status:
        stmt = stmt.where(Review.status == status)
    rows = db.scalars(stmt.order_by(Review.updated_at.desc()).limit(100)).unique()
    return [{"id": r.id, "book_id": r.book_id, "user": r.user.display_name, "rating": r.rating, "body": r.body,
             "status": r.status, "helpful_count": r.helpful_count, "updated_at": r.updated_at} for r in rows]


class ReviewModeration(BaseModel):
    status: Literal["visible", "hidden"]


@router.patch("/reviews/{review_id}")
def moderate_review(review_id: int, body: ReviewModeration, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    review = db.get(Review, review_id)
    if not review:
        raise not_found("Review")
    review.status = body.status
    if body.status == "hidden":
        for rep in db.scalars(select(ReviewReport).where(ReviewReport.review_id == review_id, ReviewReport.status == "open")):
            rep.status, rep.resolved_at = "resolved", datetime.now(timezone.utc)
    audit(db, admin, "review_moderated", "review", review.id, status=body.status)
    db.commit()
    return {"id": review.id, "status": review.status}


@router.get("/reports")
def reports(status: Literal["open", "resolved", "dismissed"] = "open", _: User = Depends(require_admin),
            db: Session = Depends(get_db)):
    lr = db.scalars(select(ListingReport).where(ListingReport.status == status).order_by(ListingReport.created_at.desc()).limit(200)).unique()
    rr = db.scalars(select(ReviewReport).where(ReviewReport.status == status).order_by(ReviewReport.created_at.desc()).limit(200)).unique()
    return {
        "listing_reports": [{"id": r.id, "listing_id": r.listing_id, "listing_title": r.listing.title,
                             "listing_status": r.listing.status, "reason": r.reason, "details": r.details,
                             "status": r.status, "created_at": r.created_at} for r in lr],
        "review_reports": [{"id": r.id, "review_id": r.review_id, "book_id": r.review.book_id,
                            "review_excerpt": (r.review.body or "")[:200], "review_status": r.review.status,
                            "reason": r.reason, "details": r.details, "status": r.status, "created_at": r.created_at} for r in rr],
    }


class ReportResolution(BaseModel):
    status: Literal["resolved", "dismissed"]


@router.patch("/reports/{kind}/{report_id}")
def resolve_report(kind: Literal["listing", "review"], report_id: int, body: ReportResolution,
                   admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    model = ListingReport if kind == "listing" else ReviewReport
    rep = db.get(model, report_id)
    if not rep:
        raise not_found("Report")
    rep.status, rep.resolved_at = body.status, datetime.now(timezone.utc)
    audit(db, admin, f"{kind}_report_{body.status}", f"{kind}_report", rep.id)
    db.commit()
    return {"id": rep.id, "status": rep.status}


@router.get("/audit-log")
def audit_log(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(100))
    return [{"id": a.id, "actor_id": a.actor_id, "action": a.action, "target_type": a.target_type,
             "target_id": a.target_id, "details": a.details, "created_at": a.created_at} for a in rows]
