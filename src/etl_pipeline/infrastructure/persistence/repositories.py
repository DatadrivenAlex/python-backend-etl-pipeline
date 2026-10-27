"""SQLAlchemy adapters for the invoice, rejection, and idempotency ports."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from etl_pipeline.application.errors import DuplicateIdempotencyKey
from etl_pipeline.application.receipts import StoredLoad, receipt_from_json, receipt_to_json
from etl_pipeline.domain.models import (
    Invoice,
    InvoiceLine,
    InvoiceSummary,
    Party,
    Rejection,
    UpsertStats,
)
from etl_pipeline.domain.money import Money
from etl_pipeline.infrastructure.clock import SystemClock
from etl_pipeline.infrastructure.persistence.mapping import as_datetime, as_decimal
from etl_pipeline.infrastructure.persistence.orm import (
    IdempotencyRow,
    InvoiceLineRow,
    InvoiceRow,
    RejectionRow,
)


class SqlInvoiceRepository:
    def __init__(self, session: Session, clock: SystemClock | None = None) -> None:
        self._session = session
        self._clock = clock or SystemClock()

    def upsert_many(self, invoices: list[Invoice] | tuple[Invoice, ...], *, load_id: str) -> UpsertStats:
        if not invoices:
            return UpsertStats(inserted=0, updated=0, unchanged=0)
        keys = [(invoice.source_system, invoice.external_id) for invoice in invoices]
        existing = self._session.scalars(
            select(InvoiceRow).where(
                tuple_(InvoiceRow.source_system, InvoiceRow.external_id).in_(keys)
            )
        ).all()
        by_key = {(row.source_system, row.external_id): row for row in existing}
        inserted = updated = unchanged = 0
        now = self._clock.now()
        for invoice in invoices:
            current = by_key.get(invoice.natural_key)
            if current is None:
                self._session.add(_new_invoice_row(invoice, load_id=load_id, now=now))
                inserted += 1
                continue
            if current.content_hash == invoice.content_hash:
                unchanged += 1
                continue
            _apply_header(current, invoice, load_id=load_id, now=now)
            current.lines.clear()
            # Delete old lines before inserting the same line numbers.
            self._session.flush()
            current.lines.extend(_line_row(line) for line in invoice.lines)
            updated += 1
        return UpsertStats(inserted=inserted, updated=updated, unchanged=unchanged)

    def get(self, source_system: str, external_id: str) -> Invoice | None:
        row = self._session.scalar(
            select(InvoiceRow)
            .where(
                InvoiceRow.source_system == source_system,
                InvoiceRow.external_id == external_id,
            )
            .options(selectinload(InvoiceRow.lines))
        )
        if row is None:
            return None
        return _invoice_from_row(row)

    def list_summaries(self, *, source_system: str | None, limit: int) -> list[InvoiceSummary]:
        counts = (
            select(
                InvoiceLineRow.invoice_id,
                func.count(InvoiceLineRow.id).label("line_count"),
            )
            .group_by(InvoiceLineRow.invoice_id)
            .subquery()
        )
        statement = (
            select(InvoiceRow, func.coalesce(counts.c.line_count, 0))
            .outerjoin(counts, counts.c.invoice_id == InvoiceRow.id)
            .order_by(InvoiceRow.ordered_at.desc(), InvoiceRow.external_id.asc())
            .limit(limit)
        )
        if source_system is not None:
            statement = statement.where(InvoiceRow.source_system == source_system)
        rows = self._session.execute(statement).all()
        summaries: list[InvoiceSummary] = []
        for row, line_count in rows:
            summaries.append(
                InvoiceSummary(
                    source_system=row.source_system,
                    external_id=row.external_id,
                    ordered_at=as_datetime(row.ordered_at),
                    currency=row.currency,
                    net_total=Money(as_decimal(row.net_amount), row.currency),
                    vat_total=Money(as_decimal(row.vat_amount), row.currency),
                    gross_total=Money(as_decimal(row.gross_amount), row.currency),
                    version=row.version,
                    line_count=int(line_count),
                )
            )
        return summaries


class SqlRejectionRepository:
    def __init__(self, session: Session, clock: SystemClock | None = None) -> None:
        self._session = session
        self._clock = clock or SystemClock()

    def add_many(self, load_id: str, rejections: list[Rejection] | tuple[Rejection, ...]) -> None:
        now = self._clock.now()
        for item in rejections:
            self._session.add(
                RejectionRow(
                    id=str(uuid.uuid4()),
                    load_id=load_id,
                    source_system=item.source_system[:64],
                    external_id=item.external_id[:128],
                    code=item.code[:64],
                    message=item.message[:2000],
                    created_at=now,
                )
            )


class SqlIdempotencyStore:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, key: str) -> StoredLoad | None:
        row = self._session.get(IdempotencyRow, key)
        if row is None:
            return None
        return _stored_from_row(row)

    def get_by_load_id(self, load_id: str) -> StoredLoad | None:
        row = self._session.scalar(
            select(IdempotencyRow).where(IdempotencyRow.load_id == load_id)
        )
        if row is None:
            return None
        return _stored_from_row(row)

    def put(self, stored: StoredLoad) -> None:
        self._session.add(
            IdempotencyRow(
                idempotency_key=stored.idempotency_key,
                request_hash=stored.request_hash,
                load_id=stored.receipt.load_id,
                http_status=stored.http_status,
                response_json=receipt_to_json(stored.receipt),
                created_at=stored.created_at,
            )
        )
        try:
            self._session.flush()
        except IntegrityError as exc:
            raise DuplicateIdempotencyKey(stored.idempotency_key) from exc


class SqlUnitOfWork:
    def __init__(self, session_factory, clock: SystemClock | None = None) -> None:
        self._session_factory = session_factory
        self._clock = clock or SystemClock()
        self._session: Session | None = None
        self.invoices: SqlInvoiceRepository
        self.rejections: SqlRejectionRepository
        self.idempotency: SqlIdempotencyStore

    def __enter__(self) -> SqlUnitOfWork:
        self._session = self._session_factory()
        self.invoices = SqlInvoiceRepository(self._session, self._clock)
        self.rejections = SqlRejectionRepository(self._session, self._clock)
        self.idempotency = SqlIdempotencyStore(self._session)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._session is None:
            return
        try:
            if exc_type is not None:
                self._session.rollback()
        finally:
            self._session.close()
            self._session = None

    def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("unit of work is closed")
        self._session.commit()

    def rollback(self) -> None:
        if self._session is None:
            raise RuntimeError("unit of work is closed")
        self._session.rollback()


def _new_invoice_row(invoice: Invoice, *, load_id: str, now: datetime) -> InvoiceRow:
    row = InvoiceRow(
        id=str(uuid.uuid4()),
        source_system=invoice.source_system,
        external_id=invoice.external_id,
        ordered_at=invoice.ordered_at,
        currency=invoice.currency,
        seller_id=invoice.seller.party_id,
        seller_name=invoice.seller.name,
        seller_country=invoice.seller.country,
        seller_vat_id=invoice.seller.vat_id or "",
        buyer_id=invoice.buyer.party_id,
        buyer_name=invoice.buyer.name,
        buyer_country=invoice.buyer.country,
        buyer_vat_id=invoice.buyer.vat_id,
        net_amount=invoice.net_total.amount,
        vat_amount=invoice.vat_total.amount,
        gross_amount=invoice.gross_total.amount,
        content_hash=invoice.content_hash,
        version=1,
        last_load_id=load_id,
        created_at=now,
        updated_at=now,
    )
    row.lines = [_line_row(line) for line in invoice.lines]
    return row


def _apply_header(row: InvoiceRow, invoice: Invoice, *, load_id: str, now: datetime) -> None:
    row.ordered_at = invoice.ordered_at
    row.currency = invoice.currency
    row.seller_id = invoice.seller.party_id
    row.seller_name = invoice.seller.name
    row.seller_country = invoice.seller.country
    row.seller_vat_id = invoice.seller.vat_id or ""
    row.buyer_id = invoice.buyer.party_id
    row.buyer_name = invoice.buyer.name
    row.buyer_country = invoice.buyer.country
    row.buyer_vat_id = invoice.buyer.vat_id
    row.net_amount = invoice.net_total.amount
    row.vat_amount = invoice.vat_total.amount
    row.gross_amount = invoice.gross_total.amount
    row.content_hash = invoice.content_hash
    row.version = row.version + 1
    row.last_load_id = load_id
    row.updated_at = now


def _line_row(line: InvoiceLine) -> InvoiceLineRow:
    return InvoiceLineRow(
        id=str(uuid.uuid4()),
        line_no=line.line_no,
        sku=line.sku,
        description=line.description,
        quantity=line.quantity,
        unit_net=line.unit_net.amount,
        line_net=line.line_net.amount,
        vat_code=line.vat_code,
        vat_rate=line.vat_rate,
        vat_treatment=line.vat_treatment,
        vat_amount=line.vat_amount.amount,
        line_gross=line.line_gross.amount,
    )


def _invoice_from_row(row: InvoiceRow) -> Invoice:
    currency = row.currency
    lines = tuple(_line_from_row(line, currency) for line in sorted(row.lines, key=lambda item: item.line_no))
    return Invoice(
        source_system=row.source_system,
        external_id=row.external_id,
        ordered_at=as_datetime(row.ordered_at),
        currency=currency,
        seller=Party(
            party_id=row.seller_id,
            name=row.seller_name,
            country=row.seller_country,
            vat_id=row.seller_vat_id,
        ),
        buyer=Party(
            party_id=row.buyer_id,
            name=row.buyer_name,
            country=row.buyer_country,
            vat_id=row.buyer_vat_id,
        ),
        lines=lines,
        net_total=Money(as_decimal(row.net_amount), currency),
        vat_total=Money(as_decimal(row.vat_amount), currency),
        gross_total=Money(as_decimal(row.gross_amount), currency),
        content_hash=row.content_hash,
        version=row.version,
        last_load_id=row.last_load_id,
    )


def _line_from_row(row: InvoiceLineRow, currency: str) -> InvoiceLine:
    return InvoiceLine(
        line_no=row.line_no,
        sku=row.sku,
        description=row.description,
        quantity=as_decimal(row.quantity),
        unit_net=Money(as_decimal(row.unit_net), currency),
        line_net=Money(as_decimal(row.line_net), currency),
        vat_code=row.vat_code,
        vat_rate=as_decimal(row.vat_rate),
        vat_treatment=row.vat_treatment,
        vat_amount=Money(as_decimal(row.vat_amount), currency),
        line_gross=Money(as_decimal(row.line_gross), currency),
    )


def _stored_from_row(row: IdempotencyRow) -> StoredLoad:
    return StoredLoad(
        idempotency_key=row.idempotency_key,
        request_hash=row.request_hash,
        http_status=row.http_status,
        receipt=receipt_from_json(row.response_json),
        created_at=as_datetime(row.created_at),
    )
