"""TEST-ONLY synthetic data (demo readers, ratings, sample listings).

Never used by the application: it exists so recommender, evaluation and price
intelligence tests have reproducible interaction data."""

from __future__ import annotations

import random
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.text import normalize_title
from app.models.book import Book
from app.models.marketplace import MarketplaceListing
from app.models.reading import BookshelfEntry
from app.models.social import INTERACTION_WEIGHTS, Review, UserBookInteraction
from app.models.user import User, UserProfile
from app.security.passwords import hash_password
from app.services.catalogue import find_book_by_isbn

# Synthetic taste profiles for demo users (genre -> affinity).
TASTE_PROFILES = {
    "tech": ["Programming", "Software Engineering", "Machine Learning", "Data Science", "Computer Science", "Python"],
    "thriller": ["Thriller", "Mystery", "Psychological Thriller", "Crime", "Horror"],
    "growth": ["Self-Help", "Productivity", "Psychology", "Personal Finance", "Inspirational"],
    "classics": ["Classics", "Literary Fiction", "Fiction", "Indian Literature"],
    "scifi": ["Science Fiction", "Fantasy", "Dystopian", "Young Adult", "Mythology"],
    "ideas": ["History", "Science", "Non-Fiction", "Economics", "Business", "Biography", "Memoir"],
}

DEMO_CITIES = ["Kolkata", "Bengaluru", "Mumbai", "Pune", "Delhi", "Chennai", "Hyderabad"]

# (isbn, condition, price INR, shipping INR or None, delivery, edition_text, description)
SAMPLE_LISTINGS = [
    ("9780735211292", "very_good", 260, 50, "both", "Hardcover", "Read once, no markings. Slight shelf wear on the dust jacket."),
    ("9780735211292", "good", 210, None, "pickup", None, "Paperback-style copy, a few highlighted lines in chapter 3."),
    ("9780735211292", "like_new", 340, 40, "shipping", "Hardcover", "Gift copy, unread."),
    ("9780735211292", "acceptable", 140, 60, "shipping", None, "Spine creased, cover corner bent, all pages intact."),
    ("9780735211292", "good", 230, 0, "both", None, "Free delivery within the city."),
    ("9780132350884", "good", 450, 60, "shipping", "1st edition", "Some pencil notes, binding solid."),
    ("9780132350884", "very_good", 520, None, "pickup", "1st edition", "Clean copy, minor cover scuffs."),
    ("9780132350884", "acceptable", 300, 50, "both", None, "Coffee stain on the bottom edge; readable."),
    ("9780062315007", "good", 150, 40, "both", None, "Paperback, light wear."),
    ("9780062315007", "like_new", 190, None, "pickup", None, "Brand-new condition."),
    ("9780857197689", "very_good", 230, 40, "shipping", None, "Read once."),
    ("9780857197689", "good", 180, None, "pickup", None, None),
    ("9781492032649", "good", 1400, 80, "shipping", "2nd edition", "2nd edition (TF2). Some underlining."),
    ("9781492032649", "very_good", 1650, None, "pickup", "2nd edition", "Barely used."),
    ("9781593279288", "good", 650, 60, "both", "2nd edition", "Exercises not filled in."),
    ("9781250301697", "very_good", 220, 40, "shipping", None, "Paperback."),
    ("9780307588371", "acceptable", 120, 50, "shipping", None, "Yellowed pages."),
    ("9780547928227", "good", 260, None, "pickup", None, "Illustrated cover."),
    ("9780441172719", "very_good", 380, 50, "both", None, None),
    ("9781455586691", "good", 240, 40, "shipping", None, "Some dog-eared pages."),
    ("9780374533557", "good", 330, None, "pickup", None, None),
    ("9780062316097", "very_good", 390, 50, "shipping", None, "Paperback, like new except spine."),
    ("9781449373320", "good", 1500, 80, "shipping", "1st edition", "Highlights in chapters 5-7."),
    ("9780143442295", "like_new", 210, None, "pickup", None, None),
]


