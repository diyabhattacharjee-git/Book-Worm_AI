from __future__ import annotations

import logging
import re

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.marketplace import ListingImage, MarketplaceListing
from app.models.social import (
    INTERACTION_WEIGHTS,
    AuditLog,
    RecommendationEvent,
    SearchQuery,
    UserBookInteraction,
)
from app.models.user import User, UserProfile
from app.schemas.users import (
    RESERVED_USERNAMES,
    PreferencesOut,
    PublicSellerOut,
    UserOut,
)
from app.services.uploads import delete_upload, public_url

logger = logging.getLogger("bookworm.users")


def upload_url(path: str | None) -> str | None:
    return public_url(path)


def user_out(user: User) -> UserOut:
    p = user.profile or UserProfile()
    return UserOut(
        id=user.id, email=user.email, username=user.username, has_password=user.has_password,
        email_verified=user.email_verified, display_name=user.display_name, role=user.role, is_seller=user.is_seller,
        is_demo=user.is_demo, created_at=user.created_at, bio=p.bio, avatar_url=upload_url(p.avatar_path),
        location_city=p.location_city, location_public=bool(p.location_public),
        allow_inquiries=p.allow_inquiries if p.allow_inquiries is not None else True, contact_note=p.contact_note,
        preferences=PreferencesOut(
            favorite_genres=p.favorite_genres or [], favorite_authors=p.favorite_authors or [],
            preferred_languages=p.preferred_languages or [], favorite_themes=p.favorite_themes or [],
            topics_to_explore=p.topics_to_explore or [], enjoyed_book_ids=p.enjoyed_book_ids or [],
            reading_goal_text=p.reading_goal_text, preferred_length=p.preferred_length,
            onboarding_completed=bool(p.onboarding_completed),
        ),
    )


def public_seller(db: Session, user: User) -> PublicSellerOut:
    p = user.profile
    counts = dict(db.execute(
        select(MarketplaceListing.status, func.count(MarketplaceListing.id))
        .where(MarketplaceListing.seller_id == user.id).group_by(MarketplaceListing.status)
    ).all())
    return PublicSellerOut(
        id=user.id, display_name=user.display_name, bio=p.bio if p else None,
        avatar_url=upload_url(p.avatar_path) if p else None,
        location_city=p.location_city if p and p.location_public else None,
        member_since=user.created_at, active_listings=counts.get("active", 0), sold_listings=counts.get("sold", 0),
        is_demo=user.is_demo,
    )


def record_interaction(db: Session, user_id: int, book_id: int, type_: str, *, replace_opposite: bool = True) -> None:
    """Store an interaction. interested/not_interested are mutually exclusive, so
    setting one removes the other (latest explicit feedback wins)."""
    opposite = {"interested": "not_interested", "not_interested": "interested"}
    if replace_opposite and type_ in opposite:
        db.execute(delete(UserBookInteraction).where(
            UserBookInteraction.user_id == user_id, UserBookInteraction.book_id == book_id,
            UserBookInteraction.type.in_((type_, opposite[type_])),
        ))
    if type_ in ("save", "dismiss"):
        db.execute(delete(UserBookInteraction).where(
            UserBookInteraction.user_id == user_id, UserBookInteraction.book_id == book_id,
            UserBookInteraction.type == type_,
        ))
    if type_ == "view":
        # Views are weak; keep at most one per book per user to avoid inflation.
        exists = db.scalar(select(UserBookInteraction.id).where(
            UserBookInteraction.user_id == user_id, UserBookInteraction.book_id == book_id,
            UserBookInteraction.type == "view"))
        if exists:
            return
    db.add(UserBookInteraction(user_id=user_id, book_id=book_id, type=type_, weight=INTERACTION_WEIGHTS[type_]))


def reset_learned_preferences(db: Session, user: User) -> dict:
    """Remove implicit signals and search history but keep ratings, shelf and reviews."""
    n_i = db.execute(delete(UserBookInteraction).where(UserBookInteraction.user_id == user.id)).rowcount
    n_s = db.execute(delete(SearchQuery).where(SearchQuery.user_id == user.id)).rowcount
    db.execute(delete(RecommendationEvent).where(RecommendationEvent.user_id == user.id))
    if user.profile:
        for f in ("favorite_genres", "favorite_authors", "preferred_languages", "favorite_themes",
                  "topics_to_explore", "enjoyed_book_ids"):
            setattr(user.profile, f, [])
        user.profile.preferred_length = None
        user.profile.reading_goal_text = None
        user.profile.onboarding_completed = False
    db.commit()
    return {"interactions_removed": n_i, "searches_removed": n_s}


def delete_user_files(db: Session, user: User) -> None:
    paths = list(db.scalars(select(ListingImage.path).join(MarketplaceListing)
                            .where(MarketplaceListing.seller_id == user.id)))
    if user.profile and user.profile.avatar_path:
        paths.append(user.profile.avatar_path)
    for path in paths:
        try:
            delete_upload(path)
        except OSError:
            logger.warning("could not delete upload", extra={"data": {"path": path}})


def audit(db: Session, actor: User | None, action: str, target_type: str, target_id: int | None, **details) -> None:
    db.add(AuditLog(actor_id=actor.id if actor else None, action=action, target_type=target_type,
                    target_id=target_id, details=details))


def unique_username(db: Session, seed: str) -> str:
    """Derive an available username from an email/name (used for Google sign-ups)."""
    base = re.sub(r"[^a-z0-9._]", "", seed.lower().split("@")[0]).strip("._")[:24] or "reader"
    if len(base) < 3:
        base = f"{base}reader"[:24]
    candidate, n = base, 1
    while candidate in RESERVED_USERNAMES or db.scalar(select(User.id).where(User.username == candidate)):
        n += 1
        candidate = f"{base}{n}"
    return candidate
