from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.ratelimit import rate_limit
from app.db.session import get_db
from app.models.reading import BookshelfEntry, Conversation
from app.models.social import SearchQuery, UserBookInteraction
from app.models.user import UNUSABLE_PASSWORD, EmailOTP, User, UserProfile
from app.schemas.users import (
    CodeVerifyIn,
    DeleteAccountIn,
    EmailIn,
    GoogleIn,
    LoginIn,
    PasswordChangeIn,
    PasswordResetIn,
    PreferencesIn,
    ProfileUpdateIn,
    SignupCompleteIn,
    UserOut,
    validate_username,
)
from app.security.deps import get_current_user, get_current_user_optional
from app.security.google import GoogleAuthError, verify_id_token
from app.security.passwords import DUMMY_HASH, hash_password, verify_password
from app.security.tokens import (
    clear_session_cookie,
    create_purpose_token,
    create_session_token,
    decode_purpose_token,
    set_session_cookie,
)
from app.services import otp, uploads
from app.services.users import (
    audit,
    delete_user_files,
    reset_learned_preferences,
    unique_username,
    user_out,
)

router = APIRouter(tags=["auth & users"])


def _start_session(response: Response, user: User) -> None:
    settings = get_settings()
    set_session_cookie(response, create_session_token(user.id, user.token_version, settings), settings)


def _login_ok(db: Session, response: Response, user: User) -> UserOut:
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been suspended")
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    _start_session(response, user)
    return user_out(user)


@router.get("/auth/config")
def auth_config():
    """Sign-in options the frontend should offer."""
    return {"google_client_id": get_settings().google_client_id or None}


@router.get("/auth/username-available")
def username_available(username: str = Query(..., max_length=40), db: Session = Depends(get_db)):
    try:
        name = validate_username(username)
    except ValueError as exc:
        return {"available": False, "username": username, "reason": str(exc)}
    taken = db.scalar(select(User.id).where(User.username == name)) is not None
    return {"available": not taken, "username": name, "reason": "That username is taken" if taken else None}


# ------------------------------------------------------------------ sign-up
@router.post("/auth/signup/start", status_code=202, dependencies=[Depends(rate_limit("signup_start", 8, 900))])
def signup_start(body: EmailIn, db: Session = Depends(get_db)):
    """Step 1: email a 6-digit verification code.

    If the email already has an account we email a short note instead, so the
    response never reveals which emails are registered."""
    existing = db.scalar(select(User).where(User.email == body.email))
    if existing:
        otp.notify(body.email, "You already have a BookWorm account",
                   "Someone (hopefully you) tried to sign up with this email, but it already has an account.\n"
                   f"Sign in with your username ({existing.username or 'shown in Settings'}) or ask for a sign-in code.\n\n"
                   "— BookWorm")
    else:
        otp.issue(db, body.email, "signup")
    return {"detail": "If this email can be used, we've sent a 6-digit code to it.", "email": body.email}


@router.post("/auth/signup/verify", dependencies=[Depends(rate_limit("otp_verify", 20, 900))])
def signup_verify(body: CodeVerifyIn, db: Session = Depends(get_db)):
    """Step 2: check the code and return a short-lived token for step 3."""
    record = otp.verify(db, body.email, "signup", body.code)
    token = create_purpose_token(body.email, "signup", get_settings(), minutes=30, otp=record.id)
    return {"verification_token": token, "email": body.email}


@router.post("/auth/signup/complete", response_model=UserOut, status_code=201,
             dependencies=[Depends(rate_limit("signup_complete", 10, 900))])
def signup_complete(body: SignupCompleteIn, response: Response, db: Session = Depends(get_db)):
    """Step 3: choose a username, display name and password; creates the account and signs in."""
    payload = decode_purpose_token(body.verification_token, "signup", get_settings())
    record = db.get(EmailOTP, payload.get("otp", 0)) if payload else None
    if not payload or not record or record.email != payload["sub"] or not record.verified_at or record.consumed_at:
        raise HTTPException(status_code=400, detail="Your verification has expired. Please start again.")
    email = payload["sub"]
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists. Please sign in.")
    if db.scalar(select(User.id).where(User.username == body.username)):
        raise HTTPException(status_code=409, detail="That username is taken")
    # Role is never taken from the request: sign-up always creates a regular user.
    user = User(email=email, username=body.username, password_hash=hash_password(body.password),
                display_name=body.display_name, email_verified=True)
    user.profile = UserProfile()
    db.add(user)
    otp.consume(db, record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="That username or email is already in use")
    _start_session(response, user)
    return user_out(user)


