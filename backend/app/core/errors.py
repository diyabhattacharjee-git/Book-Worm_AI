from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("bookworm.errors")


def not_found(what: str = "Resource") -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} not found")


def forbidden(detail: str = "You do not have permission to do this") -> HTTPException:
    return HTTPException(status_code=403, detail=detail)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        errors = []
        for e in exc.errors():
            loc = ".".join(str(p) for p in e.get("loc", []) if p not in ("body", "query", "path"))
            msg = str(e.get("msg", "Invalid value")).removeprefix("Value error, ")
            errors.append({"field": loc, "message": msg})
        return JSONResponse(status_code=422, content={"detail": "Validation failed", "errors": errors})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # The full trace goes to the logs only; clients never see internals.
        logger.exception("unhandled error", extra={"data": {"path": request.url.path}})
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
