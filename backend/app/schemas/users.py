from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

USERNAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._]{1,28})[a-z0-9]$")
RESERVED_USERNAMES = {"admin", "administrator", "root", "support", "bookworm", "system", "moderator", "api"}


def validate_username(v: str) -> str:
    v = v.strip().lower()
    if not USERNAME_RE.fullmatch(v) or ".." in v:
        raise ValueError("Use 3-30 lowercase letters, numbers, dots or underscores (not at the start or end)")
    if v in RESERVED_USERNAMES:
        raise ValueError("That username is reserved")
    return v


def validate_password(v: str) -> str:
    if v.isdigit() or v.isalpha():
        raise ValueError("Password must mix letters with numbers or symbols")
    return v


class EmailIn(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.strip().lower()


class CodeVerifyIn(EmailIn):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class SignupCompleteIn(BaseModel):
    verification_token: str = Field(min_length=20, max_length=2000)
    username: str = Field(min_length=3, max_length=30)
    display_name: str = Field(min_length=2, max_length=60)
    password: str = Field(min_length=8, max_length=256)

    _u = field_validator("username")(validate_username)
    _p = field_validator("password")(validate_password)

    @field_validator("display_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("Display name is too short")
        return v


class LoginIn(BaseModel):
    identifier: str = Field(min_length=1, max_length=254, description="Username or email")
    password: str = Field(min_length=1, max_length=256)


class PasswordResetIn(CodeVerifyIn):
    new_password: str = Field(min_length=8, max_length=256)

    _p = field_validator("new_password")(validate_password)


class GoogleIn(BaseModel):
    credential: str = Field(min_length=20, max_length=5000)


class PreferencesOut(BaseModel):
    favorite_genres: list[str] = []
    favorite_authors: list[str] = []
    preferred_languages: list[str] = []
    favorite_themes: list[str] = []
    topics_to_explore: list[str] = []
    enjoyed_book_ids: list[int] = []
    reading_goal_text: str | None = None
    preferred_length: Literal["short", "medium", "long", "any"] | None = None
    onboarding_completed: bool = False


class PreferencesIn(BaseModel):
    favorite_genres: list[str] | None = Field(default=None, max_length=20)
    favorite_authors: list[str] | None = Field(default=None, max_length=20)
    preferred_languages: list[str] | None = Field(default=None, max_length=10)
    favorite_themes: list[str] | None = Field(default=None, max_length=20)
    topics_to_explore: list[str] | None = Field(default=None, max_length=20)
    enjoyed_book_ids: list[int] | None = Field(default=None, max_length=30)
    reading_goal_text: str | None = Field(default=None, max_length=200)
    preferred_length: Literal["short", "medium", "long", "any"] | None = None
    onboarding_completed: bool | None = None

    @field_validator("favorite_genres", "favorite_authors", "preferred_languages", "favorite_themes",
                     "topics_to_explore")
    @classmethod
    def _clean_list(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        out: list[str] = []
        for item in v:
            s = " ".join(str(item).split())[:60]
            if s and s.lower() not in {o.lower() for o in out}:
                out.append(s)
        return out


class UserOut(BaseModel):
    id: int
    email: str
    username: str | None
    has_password: bool
    email_verified: bool
    display_name: str
    role: str
    is_seller: bool
    is_demo: bool
    created_at: datetime
    bio: str | None = None
    avatar_url: str | None = None
    location_city: str | None = None
    location_public: bool = False
    allow_inquiries: bool = True
    contact_note: str | None = None
    preferences: PreferencesOut


class ProfileUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=60)
    username: str | None = Field(default=None, min_length=3, max_length=30)
    bio: str | None = Field(default=None, max_length=500)
    location_city: str | None = Field(default=None, max_length=80)
    location_public: bool | None = None
    allow_inquiries: bool | None = None
    contact_note: str | None = Field(default=None, max_length=200)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)

    _p = field_validator("new_password")(validate_password)


class DeleteAccountIn(BaseModel):
    # Password for accounts that have one; Google-only accounts confirm by typing their username.
    password: str | None = Field(default=None, max_length=256)
    confirm_username: str | None = Field(default=None, max_length=30)


class PublicSellerOut(BaseModel):
    id: int
    display_name: str
    bio: str | None
    avatar_url: str | None
    location_city: str | None  # only when the seller made it public
    member_since: datetime
    active_listings: int
    sold_listings: int
    is_demo: bool