# ------------------------------------------------------------------- log in
@router.post("/auth/login", response_model=UserOut, dependencies=[Depends(rate_limit("login", 10, 300))])
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    """Log in with username or email, plus password."""
    ident = body.identifier.strip().lower()
    field = User.email if "@" in ident else User.username
    user = db.scalar(select(User).where(field == ident))
    # Always run one bcrypt check so response time doesn't reveal whether the account exists.
    ok = verify_password(body.password, user.password_hash if user and user.has_password else DUMMY_HASH)
    if not user or not ok:
        raise HTTPException(status_code=401, detail="Incorrect username/email or password")
    return _login_ok(db, response, user)


@router.post("/auth/login/code/start", status_code=202, dependencies=[Depends(rate_limit("login_code", 8, 900))])
def login_code_start(body: EmailIn, db: Session = Depends(get_db)):
    """Passwordless sign-in: email a one-time code (only sent if the account exists)."""
    user = db.scalar(select(User).where(User.email == body.email))
    if user and user.is_active:
        otp.issue(db, body.email, "login")
    return {"detail": "If an account uses this email, we've sent a 6-digit sign-in code.", "email": body.email}


@router.post("/auth/login/code/verify", response_model=UserOut, dependencies=[Depends(rate_limit("otp_verify", 20, 900))])
def login_code_verify(body: CodeVerifyIn, response: Response, db: Session = Depends(get_db)):
    record = otp.verify(db, body.email, "login", body.code)
    user = db.scalar(select(User).where(User.email == body.email))
    if not user:
        raise HTTPException(status_code=400, detail="That code is incorrect or has expired. Request a new one.")
    otp.consume(db, record)
    user.email_verified = True
    return _login_ok(db, response, user)


@router.post("/auth/password/forgot", status_code=202, dependencies=[Depends(rate_limit("forgot", 8, 900))])
def password_forgot(body: EmailIn, db: Session = Depends(get_db)):
    """Email a code to set a new password (also how Google-only accounts add a password)."""
    user = db.scalar(select(User).where(User.email == body.email))
    if user and user.is_active:
        otp.issue(db, body.email, "reset")
    return {"detail": "If an account uses this email, we've sent a 6-digit code to set a new password.",
            "email": body.email}


@router.post("/auth/password/reset", response_model=UserOut, dependencies=[Depends(rate_limit("otp_verify", 20, 900))])
def password_reset(body: PasswordResetIn, response: Response, db: Session = Depends(get_db)):
    record = otp.verify(db, body.email, "reset", body.code)
    user = db.scalar(select(User).where(User.email == body.email))
    if not user:
        raise HTTPException(status_code=400, detail="That code is incorrect or has expired. Request a new one.")
    otp.consume(db, record)
    user.password_hash = hash_password(body.new_password)
    user.email_verified = True
    user.token_version += 1  # sign out every other session
    return _login_ok(db, response, user)


@router.post("/auth/google", response_model=UserOut, dependencies=[Depends(rate_limit("google", 20, 900))])
def google_sign_in(body: GoogleIn, response: Response, db: Session = Depends(get_db)):
    """Sign in (or sign up) with a Google ID token from Google Identity Services."""
    try:
        ident = verify_id_token(body.credential)
    except GoogleAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    user = db.scalar(select(User).where(User.google_sub == ident.sub))
    if user is None:
        user = db.scalar(select(User).where(User.email == ident.email))
        if user is not None:
            user.google_sub = ident.sub  # Google verified this email, so link it to the existing account
        else:
            user = User(email=ident.email, username=unique_username(db, ident.email), password_hash=UNUSABLE_PASSWORD,
                        display_name=(ident.name or ident.email.split("@")[0])[:60], google_sub=ident.sub)
            user.profile = UserProfile()
            db.add(user)
    user.email_verified = True
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Could not link this Google account")
    return _login_ok(db, response, user)


@router.post("/auth/logout", status_code=204)
def logout(response: Response, everywhere: bool = False, user: User | None = Depends(get_current_user_optional),
           db: Session = Depends(get_db)):
    if user and everywhere:
        user.token_version += 1
        db.commit()
    clear_session_cookie(response, get_settings())
    response.status_code = 204
    return response


