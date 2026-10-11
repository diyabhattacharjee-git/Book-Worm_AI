from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models.user import EmailOTP, User
from app.security import google
from app.services.mailer import OUTBOX
from tests.conftest import HEADERS, last_code, register


def new_client() -> TestClient:
    c = TestClient(app)
    c.headers.update(HEADERS)
    return c


def test_signup_requires_email_code_then_password(client, db):
    email = "otp-flow@example.com"
    r = client.post("/api/auth/signup/start", json={"email": email})
    assert r.status_code == 202
    code = last_code(email)
    stored = db.scalar(select(EmailOTP).where(EmailOTP.email == email))
    assert stored.code_hash != code and len(stored.code_hash) == 64  # only an HMAC is stored
    assert client.post("/api/auth/signup/verify", json={"email": email, "code": "000000" if code != "000000" else "111111"}).status_code == 400
    token = client.post("/api/auth/signup/verify", json={"email": email, "code": code}).json()["verification_token"]
    assert client.get("/api/users/me").status_code == 401  # not signed in until the password is set
    r = client.post("/api/auth/signup/complete", json={"verification_token": token, "username": "otp.reader",
                                                       "display_name": "Otp Reader", "password": "s3cure-Passw0rd"})
    assert r.status_code == 201
    me = client.get("/api/users/me").json()
    assert me["username"] == "otp.reader" and me["email_verified"] and me["has_password"] and me["role"] == "user"
    # The verification token is single-use
    again = new_client().post("/api/auth/signup/complete", json={"verification_token": token, "username": "otp.reader2",
                                                                 "display_name": "Second Try", "password": "s3cure-Passw0rd"})
    assert again.status_code == 400


def test_signup_cannot_skip_verification(client):
    from app.core.config import get_settings
    from app.security.tokens import create_purpose_token

    forged = create_purpose_token("nocode@example.com", "signup", get_settings(), otp=999999)
    r = client.post("/api/auth/signup/complete", json={"verification_token": forged, "username": "nocode",
                                                       "display_name": "No Code", "password": "s3cure-Passw0rd"})
    assert r.status_code == 400
    r = client.post("/api/auth/signup/complete", json={"verification_token": "x" * 40, "username": "nocode",
                                                       "display_name": "No Code", "password": "s3cure-Passw0rd"})
    assert r.status_code == 400


def test_code_attempts_are_limited(client):
    email = "brute@example.com"
    client.post("/api/auth/signup/start", json={"email": email})
    code = last_code(email)
    wrong = "123456" if code != "123456" else "654321"
    for _ in range(5):
        client.post("/api/auth/signup/verify", json={"email": email, "code": wrong})
    assert client.post("/api/auth/signup/verify", json={"email": email, "code": code}).status_code == 400


def test_expired_code_rejected(client, db):
    email = "late@example.com"
    client.post("/api/auth/signup/start", json={"email": email})
    code = last_code(email)
    row = db.scalar(select(EmailOTP).where(EmailOTP.email == email))
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert client.post("/api/auth/signup/verify", json={"email": email, "code": code}).status_code == 400


def test_resend_cooldown(client):
    email = "resend@example.com"
    assert client.post("/api/auth/signup/start", json={"email": email}).status_code == 202
    assert client.post("/api/auth/signup/start", json={"email": email}).status_code == 429


def test_signup_start_does_not_reveal_existing_accounts(client):
    info = register(new_client(), "Existing")
    before = len(OUTBOX)
    r = client.post("/api/auth/signup/start", json={"email": info["email"]})
    assert r.status_code == 202 and "If this email can be used" in r.json()["detail"]
    assert len(OUTBOX) == before + 1 and "already has an account" in OUTBOX[-1]["text"]


def test_login_with_username_or_email(client):
    info = register(new_client(), "Bob")
    assert client.post("/api/auth/login", json={"identifier": info["username"], "password": info["password"]}).status_code == 200
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/users/me").status_code == 401
    r = client.post("/api/auth/login", json={"identifier": info["email"].upper(), "password": info["password"]})
    assert r.status_code == 200
    bad = client.post("/api/auth/login", json={"identifier": info["username"], "password": "wrong-pass-1"})
    assert bad.status_code == 401


def test_passwordless_login_code(client):
    info = register(new_client(), "Coder")
    assert client.post("/api/auth/login/code/start", json={"email": info["email"]}).status_code == 202
    r = client.post("/api/auth/login/code/verify", json={"email": info["email"], "code": last_code(info["email"])})
    assert r.status_code == 200 and client.get("/api/users/me").json()["id"] == info["id"]
    # Unknown emails get the same response but no email is sent
    before = len(OUTBOX)
    assert client.post("/api/auth/login/code/start", json={"email": "ghost@example.com"}).status_code == 202
    assert len(OUTBOX) == before


def test_password_reset_signs_out_other_sessions(client):
    c1 = new_client()
    info = register(c1, "Forgetful")
    assert client.post("/api/auth/password/forgot", json={"email": info["email"]}).status_code == 202
    r = client.post("/api/auth/password/reset", json={"email": info["email"], "code": last_code(info["email"]),
                                                      "new_password": "n3w-Passw0rd"})
    assert r.status_code == 200
    assert c1.get("/api/users/me").status_code == 401
    assert client.post("/api/auth/login", json={"identifier": info["username"], "password": "n3w-Passw0rd"}).status_code == 200


