"""Turn a raw order into an invoice. Money math stays in Decimal."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from etl_pipeline.domain.errors import (
    EmptyOrder,
    InvalidIdentifier,
    InvalidLine,
    InvalidParty,
    InvalidQuantity,
    InvalidUnitPrice,
    InvalidVatId,
    NaiveTimestamp,
    QuantityScale,
    UnitPriceScale,
    UnsupportedCurrency,
)
from etl_pipeline.domain.models import (
    Invoice,
    InvoiceLine,
    Party,
    RawOrder,
    RawOrderLine,
    fingerprint,
)
from etl_pipeline.domain.money import Money, decimal_scale, sum_money, tax_amount
from etl_pipeline.domain.time import ensure_utc
from etl_pipeline.domain.vat import EU_COUNTRIES, VatPolicy, normalize_country, normalize_vat_id

SUPPORTED_CURRENCIES = frozenset({"EUR", "GBP", "PLN", "RON", "USD"})
_MAX_QUANTITY = Decimal("1000000")
_MAX_UNIT_PRICE = Decimal("1000000000")
_PARTY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SKU = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SOURCE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
_EXTERNAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FOREIGN_TAX = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,19}$")


class InvoiceTransformer:
    def __init__(self, policy: VatPolicy | None = None) -> None:
        self._policy = policy or VatPolicy()

    def transform(self, order: RawOrder) -> Invoice:
        source_system = order.source_system.strip().lower()
        external_id = order.external_id.strip()
        if _SOURCE.fullmatch(source_system) is None:
            raise InvalidIdentifier(f"source_system {order.source_system!r} is not canonical")
        if _EXTERNAL.fullmatch(external_id) is None:
            raise InvalidIdentifier(f"external_id {order.external_id!r} is not canonical")
        if order.ordered_at.tzinfo is None:
            raise NaiveTimestamp()
        currency = order.currency.strip().upper()
        if currency not in SUPPORTED_CURRENCIES:
            raise UnsupportedCurrency(currency)
        if not order.lines:
            raise EmptyOrder()

        seller = _normalize_party(order.seller, role="seller", require_vat=True)
        buyer = _normalize_party(order.buyer, role="buyer", require_vat=False)
        ordered_at = ensure_utc(order.ordered_at)

        lines: list[InvoiceLine] = []
        for index, raw_line in enumerate(order.lines, start=1):
            lines.append(
                self._line(
                    index,
                    raw_line,
                    currency=currency,
                    seller=seller,
                    buyer=buyer,
                )
            )
        built = tuple(lines)
        net_total = sum_money((line.line_net for line in built), currency)
        vat_total = sum_money((line.vat_amount for line in built), currency)
        gross_total = sum_money((line.line_gross for line in built), currency)
        digest = _fingerprint_body(
            source_system=source_system,
            external_id=external_id,
            ordered_at=ordered_at,
            currency=currency,
            seller=seller,
            buyer=buyer,
            lines=built,
            net_total=net_total,
            vat_total=vat_total,
            gross_total=gross_total,
        )
        return Invoice(
            source_system=source_system,
            external_id=external_id,
            ordered_at=ordered_at,
            currency=currency,
            seller=seller,
            buyer=buyer,
            lines=built,
            net_total=net_total,
            vat_total=vat_total,
            gross_total=gross_total,
            content_hash=digest,
        )

    def _line(
        self,
        line_no: int,
        raw_line: RawOrderLine,
        *,
        currency: str,
        seller: Party,
        buyer: Party,
    ) -> InvoiceLine:
        sku = raw_line.sku.strip()
        if _SKU.fullmatch(sku) is None:
            raise InvalidLine(f"line {line_no} sku {raw_line.sku!r} is not canonical")
        description = _clean_text(raw_line.description, limit=200, field=f"line {line_no} description")
        quantity = _quantity(raw_line.quantity, line_no)
        unit_price = _unit_price(raw_line.unit_price, line_no)
        decision = self._policy.resolve(seller, buyer, raw_line.vat_category)
        unit_net = Money(unit_price, currency).quantized(4)
        line_net = (unit_net * quantity).quantized(2)
        vat = tax_amount(line_net, decision.rate)
        line_gross = line_net + vat
        return InvoiceLine(
            line_no=line_no,
            sku=sku,
            description=description,
            quantity=quantity,
            unit_net=unit_net,
            line_net=line_net,
            vat_code=decision.code,
            vat_rate=decision.rate,
            vat_treatment=decision.treatment.value,
            vat_amount=vat,
            line_gross=line_gross,
        )


def _fingerprint_body(
    *,
    source_system: str,
    external_id: str,
    ordered_at: datetime,
    currency: str,
    seller: Party,
    buyer: Party,
    lines: tuple[InvoiceLine, ...],
    net_total: Money,
    vat_total: Money,
    gross_total: Money,
) -> str:
    """Hash the commercial body. `Invoice.__post_init__` checks this same function."""
    invoice = object.__new__(Invoice)
    object.__setattr__(invoice, "source_system", source_system)
    object.__setattr__(invoice, "external_id", external_id)
    object.__setattr__(invoice, "ordered_at", ordered_at)
    object.__setattr__(invoice, "currency", currency)
    object.__setattr__(invoice, "seller", seller)
    object.__setattr__(invoice, "buyer", buyer)
    object.__setattr__(invoice, "lines", lines)
    object.__setattr__(invoice, "net_total", net_total)
    object.__setattr__(invoice, "vat_total", vat_total)
    object.__setattr__(invoice, "gross_total", gross_total)
    object.__setattr__(invoice, "content_hash", "")
    object.__setattr__(invoice, "version", 1)
    object.__setattr__(invoice, "last_load_id", None)
    return fingerprint(invoice)


def _normalize_party(party: Party, *, role: str, require_vat: bool) -> Party:
    if _PARTY_ID.fullmatch(party.party_id.strip()) is None:
        raise InvalidParty(f"{role} party_id {party.party_id!r} is not canonical")
    name = _clean_text(party.name, limit=120, field=f"{role} name")
    country = normalize_country(party.country)
    vat_id = _vat_id(party.vat_id, country, role=role, required=require_vat)
    return Party(party_id=party.party_id.strip(), name=name, country=country, vat_id=vat_id)


def _vat_id(value: str | None, country: str, *, role: str, required: bool) -> str | None:
    if value is None or not value.strip():
        if required:
            from etl_pipeline.domain.errors import MissingSellerVatId

            raise MissingSellerVatId()
        return None
    if country in EU_COUNTRIES or required:
        try:
            return normalize_vat_id(country, value)
        except InvalidVatId as exc:
            raise InvalidVatId(f"{role} {exc.message}") from exc
    normalized = re.sub(r"\s+", "", value).upper()
    if _FOREIGN_TAX.fullmatch(normalized) is None:
        raise InvalidVatId(f"{role} tax id {value!r} is not a usable token")
    return normalized


def _quantity(value: Decimal, line_no: int) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvalidQuantity(f"line {line_no} quantity must be a finite Decimal")
    if value <= 0 or value > _MAX_QUANTITY:
        raise InvalidQuantity(f"line {line_no} quantity must be > 0 and <= {_MAX_QUANTITY}")
    scale = decimal_scale(value)
    if scale > 3:
        raise QuantityScale(scale)
    return value


def _unit_price(value: Decimal, line_no: int) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvalidUnitPrice(f"line {line_no} unit price must be a finite Decimal")
    if value < 0 or value > _MAX_UNIT_PRICE:
        raise InvalidUnitPrice(f"line {line_no} unit price must be >= 0 and <= {_MAX_UNIT_PRICE}")
    scale = decimal_scale(value)
    if scale > 4:
        raise UnitPriceScale(scale)
    return value


def _clean_text(value: str, *, limit: int, field: str) -> str:
    if "\x00" in value:
        raise InvalidLine(f"{field} contains a NUL")
    cleaned = " ".join(value.split())
    if not cleaned:
        raise InvalidLine(f"{field} is empty")
    if len(cleaned) > limit:
        raise InvalidLine(f"{field} exceeds {limit} characters")
    return cleaned
