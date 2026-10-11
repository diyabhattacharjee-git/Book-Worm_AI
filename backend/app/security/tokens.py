"""Signed session tokens stored in an HttpOnly cookie.

The token carries the user's `token_version`; bumping that column (logout
everywhere, password change, deletion) invalidates all outstanding tokens."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Response

from app.core.config import Settings, get_secret_key

COOKIE_NAME = "bw_session"
ALGORITHM = "HS256"


def create_session_token(user_id: int, token_version: int, settings: Settings) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "ver": token_version,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.session_ttl_hours)).timestamp()),
    }
    return jwt.encode(payload, get_secret_key(settings), algorithm=ALGORITHM)


def decode_session_token(token: str, settings: Settings) -> dict | None:
    try:
        return jwt.decode(token, get_secret_key(settings), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", secure=settings.is_production, httponly=True, samesite="lax")


def create_purpose_token(subject: str, purpose: str, settings: Settings, minutes: int = 20, **claims) -> str:
    """Short-lived signed token proving a step was completed (e.g. email verified for sign-up)."""
    now = datetime.now(timezone.utc)
    payload = {"sub": subject, "purpose": purpose, "iat": int(now.timestamp()),
               "exp": int((now + timedelta(minutes=minutes)).timestamp()), **claims}
    return jwt.encode(payload, get_secret_key(settings), algorithm=ALGORITHM)


def decode_purpose_token(token: str, purpose: str, settings: Settings) -> dict | None:
    payload = decode_session_token(token, settings)
    if not payload or payload.get("purpose") != purpose:
        return None
    return payload
