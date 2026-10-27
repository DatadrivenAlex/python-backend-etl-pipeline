"""Idempotent load: transform, upsert by natural key, remember the HTTP body."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence

from etl_pipeline.application.errors import DuplicateIdempotencyKey, IdempotencyConflict
from etl_pipeline.application.ports import Clock, IdFactory, MetricsPort, UnitOfWork
from etl_pipeline.application.receipts import (
    MAX_EMBEDDED_REJECTIONS,
    LoadReceipt,
    LoadResult,
    StoredLoad,
)
from etl_pipeline.application.transform import InvoiceTransformer
from etl_pipeline.domain.errors import DomainError
from etl_pipeline.domain.models import Invoice, InvoiceSummary, RawOrder, Rejection
from etl_pipeline.logging import log_event

logger = logging.getLogger(__name__)


class LoadService:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        transformer: InvoiceTransformer,
        metrics: MetricsPort,
        ids: IdFactory,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._transformer = transformer
        self._metrics = metrics
        self._ids = ids
        self._clock = clock

    def execute(
        self,
        orders: Sequence[RawOrder],
        *,
        idempotency_key: str,
        request_hash: str,
        extra_rejections: Sequence[Rejection] = (),
    ) -> LoadResult:
        started = time.perf_counter()
        try:
            return self._execute_once(
                orders,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                extra_rejections=extra_rejections,
                started=started,
            )
        except DuplicateIdempotencyKey:
            return self._resolve_race(idempotency_key, request_hash)

    def get_invoice(self, source_system: str, external_id: str) -> Invoice | None:
        with self._uow_factory() as uow:
            return uow.invoices.get(source_system, external_id)

    def list_invoices(self, *, source_system: str | None, limit: int) -> list[InvoiceSummary]:
        with self._uow_factory() as uow:
            return uow.invoices.list_summaries(source_system=source_system, limit=limit)

    def get_load(self, load_id: str) -> LoadReceipt | None:
        with self._uow_factory() as uow:
            stored = uow.idempotency.get_by_load_id(load_id)
        if stored is None:
            return None
        return stored.receipt

    def _execute_once(
        self,
        orders: Sequence[RawOrder],
        *,
        idempotency_key: str,
        request_hash: str,
        extra_rejections: Sequence[Rejection],
        started: float,
    ) -> LoadResult:
        with self._uow_factory() as uow:
            existing = uow.idempotency.get(idempotency_key)
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise IdempotencyConflict(idempotency_key)
                self._metrics.inc("etl_load_requests_total", result="replay")
                return LoadResult(
                    receipt=existing.receipt,
                    replayed=True,
                    http_status=existing.http_status,
                )

            load_id = self._ids.new()
            invoices, rejections = self._transform(orders, extra_rejections)
            stats = uow.invoices.upsert_many(invoices, load_id=load_id)
            uow.rejections.add_many(load_id, rejections)
            duration_ms = int((time.perf_counter() - started) * 1000)
            receipt = LoadReceipt(
                load_id=load_id,
                idempotency_key=idempotency_key,
                accepted=len(invoices),
                rejected=len(rejections),
                inserted=stats.inserted,
                updated=stats.updated,
                unchanged=stats.unchanged,
                duration_ms=duration_ms,
                rejections=tuple(rejections[:MAX_EMBEDDED_REJECTIONS]),
            )
            stored = StoredLoad(
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                http_status=201,
                receipt=receipt,
                created_at=self._clock.now(),
            )
            uow.idempotency.put(stored)
            uow.commit()

        self._record_created(receipt, started)
        log_event(
            logger,
            "load completed",
            load_id=receipt.load_id,
            accepted=receipt.accepted,
            rejected=receipt.rejected,
            inserted=receipt.inserted,
            updated=receipt.updated,
            unchanged=receipt.unchanged,
        )
        return LoadResult(receipt=receipt, replayed=False, http_status=201)

    def _resolve_race(self, idempotency_key: str, request_hash: str) -> LoadResult:
        with self._uow_factory() as uow:
            existing = uow.idempotency.get(idempotency_key)
        if existing is None:
            raise RuntimeError(f"idempotency key {idempotency_key!r} vanished after a conflict")
        if existing.request_hash != request_hash:
            raise IdempotencyConflict(idempotency_key)
        self._metrics.inc("etl_load_requests_total", result="replay")
        return LoadResult(
            receipt=existing.receipt,
            replayed=True,
            http_status=existing.http_status,
        )

    def _transform(
        self,
        orders: Sequence[RawOrder],
        extra_rejections: Sequence[Rejection],
    ) -> tuple[list[Invoice], list[Rejection]]:
        seen: set[tuple[str, str]] = set()
        invoices: list[Invoice] = []
        rejections = list(extra_rejections)
        for order in orders:
            if order.natural_key in seen:
                rejections.append(
                    Rejection(
                        source_system=order.source_system,
                        external_id=order.external_id,
                        code="DUPLICATE_IN_BATCH",
                        message="external_id repeated in this load; the first copy was kept",
                    )
                )
                continue
            seen.add(order.natural_key)
            try:
                invoices.append(self._transformer.transform(order))
            except DomainError as exc:
                rejections.append(
                    Rejection(
                        source_system=order.source_system.strip().lower(),
                        external_id=order.external_id.strip(),
                        code=exc.code,
                        message=exc.message,
                    )
                )
        return invoices, rejections

    def _record_created(self, receipt: LoadReceipt, started: float) -> None:
        self._metrics.inc("etl_load_requests_total", result="created")
        self._metrics.inc("etl_invoices_total", value=receipt.accepted, outcome="accepted")
        self._metrics.inc("etl_invoices_total", value=receipt.rejected, outcome="rejected")
        self._metrics.inc("etl_persisted_invoices_total", value=receipt.inserted, result="inserted")
        self._metrics.inc("etl_persisted_invoices_total", value=receipt.updated, result="updated")
        self._metrics.inc(
            "etl_persisted_invoices_total", value=receipt.unchanged, result="unchanged"
        )
        for rejection in receipt.rejections:
            self._metrics.inc("etl_rejections_total", code=rejection.code)
        self._metrics.observe(
            "etl_load_duration_seconds",
            time.perf_counter() - started,
            result="created",
        )
