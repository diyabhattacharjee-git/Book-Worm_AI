"""Application configuration loaded from environment variables / .env.

Every external integration is optional. Missing keys disable that integration
and are reported through /api/health and /api/marketplace/providers/status.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]

logger = logging.getLogger("bookworm.config")

_INSECURE_SECRETS = {"", "change-me", "replace_with_a_secure_random_value"}

# BOOKWORM_ENV_FILE="" disables reading backend/.env (the test suite does this so it can never
# use real credentials such as SMTP or API keys).
_ENV_FILE = os.environ.get("BOOKWORM_ENV_FILE", str(BACKEND_DIR / ".env")) or None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_secret_key: str = ""
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'book_platform.db').as_posix()}"
    frontend_origin: str = "http://localhost:5173"
    session_ttl_hours: int = 24 * 7
    log_level: str = "INFO"
    # Optional: path to the built frontend (frontend/dist) to serve it from this
    # same process (single-service deployment). Empty = API only.
    frontend_dist: str = ""

    # Interactive API docs (/api/docs). Off by default so end users never see them.
    enable_api_docs: bool = False

    # Email delivery for one-time codes (any SMTP server, e.g. Gmail with an app password).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True  # STARTTLS on 587; set SMTP_PORT=465 for implicit TLS
    otp_ttl_minutes: int = 10
    otp_max_attempts: int = 5
    otp_resend_seconds: int = 60

    # Google sign-in (OAuth client ID from Google Cloud console; free)
    google_client_id: str = ""

    # Image storage: "cloudinary://<api_key>:<api_secret>@<cloud_name>" stores uploads in Cloudinary
    # (free plan, needed on hosts without a persistent disk such as Vercel). Empty = local UPLOAD_DIR.
    cloudinary_url: str = ""
    # Where photos go without Cloudinary: "local" (UPLOAD_DIR), "database" (the app database; fine for a
    # small site) or "auto" (database on Vercel, whose disk is temporary; local everywhere else).
    image_storage: str = "auto"

    # Uploads
    upload_dir: str = str(BACKEND_DIR / "uploads")
    max_upload_mb: float = 5.0
    max_images_per_listing: int = 6

    # Optional LLM providers (tried in this order: groq -> huggingface -> ollama)
    llm_provider_order: str = "groq,huggingface,ollama"
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    hf_token: str = ""
    hf_model: str = ""
    hf_provider: str = "auto"  # HF Inference Providers routing; free accounts are limited to free credits
    ollama_base_url: str = ""
    ollama_model: str = ""
    llm_timeout_seconds: float = 20.0

    # Optional embeddings (requires `pip install -r requirements-ml.txt`)
    embeddings_backend: str = "tfidf"  # tfidf | sentence-transformers
    embeddings_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # Book metadata providers
    google_books_api_key: str = ""
    enable_open_library: bool = True
    enable_google_books: bool = True
    google_books_country: str = "IN"
    external_http_timeout_seconds: float = 8.0
    metadata_cache_ttl_hours: int = 24 * 7

    # eBay Browse API (optional)
    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    ebay_environment: str = "sandbox"  # sandbox | production
    ebay_marketplace_id: str = "EBAY_US"
    ebay_cache_ttl_minutes: int = 60

    # Price intelligence
    default_currency: str = "INR"
    # Explicit, user-configured conversion rates, e.g. {"USD_INR": 83.0}.
    # Empty means currencies are never mixed.
    fx_rates_json: str = ""
    include_sample_listings_in_estimates: bool = True

    # Recommendation weights (see docs/RECOMMENDER.md)
    rec_weight_content: float = 0.40
    rec_weight_collaborative: float = 0.25
    rec_weight_popularity: float = 0.15
    rec_weight_preference: float = 0.20
    rec_diversity_lambda: float = 0.80
    rec_recency_half_life_days: float = 60.0
    rec_bayes_prior_count: int = 5
    rec_cf_min_users: int = 5
    rec_cf_min_user_interactions: int = 3

    @field_validator("database_url")
    @classmethod
    def _resolve_sqlite_path(cls, v: str) -> str:
        v = v.strip()
        # Neon/Heroku-style URLs -> SQLAlchemy's psycopg 3 driver.
        for scheme in ("postgres://", "postgresql://"):
            if v.startswith(scheme):
                return "postgresql+psycopg://" + v[len(scheme):]
        # "sqlite:///./x.db" is resolved against backend/ so the working directory doesn't matter.
        prefix = "sqlite:///"
        if v.startswith(prefix) and not v.startswith(prefix + "/"):
            rel = v[len(prefix):]
            if rel and rel != ":memory:" and not Path(rel).is_absolute():
                return prefix + (BACKEND_DIR / rel).resolve().as_posix()
        return v

    @field_validator("upload_dir", "frontend_dist")
    @classmethod
    def _resolve_dir(cls, v: str) -> str:
        if not v:
            return v
        if os.environ.get("VERCEL") and v == str(BACKEND_DIR / "uploads"):
            return "/tmp/bookworm-uploads"  # Vercel's filesystem is read-only except /tmp
        p = Path(v)
        return str(p if p.is_absolute() else (BACKEND_DIR / p).resolve())

    @field_validator("ebay_environment")
    @classmethod
    def _check_ebay_env(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in {"sandbox", "production"}:
            raise ValueError("EBAY_ENVIRONMENT must be 'sandbox' or 'production'")
        return v

    @field_validator("image_storage")
    @classmethod
    def _check_image_storage(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in {"auto", "local", "database"}:
            raise ValueError("IMAGE_STORAGE must be 'auto', 'local' or 'database'")
        return v

    @property
    def image_backend(self) -> str:
        """cloudinary | database | local"""
        if self.cloudinary:
            return "cloudinary"
        if self.image_storage == "database" or (self.image_storage == "auto" and os.environ.get("VERCEL")):
            return "database"
        return "local"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def fx_rates(self) -> dict[str, float]:
        if not self.fx_rates_json.strip():
            return {}
        try:
            data = json.loads(self.fx_rates_json)
            return {str(k).upper(): float(v) for k, v in data.items() if float(v) > 0}
        except (ValueError, TypeError, AttributeError):
            logger.warning("FX_RATES_JSON is not valid JSON; currency conversion disabled")
            return {}

    @property
    def cloudinary(self) -> dict | None:
        m = re.fullmatch(r"cloudinary://([^:]+):([^@]+)@(.+)", self.cloudinary_url.strip())
        return {"api_key": m.group(1), "api_secret": m.group(2), "cloud_name": m.group(3)} if m else None

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def ebay_configured(self) -> bool:
        return bool(self.ebay_client_id and self.ebay_client_secret)

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_origin.split(",") if o.strip()]

_runtime_secret: str | None = None

def get_secret_key(settings: "Settings") -> str:
    """Return the signing secret. In development a random per-process secret is
    generated when none is configured (sessions reset on restart). Production
    refuses to start without a real secret."""
    global _runtime_secret
    if settings.app_secret_key not in _INSECURE_SECRETS and len(settings.app_secret_key) >= 32:
        return settings.app_secret_key
    if settings.is_production:
        raise RuntimeError("APP_SECRET_KEY must be set to a random value of at least 32 characters in production")
    if _runtime_secret is None:
        _runtime_secret = secrets.token_urlsafe(48)
        logger.warning("APP_SECRET_KEY not set: using a temporary random secret (sessions reset on restart)")
    return _runtime_secret

@lru_cache
def get_settings() -> Settings:
    return Settings()

def integration_warnings(settings: Settings) -> list[str]:
    warnings: list[str] = []
    if not settings.groq_api_key and not settings.hf_token and not (settings.ollama_base_url and settings.ollama_model):
        warnings.append("No LLM provider configured: assistant and agents run in deterministic mode.")
    if not settings.ebay_configured:
        warnings.append("eBay credentials not configured: used-book search uses community listings only.")
    if not settings.smtp_configured:
        warnings.append("SMTP not configured: one-time codes are printed to the server log (development only).")
    if settings.hf_token and not settings.hf_model:
        warnings.append("HF_TOKEN set without HF_MODEL: Hugging Face provider disabled.")
    return warnings
