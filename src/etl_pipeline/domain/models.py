"""Commercial documents. Hashing uses quantized decimals so reloads compare equal."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from etl_pipeline.domain.errors import InvariantError
from etl_pipeline.domain.money import Money, format_decimal, sum_money
from etl_pipeline.domain.time import ensure_utc

_SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
_EXTERNAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


@dataclass(frozen=True, slots=True)
class Party:
    party_id: str
    name: str
    country: str
    vat_id: str | None


@dataclass(frozen=True, slots=True)
class RawOrderLine:
    sku: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    vat_category: str


@dataclass(frozen=True, slots=True)
class RawOrder:
    source_system: str
    external_id: str
    ordered_at: datetime
    currency: str
    seller: Party
    buyer: Party
    lines: tuple[RawOrderLine, ...]

    @property
    def natural_key(self) -> tuple[str, str]:
        return (self.source_system, self.external_id)


@dataclass(frozen=True, slots=True)
class InvoiceLine:
    line_no: int
    sku: str
    description: str
    quantity: Decimal
    unit_net: Money
    line_net: Money
    vat_code: str
    vat_rate: Decimal
    vat_treatment: str
    vat_amount: Money
    line_gross: Money


@dataclass(frozen=True, slots=True)
class Invoice:
    source_system: str
    external_id: str
    ordered_at: datetime
    currency: str
    seller: Party
    buyer: Party
    lines: tuple[InvoiceLine, ...]
    net_total: Money
    vat_total: Money
    gross_total: Money
    content_hash: str
    version: int = 1
    last_load_id: str | None = None

    def __post_init__(self) -> None:
        if self.version < 1:
            raise InvariantError("version must be >= 1")
        if not isinstance(self.net_total, Money):
            raise InvariantError("totals must be Money")
        if self.net_total.currency != self.currency:
            raise InvariantError("net currency does not match the invoice")
        if self.vat_total.currency != self.currency or self.gross_total.currency != self.currency:
            raise InvariantError("VAT or gross currency does not match the invoice")
        net = sum_money((line.line_net for line in self.lines), self.currency)
        vat = sum_money((line.vat_amount for line in self.lines), self.currency)
        gross = sum_money((line.line_gross for line in self.lines), self.currency)
        if net != self.net_total or vat != self.vat_total or gross != self.gross_total:
            raise InvariantError("stored totals do not match the lines")
        if self.gross_total != self.net_total + self.vat_total:
            raise InvariantError("gross is not net plus VAT")
        if self.content_hash != fingerprint(self):
            raise InvariantError("content hash does not match the invoice body")
        if not _SOURCE_RE.fullmatch(self.source_system):
            raise InvariantError("source_system is not canonical")
        if not _EXTERNAL_RE.fullmatch(self.external_id):
            raise InvariantError("external_id is not canonical")

    @property
    def natural_key(self) -> tuple[str, str]:
        return (self.source_system, self.external_id)


@dataclass(frozen=True, slots=True)
class InvoiceSummary:
    source_system: str
    external_id: str
    ordered_at: datetime
    currency: str
    net_total: Money
    vat_total: Money
    gross_total: Money
    version: int
    line_count: int


@dataclass(frozen=True, slots=True)
class Rejection:
    source_system: str
    external_id: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class UpsertStats:
    inserted: int
    updated: int
    unchanged: int


def fingerprint(invoice: Invoice) -> str:
    """Stable hash of the commercial body. Version and load id are excluded."""
    ordered = ensure_utc(invoice.ordered_at).isoformat()
    payload = {
        "buyer": _party_payload(invoice.buyer),
        "currency": invoice.currency,
        "external_id": invoice.external_id,
        "gross_total": format_decimal(invoice.gross_total.amount, 2),
        "lines": [_line_payload(line) for line in invoice.lines],
        "net_total": format_decimal(invoice.net_total.amount, 2),
        "ordered_at": ordered,
        "seller": _party_payload(invoice.seller),
        "source_system": invoice.source_system,
        "vat_total": format_decimal(invoice.vat_total.amount, 2),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def request_fingerprint(source_system: str, orders: Sequence[RawOrder]) -> str:
    """Semantic hash of a load body. Order of `orders` is significant."""
    payload = {
        "orders": [_raw_order_payload(order) for order in orders],
        "source_system": source_system,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _party_payload(party: Party) -> dict[str, str | None]:
    return {
        "country": party.country,
        "name": party.name,
        "party_id": party.party_id,
        "vat_id": party.vat_id,
    }


def _line_payload(line: InvoiceLine) -> dict[str, str | int]:
    return {
        "description": line.description,
        "line_gross": format_decimal(line.line_gross.amount, 2),
        "line_net": format_decimal(line.line_net.amount, 2),
        "line_no": line.line_no,
        "quantity": format_decimal(line.quantity, 3),
        "sku": line.sku,
        "unit_net": format_decimal(line.unit_net.amount, 4),
        "vat_amount": format_decimal(line.vat_amount.amount, 2),
        "vat_code": line.vat_code,
        "vat_rate": format_decimal(line.vat_rate, 4),
        "vat_treatment": line.vat_treatment,
    }


def _raw_order_payload(order: RawOrder) -> dict[str, object]:
    return {
        "buyer": _party_payload(order.buyer),
        "currency": order.currency,
        "external_id": order.external_id,
        "lines": [
            {
                "description": line.description,
                "quantity": format(line.quantity, "f"),
                "sku": line.sku,
                "unit_price": format(line.unit_price, "f"),
                "vat_category": line.vat_category,
            }
            for line in order.lines
        ],
        "ordered_at": order.ordered_at.astimezone(UTC).isoformat(),
        "seller": _party_payload(order.seller),
        "source_system": order.source_system,
    }
