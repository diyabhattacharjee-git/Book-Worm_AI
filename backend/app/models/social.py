"""Reviews, ratings, interactions and recommendation telemetry."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, utcnow
from app.models.user import User


class Review(TimestampMixin, Base):
    """Rating + optional review text. One per (user, book): re-rating updates the
    same row, which is how duplicate ratings are prevented (DB unique constraint).

    The spec lists Rating and Review separately; they are merged because a rating
    without text is simply a Review with an empty body."""

    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("user_id", "book_id"),
        CheckConstraint("rating >= 1 AND rating <= 5", name="rating_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True, nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    # visible | hidden (by moderator)
    status: Mapped[str] = mapped_column(String(16), default="visible", nullable=False, index=True)
    helpful_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    user: Mapped[User] = relationship(lazy="joined")


class ReviewHelpfulVote(Base):
    __tablename__ = "review_helpful_votes"
    __table_args__ = (UniqueConstraint("user_id", "review_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    review_id: Mapped[int] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ReviewReport(Base):
    __tablename__ = "review_reports"
    __table_args__ = (UniqueConstraint("reporter_id", "review_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    reporter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    review_id: Mapped[int] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True, nullable=False)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    details: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False, index=True)  # open|resolved|dismissed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    review: Mapped[Review] = relationship(lazy="joined")


# Interaction types and their default implicit-feedback weights. Negative values
# push recommendations away from similar books. Documented in docs/RECOMMENDER.md.
INTERACTION_WEIGHTS: dict[str, float] = {
    "view": 0.3,
    "save": 1.0,
    "interested": 1.0,
    "not_interested": -1.5,
    "dismiss": -0.7,
    "shelf_want": 0.8,
    "shelf_reading": 1.2,
    "shelf_read": 1.5,
    "shelf_abandoned": -0.5,
}


class UserBookInteraction(Base):
    __tablename__ = "user_book_interactions"
    __table_args__ = (Index("ix_ubi_user_book_type", "user_id", "book_id", "type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(24), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True, nullable=False)


class SearchQuery(Base):
    """Recent searches feed the content profile (as free text), nothing else."""

    __tablename__ = "search_queries"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    query: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True, nullable=False)


class RecommendationEvent(Base):
    """Logged when recommendations are served / acted on (for usage analytics)."""

    __tablename__ = "recommendation_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    event: Mapped[str] = mapped_column(String(16), nullable=False)  # shown|saved|dismissed|rated|opened
    strategy: Mapped[str] = mapped_column(String(24), nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True, nullable=False)


class RecommendationEvaluationRun(Base):
    __tablename__ = "recommendation_evaluation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(24), nullable=False)  # ok|insufficient_data
    k: Mapped[int] = mapped_column(Integer, nullable=False)
    include_demo: Mapped[bool] = mapped_column(default=False, nullable=False)
    n_users: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    results: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True, nullable=False)