def _demo_user(db: Session, idx: int, profile: str, password_hash: str) -> User:
    email = f"demo{idx:02d}@bookworm.local"
    user = db.scalar(select(User).where(User.email == email))
    if user:
        return user
    user = User(email=email, password_hash=password_hash, display_name=f"Demo Reader {idx:02d}", is_demo=True)
    user.profile = UserProfile(
        location_city=DEMO_CITIES[idx % len(DEMO_CITIES)],
        location_public=True,
        favorite_genres=TASTE_PROFILES[profile][:2],
        bio=f"Synthetic demo account ({profile} taste profile).",
    )
    db.add(user)
    db.flush()
    return user


def seed_demo_activity(db: Session, n_users: int = 36) -> str | None:
    """Create synthetic demo readers with ratings, shelves and interactions.
    Returns the generated demo password (printed once by the CLI)."""
    if db.scalar(select(func.count(User.id)).where(User.is_demo.is_(True))):
        return None
    rng = random.Random(42)
    password = secrets.token_urlsafe(9)
    pw_hash = hash_password(password)
    books = list(db.scalars(select(Book)))
    genre_names = {b.id: {g.name for g in b.genres} for b in books}
    now = datetime.now(timezone.utc)
    profiles = list(TASTE_PROFILES)
    for i in range(1, n_users + 1):
        profile = profiles[(i - 1) % len(profiles)]
        secondary = rng.choice([p for p in profiles if p != profile])
        user = _demo_user(db, i, profile, pw_hash)

        def affinity(book_id: int) -> float:
            g = genre_names[book_id]
            return 1.0 * len(g & set(TASTE_PROFILES[profile])) + 0.4 * len(g & set(TASTE_PROFILES[secondary]))

        ranked = sorted(books, key=lambda b: affinity(b.id) + rng.random() * 0.8, reverse=True)
        liked = ranked[: rng.randint(7, 12)]
        others = rng.sample(ranked[20:], k=3)
        for j, book in enumerate(liked + others):
            fit = affinity(book.id)
            rating = 5 if fit >= 2 else 4 if fit >= 1 else rng.choice([2, 3])
            if rng.random() < 0.15:
                rating = max(1, rating - 1)
            ts = now - timedelta(days=rng.randint(1, 300))
            db.add(Review(user_id=user.id, book_id=book.id, rating=rating, created_at=ts, updated_at=ts,
                          body=None))
            status = "read" if j < len(liked) - 2 else "reading"
            db.add(BookshelfEntry(user_id=user.id, book_id=book.id, status=status,
                                  pages_read=(book.page_count or 0) if status == "read" else 0))
            db.add(UserBookInteraction(user_id=user.id, book_id=book.id, type=f"shelf_{status}",
                                       weight=INTERACTION_WEIGHTS[f"shelf_{status}"], created_at=ts))
    db.commit()
    return password


def seed_sample_listings(db: Session) -> int:
    if db.scalar(select(func.count(MarketplaceListing.id)).where(MarketplaceListing.is_sample.is_(True))):
        return 0
    sellers = list(db.scalars(select(User).where(User.is_demo.is_(True)).order_by(User.id).limit(8)))
    if not sellers:
        return 0
    now = datetime.now(timezone.utc)
    count = 0
    for i, (isbn, cond, price, ship, delivery, edition, desc) in enumerate(SAMPLE_LISTINGS):
        book = find_book_by_isbn(db, isbn)
        if not book:
            continue
        seller = sellers[i % len(sellers)]
        seller.is_seller = True
        created = now - timedelta(days=(i * 3) % 40, hours=i)
        db.add(MarketplaceListing(
            seller_id=seller.id, book_id=book.id,
            edition_id=book.editions[0].id if book.editions else None,
            title=book.title, normalized_title=normalize_title(book.title),
            author=", ".join(book.author_names) or "Unknown", isbn=isbn, edition_text=edition,
            published_year=None, description=desc, condition=cond,
            price_amount=Decimal(price), currency="INR",
            shipping_cost=Decimal(ship) if ship is not None else None,
            delivery=delivery, location_city=seller.profile.location_city if seller.profile else None,
            location_public=True, allow_inquiries=True, status="active", is_sample=True,
            created_at=created, updated_at=created,
        ))
        count += 1
    db.commit()
    return count


def seed_test_data(db: Session) -> None:
    seed_demo_activity(db)
    seed_sample_listings(db)
