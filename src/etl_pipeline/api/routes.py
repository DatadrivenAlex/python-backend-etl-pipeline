"""HTTP routes. Business decisions stay in the load service."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text

from etl_pipeline.api.mapping import (
    invoice_response,
    load_response,
    orders_from_request,
    request_hash,
    summary_response,
)
from etl_pipeline.api.schemas import InvoiceOut, InvoiceSummaryOut, LoadRequest, LoadResponse
from etl_pipeline.application.errors import IdempotencyConflict

logger = logging.getLogger(__name__)

router = APIRouter()

_IDEMPOTENCY = r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,199}$"


@router.get("/")
def root() -> dict[str, str]:
    return {
        "service": "python-backend-etl-pipeline",
        "health": "/health",
        "ready": "/ready",
        "metrics": "/metrics",
        "docs": "/docs",
    }


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", response_model=None)
def ready(request: Request) -> JSONResponse | dict[str, str]:
    try:
        with request.app.state.runtime.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        logger.warning("readiness check failed", exc_info=True)
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    return {"status": "ready"}


@router.get("/metrics", response_model=None)
def metrics(request: Request) -> Response:
    body = request.app.state.runtime.metrics.render()
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")


@router.post("/v1/loads", response_model=LoadResponse, status_code=201)
def create_load(
    payload: LoadRequest,
    request: Request,
    response: Response,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=200, pattern=_IDEMPOTENCY),
    ],
) -> LoadResponse:
    limit = request.app.state.runtime.settings.max_orders_per_request
    if len(payload.orders) > limit:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "TOO_MANY_ORDERS",
                "message": f"a request accepts at most {limit} orders",
            },
        )
    orders = orders_from_request(payload)
    result = request.app.state.runtime.load_service().execute(
        orders,
        idempotency_key=idempotency_key,
        request_hash=request_hash(payload, orders),
    )
    response.status_code = result.http_status
    if result.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return load_response(result.receipt)


@router.get("/v1/loads/{load_id}", response_model=LoadResponse)
def get_load(load_id: str, request: Request) -> LoadResponse:
    _validate_uuid(load_id)
    receipt = request.app.state.runtime.load_service().get_load(load_id)
    if receipt is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "load not found"},
        )
    return load_response(receipt)


@router.get("/v1/invoices/{source_system}/{external_id}", response_model=InvoiceOut)
def get_invoice(source_system: str, external_id: str, request: Request) -> InvoiceOut:
    invoice = request.app.state.runtime.load_service().get_invoice(source_system, external_id)
    if invoice is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "invoice not found"},
        )
    return invoice_response(invoice)


@router.get("/v1/invoices", response_model=list[InvoiceSummaryOut])
def list_invoices(
    request: Request,
    source_system: Annotated[
        str | None,
        Query(pattern=r"^[a-z0-9][a-z0-9._-]{0,62}$"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[InvoiceSummaryOut]:
    summaries = request.app.state.runtime.load_service().list_invoices(
        source_system=source_system,
        limit=limit,
    )
    return [summary_response(item) for item in summaries]


def _validate_uuid(value: str) -> None:
    try:
        uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "load not found"},
        ) from exc


def register_exception_handlers(app) -> None:
    @app.exception_handler(IdempotencyConflict)
    async def _conflict(_request: Request, exc: IdempotencyConflict) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": {"code": exc.code, "message": str(exc)}},
        )
