"""Persistence ports. Implementations live in infrastructure."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from etl_pipeline.domain.models import Invoice, InvoiceSummary, Rejection, UpsertStats


class InvoiceRepository(Protocol):
    def upsert_many(self, invoices: Sequence[Invoice], *, load_id: str) -> UpsertStats: ...

    def get(self, source_system: str, external_id: str) -> Invoice | None: ...

    def list_summaries(
        self, *, source_system: str | None, limit: int
    ) -> list[InvoiceSummary]: ...


class RejectionRepository(Protocol):
    def add_many(self, load_id: str, rejections: Sequence[Rejection]) -> None: ...
