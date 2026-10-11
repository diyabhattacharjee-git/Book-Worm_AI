"""Verify Google Identity Services ID tokens (free; needs GOOGLE_CLIENT_ID)."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings


class GoogleAuthError(Exception):
    pass


@dataclass
class GoogleIdentity:
    sub: str
    email: str
    name: str | None


def verify_id_token(credential: str) -> GoogleIdentity:
    client_id = get_settings().google_client_id
    if not client_id:
        raise GoogleAuthError("Google sign-in is not enabled")
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    try:
        info = id_token.verify_oauth2_token(credential, google_requests.Request(), client_id)
    except ValueError as exc:  # bad signature, wrong audience, expired...
        raise GoogleAuthError("Google sign-in could not be verified") from exc
    if info.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise GoogleAuthError("Unexpected token issuer")
    if not info.get("email") or not info.get("email_verified"):
        raise GoogleAuthError("Your Google account email isn't verified")
    return GoogleIdentity(sub=str(info["sub"]), email=str(info["email"]).lower(), name=info.get("name"))
