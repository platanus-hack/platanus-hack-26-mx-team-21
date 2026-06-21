"""FastAPI application factory. Wires request-id middleware, CORS, the one error envelope,
and explicit router registration. There is no dynamic plugin loader — the public surface is
the list of include_router calls below, which keeps it reviewable."""
from __future__ import annotations
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from citycrawl_api import __version__
from citycrawl_api.config import get_settings
from citycrawl_api.errors import ApiError
from citycrawl_api.logging import configure_logging, get_logger, log_event, set_request_id
from citycrawl_api.routers import datasets, health, llm, observations, planning, video

logger = get_logger()


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    # Fail fast on unsafe CORS/storage config before serving any traffic.
    settings.validate_startup()
    app = FastAPI(title="citycrawl-api", version=__version__)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        # Narrowed from "*": allow_credentials=True must not be paired with a wildcard.
        allow_headers=settings.cors_allow_headers,
        expose_headers=["X-Request-ID", "X-Planning-Engine"],
    )

    @app.middleware("http")
    async def body_size_limit(request: Request, call_next):
        """Reject oversized requests up front via Content-Length so a huge upload can't
        OOM the worker before the route reads it. Content-Length can be absent or spoofed,
        so the upload route also guards the actual byte count after reading."""
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                declared = int(cl)
            except ValueError:
                declared = None
            if declared is not None and declared > settings.max_upload_bytes:
                from citycrawl_api.logging import get_request_id

                rid = get_request_id()
                err = ApiError(
                    413, "payload_too_large",
                    "Request body exceeds the maximum allowed size",
                    {"maxBytes": settings.max_upload_bytes},
                )
                return JSONResponse(
                    status_code=413, content=err.envelope(rid), headers={"X-Request-ID": rid}
                )
        return await call_next(request)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("X-Request-ID")
        request_id = incoming if incoming else uuid.uuid4().hex
        set_request_id(request_id)
        start = time.monotonic()
        try:
            response = await call_next(request)
        except ApiError:
            raise
        except Exception:
            elapsed = round((time.monotonic() - start) * 1000, 1)
            log_event(
                logger,
                "request_failed",
                route=request.url.path,
                method=request.method,
                status=500,
                elapsedMs=elapsed,
            )
            raise
        elapsed = round((time.monotonic() - start) * 1000, 1)
        response.headers["X-Request-ID"] = request_id
        log_event(
            logger,
            "request",
            route=request.url.path,
            method=request.method,
            status=response.status_code,
            elapsedMs=elapsed,
        )
        return response

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError):
        from citycrawl_api.logging import get_request_id

        rid = get_request_id()
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.envelope(rid),
            headers={"X-Request-ID": rid},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        from citycrawl_api.logging import get_request_id

        from fastapi.encoders import jsonable_encoder

        rid = get_request_id()
        details = {"errors": jsonable_encoder(exc.errors())}
        err = ApiError(422, "invalid_request", "Request validation failed", details)
        return JSONResponse(status_code=422, content=err.envelope(rid), headers={"X-Request-ID": rid})

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception):
        from citycrawl_api.logging import get_request_id

        rid = get_request_id()
        logger.exception("unhandled_error")
        err = ApiError(500, "internal_error", "Internal server error")
        return JSONResponse(status_code=500, content=err.envelope(rid), headers={"X-Request-ID": rid})

    # Explicit router registration — the reviewable public surface.
    app.include_router(health.router)
    app.include_router(planning.router)
    app.include_router(llm.router)
    app.include_router(datasets.router)
    app.include_router(video.router)
    app.include_router(observations.router)
    return app


app = create_app()
