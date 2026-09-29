"""Formly API -- text prompt in, validated GLB out."""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.logging_config import configure_logging
from app.routes import generation, health
from app.services.generation.registry import build_provider
from app.services.rate_limit import RateLimiter
from app.services.store import AssetStore

logger = logging.getLogger("formly")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging()

    app.state.settings = settings
    app.state.provider = build_provider(settings)
    app.state.store = AssetStore(
        ttl_seconds=settings.asset_ttl_seconds,
        max_items=settings.max_stored_assets,
    )
    app.state.limiter = RateLimiter(
        max_requests=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )

    logger.info(
        "startup provider=%s space=%s token=%s cors=%s",
        app.state.provider.name,
        settings.hf_space,
        "set" if settings.hf_token else "anonymous",
        settings.cors_origin_list,
    )
    try:
        yield
    finally:
        await app.state.provider.aclose()
        app.state.store.clear()
        logger.info("shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Formly API",
        description="Turns a natural-language prompt into a validated GLB 3D model.",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Exact origins only -- no wildcard, since the frontend URL is known.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
        expose_headers=["Content-Disposition", "X-Request-ID"],
        max_age=600,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        started = time.perf_counter()

        response = await call_next(request)

        duration_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    # --- Uniform error envelope ---------------------------------------------
    # The frontend should only ever have to read {success, error}.

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError):
        message = "Invalid request"
        for error in exc.errors():
            raw = error.get("msg", "")
            # Pydantic prefixes ValueError messages with "Value error, ".
            message = raw.removeprefix("Value error, ") or message
            break
        return JSONResponse(status_code=422, content={"success": False, "error": message})

    @app.exception_handler(StarletteHTTPException)
    async def on_http_error(request: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(
            status_code=exc.status_code,
            content={"success": False, "error": detail},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def on_unhandled_error(request: Request, exc: Exception):
        # Log the detail, return a generic message -- never leak internals.
        logger.exception(
            "unhandled_error request_id=%s path=%s",
            getattr(request.state, "request_id", "-"),
            request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "Something went wrong"},
        )

    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(generation.router, prefix="/api", tags=["generation"])

    return app


app = create_app()
