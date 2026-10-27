"""ASGI application factory. `asgi.py` is what uvicorn imports."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from sqlalchemy import Engine

from etl_pipeline import __version__
from etl_pipeline.api.routes import register_exception_handlers, router
from etl_pipeline.composition import build_runtime
from etl_pipeline.config import Settings

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or Settings()
    runtime = build_runtime(settings, engine=engine)
    app = FastAPI(
        title="Invoice ETL Pipeline",
        version=__version__,
        summary="Idempotent commercial-invoice loads with Decimal VAT.",
        description=(
            "Submit orders with an Idempotency-Key. Replays of the same body return the "
            "original result. A different body for the same key is a conflict. "
            "Money amounts in JSON are decimal strings."
        ),
    )
    app.state.runtime = runtime
    register_exception_handlers(app)
    app.include_router(router)
    _install_http_metrics(app)
    return app


def _install_http_metrics(app: FastAPI) -> None:
    @app.middleware("http")
    async def _observe(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            _record(request, started, "500")
            logger.exception("request failed", extra={"event_fields": {"request_id": request_id}})
            raise
        status = str(response.status_code)
        _record(request, started, status)
        response.headers["X-Request-ID"] = request_id
        return response

    def _record(request: Request, started: float, status: str) -> None:
        route = request.scope.get("route")
        path = getattr(route, "path", None)
        template = path if isinstance(path, str) else "unmatched"
        metrics = request.app.state.runtime.metrics
        metrics.inc(
            "etl_http_requests_total",
            method=request.method,
            path=template,
            status=status,
        )
        metrics.observe(
            "etl_http_request_duration_seconds",
            time.perf_counter() - started,
            method=request.method,
            path=template,
        )
