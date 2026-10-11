from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, utcnow

ROLE_USER = "user"
ROLE_ADMIN = "admin"
UNUSABLE_PASSWORD = "!"  # never matches any password


class User(TimestampMixin, Base):
    """A single account can browse, read, buy and sell. `is_seller` flips on the
    first time the user creates a listing; `role` is only ever `admin` when set
    through the CLI (never through public registration)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True, nullable=False)
    # Login handle (lowercase letters, digits, "." and "_"). Unique; always set for new accounts.
    username: Mapped[str | None] = mapped_column(String(30), unique=True, index=True)
    # bcrypt hash, or UNUSABLE_PASSWORD for accounts created through Google that never set one.
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(60), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default=ROLE_USER, nullable=False)
    is_seller: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Demo accounts created by the seed command; excluded from evaluation by default.
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Incrementing this invalidates every issued session token (logout everywhere).
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    profile: Mapped[UserProfile] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan", lazy="joined"
    )

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def has_password(self) -> bool:
        return self.password_hash.startswith("$2")


class UserProfile(TimestampMixin, Base):
    """Public-facing profile plus optional onboarding/recommendation preferences.

    Preferences are stored as JSON lists here (rather than separate join tables)
    because they are small, user-owned, always read together and never queried
    across users."""

    __tablename__ = "user_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    bio: Mapped[str | None] = mapped_column(Text)
    avatar_path: Mapped[str | None] = mapped_column(String(255))
    location_city: Mapped[str | None] = mapped_column(String(80))
    location_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    allow_inquiries: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Free text the seller chooses to reveal *only* in replies to inquiries.
    contact_note: Mapped[str | None] = mapped_column(String(200))

    favorite_genres: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    favorite_authors: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    preferred_languages: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    favorite_themes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    topics_to_explore: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    enjoyed_book_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    reading_goal_text: Mapped[str | None] = mapped_column(String(200))
    preferred_length: Mapped[str | None] = mapped_column(String(16))  # short|medium|long|any
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped[User] = relationship(back_populates="profile")


class EmailOTP(Base):
    """A one-time code sent by email. Only an HMAC of the code is stored.

    purpose: signup | login | reset. `verified_at` is set when the code is entered
    correctly; `consumed_at` when the follow-up action (e.g. account creation) used it."""

    __tablename__ = "email_otps"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), index=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(12), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True, nullable=False)
