"""Relational model. SQLAlchemy stays in this package; the domain never imports it."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class InvoiceRow(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("source_system", "external_id", name="uq_invoice_natural_key"),
        Index("ix_invoices_ordered_at", "ordered_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    seller_id: Mapped[str] = mapped_column(String(64), nullable=False)
    seller_name: Mapped[str] = mapped_column(String(120), nullable=False)
    seller_country: Mapped[str] = mapped_column(String(2), nullable=False)
    seller_vat_id: Mapped[str] = mapped_column(String(20), nullable=False)
    buyer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    buyer_name: Mapped[str] = mapped_column(String(120), nullable=False)
    buyer_country: Mapped[str] = mapped_column(String(2), nullable=False)
    buyer_vat_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2, asdecimal=True), nullable=False)
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2, asdecimal=True), nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2, asdecimal=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    last_load_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lines: Mapped[list[InvoiceLineRow]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="InvoiceLineRow.line_no",
    )


class InvoiceLineRow(Base):
    __tablename__ = "invoice_lines"
    __table_args__ = (
        UniqueConstraint("invoice_id", "line_no", name="uq_invoice_line_no"),
        Index("ix_invoice_lines_invoice_id", "invoice_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    invoice_id: Mapped[str] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3, asdecimal=True), nullable=False)
    unit_net: Mapped[Decimal] = mapped_column(Numeric(18, 4, asdecimal=True), nullable=False)
    line_net: Mapped[Decimal] = mapped_column(Numeric(18, 2, asdecimal=True), nullable=False)
    vat_code: Mapped[str] = mapped_column(String(32), nullable=False)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(8, 4, asdecimal=True), nullable=False)
    vat_treatment: Mapped[str] = mapped_column(String(32), nullable=False)
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2, asdecimal=True), nullable=False)
    line_gross: Mapped[Decimal] = mapped_column(Numeric(18, 2, asdecimal=True), nullable=False)
    invoice: Mapped[InvoiceRow] = relationship(back_populates="lines")


class RejectionRow(Base):
    __tablename__ = "rejections"
    __table_args__ = (Index("ix_rejections_load_id", "load_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    load_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IdempotencyRow(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (Index("ix_idempotency_load_id", "load_id"),)

    idempotency_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    load_id: Mapped[str] = mapped_column(String(36), nullable=False)
    http_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