@router.get("/auth/session")
def session(user: User | None = Depends(get_current_user_optional)):
    """Session probe for the frontend: 200 with `user: null` when logged out (no 401 noise)."""
    return {"user": user_out(user) if user else None}


@router.get("/users/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@router.patch("/users/me", response_model=UserOut)
def update_me(body: ProfileUpdateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    new_username = data.pop("username", None)
    if new_username:
        try:
            new_username = validate_username(new_username)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if new_username != user.username:
            if db.scalar(select(User.id).where(User.username == new_username)):
                raise HTTPException(status_code=409, detail="That username is taken")
            user.username = new_username
    if "display_name" in data and data["display_name"]:
        user.display_name = " ".join(data.pop("display_name").split())
    else:
        data.pop("display_name", None)
    if user.profile is None:
        user.profile = UserProfile()
    for k, v in data.items():
        setattr(user.profile, k, v.strip() if isinstance(v, str) else v)
    db.commit()
    return user_out(user)


@router.patch("/users/me/preferences", response_model=UserOut)
def update_preferences(body: PreferencesIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.profile is None:
        user.profile = UserProfile()
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None or k in ("preferred_length", "reading_goal_text"):
            setattr(user.profile, k, v)
    db.commit()
    return user_out(user)


@router.post("/users/me/avatar", response_model=UserOut, dependencies=[Depends(rate_limit("upload", 30, 3600))])
async def upload_avatar(file: UploadFile = File(...), user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    data = await uploads.read_limited(file)
    path = uploads.save_image(data, "avatars")
    if user.profile is None:
        user.profile = UserProfile()
    old = user.profile.avatar_path
    user.profile.avatar_path = path
    db.commit()
    uploads.delete_upload(old)
    return user_out(user)


@router.delete("/users/me/avatar", response_model=UserOut)
def delete_avatar(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.profile and user.profile.avatar_path:
        uploads.delete_upload(user.profile.avatar_path)
        user.profile.avatar_path = None
        db.commit()
    return user_out(user)


@router.post("/users/me/password", status_code=204, dependencies=[Depends(rate_limit("password", 10, 3600))])
def change_password(body: PasswordChangeIn, response: Response, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not user.has_password:
        raise HTTPException(status_code=400, detail="Your account has no password yet. Use “Set a password” to get an email code.")
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # sign out other sessions
    db.commit()
    set_session_cookie(response, create_session_token(user.id, user.token_version, get_settings()), get_settings())
    response.status_code = 204
    return response


@router.post("/users/me/reset-recommendations")
def reset_recommendations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Forget learned signals (views, saves, dismissals, searches, onboarding answers).
    Ratings, reviews and the bookshelf are kept."""
    return reset_learned_preferences(db, user)


@router.delete("/users/me/reading-history")
def delete_reading_history(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Remove bookshelf entries, interactions, searches and assistant conversations."""
    counts = {
        "bookshelf_entries": db.execute(delete(BookshelfEntry).where(BookshelfEntry.user_id == user.id)).rowcount,
        "interactions": db.execute(delete(UserBookInteraction).where(UserBookInteraction.user_id == user.id)).rowcount,
        "searches": db.execute(delete(SearchQuery).where(SearchQuery.user_id == user.id)).rowcount,
    }
    for conv in db.scalars(select(Conversation).where(Conversation.user_id == user.id)):
        db.delete(conv)
    db.commit()
    return counts


@router.delete("/users/me", status_code=204)
def delete_account(body: DeleteAccountIn, response: Response, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Permanently delete the account. Listings, reviews, shelves, conversations,
    favourites, inquiries and uploaded images are deleted with it (FK cascades);
    reports filed by the user are kept but anonymised (SET NULL)."""
    if user.has_password:
        if not body.password or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=400, detail="Password is incorrect")
    elif (body.confirm_username or "").strip().lower() != (user.username or ""):
        raise HTTPException(status_code=400, detail="Type your username exactly to confirm")
    delete_user_files(db, user)
    audit(db, None, "account_deleted", "user", user.id)
    db.delete(user)
    db.commit()
    clear_session_cookie(response, get_settings())
    response.status_code = 204
    return response
