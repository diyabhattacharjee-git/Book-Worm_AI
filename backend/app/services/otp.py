"""Email one-time codes for sign-up, passwordless login and password reset.

* 6-digit codes from `secrets`, valid for OTP_TTL_MINUTES, at most OTP_MAX_ATTEMPTS
  guesses each; only an HMAC-SHA256 of the code is stored.
* A new code replaces any earlier unused one for the same email and purpose.
* Resending is limited to one code per OTP_RESEND_SECONDS and 6 per hour per email.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_secret_key, get_settings
from app.db.base import as_utc
from app.models.user import EmailOTP
from app.services.mailer import EmailNotConfigured, EmailSendFailed, send_email

PURPOSES = ("signup", "login", "reset")
MAX_PER_HOUR = 6

SUBJECTS = {
    "signup": "Your BookWorm verification code",
    "login": "Your BookWorm sign-in code",
    "reset": "Reset your BookWorm password",
}
INTROS = {
    "signup": "Use this code to verify your email and finish creating your BookWorm account:",
    "login": "Use this code to sign in to BookWorm:",
    "reset": "Use this code to set a new BookWorm password:",
}


def _hash(email: str, purpose: str, code: str) -> str:
    key = get_secret_key(get_settings()).encode()
    return hmac.new(key, f"{purpose}:{email}:{code}".encode(), hashlib.sha256).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def issue(db: Session, email: str, purpose: str) -> None:
    """Create a code and email it. Raises HTTPException for throttling/delivery problems."""
    s = get_settings()
    now = _now()
    last = db.scalar(select(EmailOTP).where(EmailOTP.email == email, EmailOTP.purpose == purpose)
                     .order_by(EmailOTP.created_at.desc()).limit(1))
    if last and (now - as_utc(last.created_at)).total_seconds() < s.otp_resend_seconds:
        wait = int(s.otp_resend_seconds - (now - as_utc(last.created_at)).total_seconds()) + 1
        raise HTTPException(status_code=429, detail=f"Please wait {wait} seconds before requesting another code.",
                            headers={"Retry-After": str(wait)})
    recent = db.scalar(select(func.count(EmailOTP.id)).where(
        EmailOTP.email == email, EmailOTP.created_at >= now - timedelta(hours=1)))
    if recent and recent >= MAX_PER_HOUR:
        raise HTTPException(status_code=429, detail="Too many codes requested. Try again in an hour.")
    db.execute(update(EmailOTP).where(EmailOTP.email == email, EmailOTP.purpose == purpose,
                                      EmailOTP.consumed_at.is_(None)).values(consumed_at=now))
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(EmailOTP(email=email, purpose=purpose, code_hash=_hash(email, purpose, code),
                    expires_at=now + timedelta(minutes=s.otp_ttl_minutes)))
    db.commit()
    text = (f"{INTROS[purpose]}\n\n    {code}\n\nThe code expires in {s.otp_ttl_minutes} minutes. "
            "If you didn't request it, you can ignore this email.\n\n— BookWorm")
    html = (f"<p>{INTROS[purpose]}</p><p style=\"font-size:28px;font-weight:700;letter-spacing:6px\">{code}</p>"
            f"<p>The code expires in {s.otp_ttl_minutes} minutes. If you didn't request it, you can ignore this email.</p>")
    _deliver(email, SUBJECTS[purpose], text, html)


def notify(email: str, subject: str, text: str) -> None:
    _deliver(email, subject, text, None)


def _deliver(email: str, subject: str, text: str, html: str | None) -> None:
    try:
        send_email(email, subject, text, html)
    except EmailNotConfigured:
        raise HTTPException(status_code=503, detail="Email delivery isn't available right now. Please try again later.")
    except EmailSendFailed:
        raise HTTPException(status_code=502, detail="We couldn't send the email. Check the address and try again.")


def verify(db: Session, email: str, purpose: str, code: str) -> EmailOTP:
    """Check a code; marks it verified. Raises HTTPException(400) on any failure."""
    s = get_settings()
    otp = db.scalar(select(EmailOTP).where(EmailOTP.email == email, EmailOTP.purpose == purpose,
                                           EmailOTP.consumed_at.is_(None))
                    .order_by(EmailOTP.created_at.desc()).limit(1))
    invalid = HTTPException(status_code=400, detail="That code is incorrect or has expired. Request a new one.")
    if otp is None or as_utc(otp.expires_at) < _now() or otp.attempts >= s.otp_max_attempts:
        raise invalid
    if not hmac.compare_digest(otp.code_hash, _hash(email, purpose, code.strip())):
        otp.attempts += 1
        db.commit()
        left = s.otp_max_attempts - otp.attempts
        if left <= 0:
            raise invalid
        raise HTTPException(status_code=400, detail=f"That code is incorrect. {left} attempt{'s' if left != 1 else ''} left.")
    otp.verified_at = _now()
    db.commit()
    return otp


def consume(db: Session, otp: EmailOTP) -> None:
    otp.consumed_at = _now()
