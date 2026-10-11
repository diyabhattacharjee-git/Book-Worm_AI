"""Test setup: an isolated temporary SQLite database, no network, no LLM, no eBay."""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="bookworm-tests-"))
os.environ.update({
    # Never read backend/.env: tests must not touch real SMTP, Google or LLM credentials.
    "BOOKWORM_ENV_FILE": "",
    "SMTP_HOST": "", "SMTP_FROM": "", "SMTP_USERNAME": "", "SMTP_PASSWORD": "",
    "GOOGLE_CLIENT_ID": "", "GOOGLE_BOOKS_API_KEY": "", "HF_MODEL": "",
    "APP_ENV": "test",
    # TEST_DATABASE_URL=postgresql://... runs the suite against Postgres (an empty, disposable database).
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{(_TMP / 'test.db').as_posix()}",
    "UPLOAD_DIR": str(_TMP / "uploads"),
    "APP_SECRET_KEY": "test-secret-key-that-is-long-enough-for-hs256-signing",
    "GROQ_API_KEY": "", "HF_TOKEN": "", "OLLAMA_BASE_URL": "", "OLLAMA_MODEL": "",
    "EBAY_CLIENT_ID": "", "EBAY_CLIENT_SECRET": "",
    "ENABLE_OPEN_LIBRARY": "false", "ENABLE_GOOGLE_BOOKS": "false",
    "LOG_LEVEL": "WARNING",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.models  # noqa: E402,F401
from app.core.ratelimit import limiter  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.seed import run_seed  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.mailer import OUTBOX  # noqa: E402
from tests.factories import seed_test_data  # noqa: E402

HEADERS = {"X-Requested-With": "XMLHttpRequest"}


@pytest.fixture(scope="session", autouse=True)
def database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        info = run_seed(db)
        seed_test_data(db)  # synthetic readers/listings exist only in the test database
    assert info["books_created"] > 50
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _no_rate_limits():
    limiter.enabled = False
    limiter.reset()
    yield
    limiter.enabled = True


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client() -> TestClient:
    c = TestClient(app)
    c.headers.update(HEADERS)
    return c


def last_code(email: str) -> str:
    import re

    for msg in reversed(OUTBOX):
        if msg["to"] == email:
            return re.search(r"\b(\d{6})\b", msg["text"]).group(1)
    raise AssertionError(f"no email sent to {email}")


def register(client: TestClient, name: str = "Reader") -> dict:
    """Full sign-up: email code -> verify -> choose username/password."""
    tag = uuid.uuid4().hex[:8]
    email = f"{name.lower().replace(' ', '')}-{tag}@example.com"
    username = f"{name.lower().replace(' ', '')}_{tag}"
    assert client.post("/api/auth/signup/start", json={"email": email}).status_code == 202
    r = client.post("/api/auth/signup/verify", json={"email": email, "code": last_code(email)})
    assert r.status_code == 200, r.text
    r = client.post("/api/auth/signup/complete", json={"verification_token": r.json()["verification_token"],
                                                       "username": username, "display_name": name,
                                                       "password": "s3cure-Passw0rd"})
    assert r.status_code == 201, r.text
    return {**r.json(), "password": "s3cure-Passw0rd"}


@pytest.fixture
def user_client() -> tuple[TestClient, dict]:
    c = TestClient(app)
    c.headers.update(HEADERS)
    return c, register(c, "Alice")


@pytest.fixture
def other_client() -> tuple[TestClient, dict]:
    c = TestClient(app)
    c.headers.update(HEADERS)
    return c, register(c, "Mallory")


@pytest.fixture
def admin_client(db) -> tuple[TestClient, dict]:
    from app.models.user import User

    c = TestClient(app)
    c.headers.update(HEADERS)
    info = register(c, "Admin")
    user = db.get(User, info["id"])
    user.role = "admin"
    db.commit()
    return c, info


def book_id_by_title(db, title: str) -> int:
    from sqlalchemy import select

    from app.models.book import Book

    return db.scalar(select(Book.id).where(Book.title == title))
