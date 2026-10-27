"""Application ports implemented by infrastructure."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from etl_pipeline.application.receipts import StoredLoad
from etl_pipeline.domain.ports import InvoiceRepository, RejectionRepository


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdFactory(Protocol):
    def new(self) -> str: ...


class MetricsPort(Protocol):
    def inc(self, name: str, value: float = 1, **labels: str) -> None: ...

    def observe(self, name: str, value: float, **labels: str) -> None: ...


class IdempotencyStore(Protocol):
    def get(self, key: str) -> StoredLoad | None: ...

    def get_by_load_id(self, load_id: str) -> StoredLoad | None: ...

    def put(self, stored: StoredLoad) -> None: ...


class UnitOfWork(Protocol):
    invoices: InvoiceRepository
    rejections: RejectionRepository
    idempotency: IdempotencyStore

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