def test_google_sign_in_creates_and_links_accounts(client, monkeypatch):
    monkeypatch.setattr("app.api.auth.verify_id_token",
                        lambda cred: google.GoogleIdentity(sub="g-123", email="gina@example.com", name="Gina"))
    r = client.post("/api/auth/google", json={"credential": "x" * 50})
    assert r.status_code == 200
    me = r.json()
    assert me["email"] == "gina@example.com" and me["username"] == "gina" and not me["has_password"]
    # Second sign-in reuses the same account
    again = new_client().post("/api/auth/google", json={"credential": "x" * 50}).json()
    assert again["id"] == me["id"]
    # Password login is impossible until a password is set
    assert client.post("/api/auth/login", json={"identifier": "gina", "password": "anything-1"}).status_code == 401

    def bad(cred):
        raise google.GoogleAuthError("Google sign-in could not be verified")

    monkeypatch.setattr("app.api.auth.verify_id_token", bad)
    assert new_client().post("/api/auth/google", json={"credential": "y" * 50}).status_code == 401


def test_google_disabled_without_client_id(client):
    assert client.get("/api/auth/config").json()["google_client_id"] is None
    assert client.post("/api/auth/google", json={"credential": "z" * 50}).status_code == 401


def test_username_rules(client):
    info = register(new_client(), "Taken")
    assert client.get("/api/auth/username-available", params={"username": info["username"]}).json()["available"] is False
    assert client.get("/api/auth/username-available", params={"username": "Bad Name!"}).json()["available"] is False
    assert client.get("/api/auth/username-available", params={"username": "fresh.name_1"}).json()["available"] is True


def test_password_is_hashed(client, db):
    info = register(client, "Hash")
    user = db.scalar(select(User).where(User.email == info["email"]))
    assert user.password_hash != info["password"] and user.password_hash.startswith("$2")


def test_weak_password_rejected(client):
    email = "weak@example.com"
    client.post("/api/auth/signup/start", json={"email": email})
    token = client.post("/api/auth/signup/verify", json={"email": email, "code": last_code(email)}).json()["verification_token"]
    r = client.post("/api/auth/signup/complete", json={"verification_token": token, "username": "weakling",
                                                       "display_name": "W", "password": "12345678"})
    assert r.status_code == 422


def test_purpose_token_is_not_a_session(client):
    from app.core.config import get_settings
    from app.security.tokens import COOKIE_NAME, create_purpose_token

    c = new_client()
    c.cookies.set(COOKIE_NAME, create_purpose_token("1", "signup", get_settings()))
    assert c.get("/api/users/me").status_code == 401


def test_csrf_header_required_for_mutations():
    c = TestClient(app)  # no X-Requested-With header
    assert c.post("/api/auth/signup/start", json={"email": "x@example.com"}).status_code == 403


def test_logout_everywhere_invalidates_tokens(client):
    register(client, "Multi")
    other = new_client()
    other.cookies.update(client.cookies)
    assert other.get("/api/users/me").status_code == 200
    client.post("/api/auth/logout?everywhere=true")
    assert other.get("/api/users/me").status_code == 401


def test_profile_username_and_preferences_update(client):
    register(client, "Prefs")
    other = register(new_client(), "Other")
    r = client.patch("/api/users/me", json={"display_name": "New Name", "username": "New.Handle", "location_public": False})
    assert r.json()["display_name"] == "New Name" and r.json()["username"] == "new.handle"
    assert client.patch("/api/users/me", json={"username": other["username"]}).status_code == 409
    r = client.patch("/api/users/me/preferences", json={"favorite_genres": ["Thriller", "thriller", "Mystery"],
                                                        "preferred_length": "short"})
    assert r.json()["preferences"]["favorite_genres"] == ["Thriller", "Mystery"]


def test_delete_account(client, db, monkeypatch):
    info = register(client, "Leaver")
    assert client.request("DELETE", "/api/users/me", json={"password": "wrong-one-1"}).status_code == 400
    assert client.request("DELETE", "/api/users/me", json={"password": info["password"]}).status_code == 204
    assert db.scalar(select(User).where(User.email == info["email"])) is None
    # Google-only accounts confirm with their username instead of a password
    monkeypatch.setattr("app.api.auth.verify_id_token",
                        lambda cred: google.GoogleIdentity(sub="g-del", email="gdel@example.com", name="G Del"))
    g = new_client()
    me = g.post("/api/auth/google", json={"credential": "x" * 50}).json()
    assert g.request("DELETE", "/api/users/me", json={"confirm_username": "wrong"}).status_code == 400
    assert g.request("DELETE", "/api/users/me", json={"confirm_username": me["username"]}).status_code == 204


def test_rate_limit_on_login(client):
    from app.core.ratelimit import limiter

    limiter.enabled = True
    limiter.reset()
    codes = [client.post("/api/auth/login", json={"identifier": "nobody", "password": "x"}).status_code for _ in range(12)]
    assert 429 in codes


def test_api_docs_hidden_and_health(client):
    assert client.get("/api/docs").status_code == 404
    assert client.get("/api/openapi.json").status_code == 404
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["llm"] == "deterministic"


def test_tests_never_use_real_credentials():
    from app.core.config import get_settings

    s = get_settings()
    assert not s.smtp_configured and not s.groq_api_key and not s.google_client_id and not s.hf_token
