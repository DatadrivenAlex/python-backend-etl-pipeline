"""Shared builders. Tests stay offline: SQLite in memory, no network."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from etl_pipeline.domain.models import Party, RawOrder, RawOrderLine

FIXTURES = __import__("pathlib").Path(__file__).resolve().parent / "fixtures"


def seller() -> Party:
    return Party("SELL-1", "Nordlicht GmbH", "DE", "DE123456789")


def buyer_de() -> Party:
    return Party("BUY-1", "Müller AG", "DE", "DE987654321")


def line(
    sku: str = "SKU-1",
    description: str = "Copper busbar",
    quantity: str = "2",
    unit_price: str = "10.50",
    vat_category: str = "standard",
) -> RawOrderLine:
    return RawOrderLine(sku, description, Decimal(quantity), Decimal(unit_price), vat_category)


def order(**overrides: object) -> RawOrder:
    payload: dict[str, object] = {
        "source_system": "erp-de",
        "external_id": "INV-100",
        "ordered_at": datetime(2026, 1, 15, 8, 30, tzinfo=UTC),
        "currency": "EUR",
        "seller": seller(),
        "buyer": buyer_de(),
        "lines": (line(),),
    }
    payload.update(overrides)
    return RawOrder(**payload)  # type: ignore[arg-type]


def api_order(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "external_id": "INV-100",
        "ordered_at": "2026-01-15T08:30:00+00:00",
        "currency": "EUR",
        "seller": {
            "party_id": "SELL-1",
            "name": "Nordlicht GmbH",
            "country": "DE",
            "vat_id": "DE123456789",
        },
        "buyer": {
            "party_id": "BUY-1",
            "name": "Müller AG",
            "country": "DE",
            "vat_id": "DE987654321",
        },
        "lines": [
            {
                "sku": "SKU-1",
                "description": "Copper busbar",
                "quantity": "2",
                "unit_price": "10.50",
                "vat_category": "standard",
            }
        ],
    }
    body.update(overrides)
    return body
