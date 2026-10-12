"""FastAPI application entry point.  Run:  uvicorn app.main:app --reload"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.agents import llm
from app.api import (
    admin,
    assistant,
    auth,
    books,
    intelligence,
    marketplace,
    reading,
    recommendations,
)
from app.core.config import get_secret_key, get_settings, integration_warnings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, log_event
from app.db.session import get_db
from app.marketplace.providers import providers_status
from app.models.media import StoredImage
from app.recommender.content import get_content_model
from app.security.middleware import CSRFHeaderMiddleware, SecurityHeadersMiddleware

logger = logging.getLogger("bookworm")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    get_secret_key(settings)  # fail fast in production without a real secret
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    for w in integration_warnings(settings):
        log_event(logger, "optional integration disabled", logging.WARNING, detail=w)
    log_event(logger, "startup", env=settings.app_env, database=settings.database_url.split(":", 1)[0])
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="BookWorm API",
        version="1.0.0",
        description="Book discovery, recommendations, reading tools and a second-hand marketplace with "
                    "multi-step price intelligence. All external integrations are optional.",
        lifespan=lifespan,
        # Developer-only; hidden unless ENABLE_API_DOCS=true.
        docs_url="/api/docs" if settings.enable_api_docs else None,
        redoc_url="/api/redoc" if settings.enable_api_docs else None,
        openapi_url="/api/openapi.json" if settings.enable_api_docs else None,
    )
    install_error_handlers(app)
    app.add_middleware(CSRFHeaderMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-Requested-With"],
    )
    for r in (auth.router, books.router, reading.router, recommendations.router, marketplace.router,
              intelligence.router, assistant.router, admin.router):
        app.include_router(r, prefix="/api")

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=str(upload_dir)), name="uploads")

    @app.get("/api/media/{subdir}/{name}", include_in_schema=False)
    def media(subdir: str, name: str, db: Session = Depends(get_db)):
        """Photos stored in the database (IMAGE_STORAGE=database). Keys are random, so URLs are unguessable."""
        img = db.scalar(select(StoredImage).where(StoredImage.key == f"{subdir}/{name}"))
        if img is None:
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        return Response(content=img.data, media_type=img.content_type)

    @app.get("/api/health", tags=["health"])
    def health(db: Session = Depends(get_db)):
        try:
            db.execute(text("SELECT 1"))
            db_ok = True
        except Exception:
            db_ok = False
        model = None
        try:
            model = get_content_model(db).backend
        except Exception:
            model = "unavailable"
        return {
            "status": "ok" if db_ok else "degraded",
            "database": "ok" if db_ok else "unreachable",
            "environment": settings.app_env,
            "content_model": model,
            "llm": llm.status()["mode"],
            "marketplace_providers": {p["key"]: p["available"] for p in providers_status(db)},
            "warnings": integration_warnings(settings),
        }

    # Registered last so the catch-all never shadows API routes.
    dist = Path(settings.frontend_dist) if settings.frontend_dist else None
    if dist and (dist / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=str(dist / "assets")), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            # Serve real files from dist (favicon etc.), otherwise the SPA shell.
            if path.startswith("api/"):
                return JSONResponse(status_code=404, content={"detail": "Not found"})
            target = (dist / path).resolve()
            if path and dist.resolve() in target.parents and target.is_file():
                return FileResponse(target)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
