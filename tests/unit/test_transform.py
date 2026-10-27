from decimal import Decimal

import pytest

from etl_pipeline.application.transform import InvoiceTransformer
from etl_pipeline.domain.errors import InvalidQuantity, NaiveTimestamp, QuantityScale
from etl_pipeline.domain.money import Money
from tests.conftest import buyer_de, line, order, seller


def test_domestic_invoice_totals_are_sum_of_rounded_lines() -> None:
    invoice = InvoiceTransformer().transform(
        order(lines=(line(), line("SKU-2", "Reduced spare", "1", "5.00", "reduced")))
    )
    assert invoice.net_total == Money(Decimal("26.00"), "EUR")
    assert invoice.vat_total == Money(Decimal("4.34"), "EUR")
    assert invoice.gross_total == Money(Decimal("30.34"), "EUR")
    assert invoice.lines[0].vat_amount == Money(Decimal("3.99"), "EUR")
    assert invoice.lines[1].vat_code == "DE-RED"
    assert invoice.lines[1].vat_amount == Money(Decimal("0.35"), "EUR")
    assert invoice.content_hash == InvoiceTransformer().transform(
        order(lines=(line(), line("SKU-2", "Reduced spare", "1", "5.00", "reduced")))
    ).content_hash


def test_sub_cent_vat_rounds_half_up() -> None:
    invoice = InvoiceTransformer().transform(order(lines=(line(quantity="3", unit_price="0.10"),)))
    assert invoice.lines[0].line_net == Money(Decimal("0.30"), "EUR")
    # 0.30 * 0.19 = 0.057 -> 0.06
    assert invoice.lines[0].vat_amount == Money(Decimal("0.06"), "EUR")
    assert invoice.gross_total == Money(Decimal("0.36"), "EUR")


def test_unit_price_is_rounded_to_cents_on_the_line_net() -> None:
    invoice = InvoiceTransformer().transform(order(lines=(line(quantity="1", unit_price="10.005"),)))
    assert invoice.lines[0].unit_net == Money(Decimal("10.0050"), "EUR")
    assert invoice.lines[0].line_net == Money(Decimal("10.01"), "EUR")
    assert invoice.lines[0].vat_amount == Money(Decimal("1.90"), "EUR")


def test_reverse_charge_export_and_hash_changes_with_price() -> None:
    transformer = InvoiceTransformer()
    reverse = transformer.transform(
        order(
            external_id="INV-200",
            buyer=__import__("etl_pipeline.domain.models", fromlist=["Party"]).Party(
                "BUY-2", "Transilvania SRL", "RO", "RO12345678"
            ),
            lines=(line(quantity="4"),),
        )
    )
    assert reverse.vat_total == Money(Decimal("0.00"), "EUR")
    assert reverse.lines[0].vat_code == "EU-RC"
    assert reverse.gross_total == Money(Decimal("42.00"), "EUR")

    exported = transformer.transform(
        order(
            external_id="INV-300",
            buyer=__import__("etl_pipeline.domain.models", fromlist=["Party"]).Party(
                "BUY-3", "Acme LLC", "US", None
            ),
            lines=(line(quantity="1", unit_price="100.00", sku="SKU-9", description="Export crate"),),
        )
    )
    assert exported.lines[0].vat_treatment == "export"
    assert exported.gross_total == Money(Decimal("100.00"), "EUR")

    changed = transformer.transform(order(lines=(line(unit_price="10.51"),)))
    original = transformer.transform(order())
    assert changed.content_hash != original.content_hash


def test_rejections() -> None:
    transformer = InvoiceTransformer()
    with pytest.raises(InvalidQuantity):
        transformer.transform(order(lines=(line(quantity="-1"),)))
    with pytest.raises(QuantityScale):
        transformer.transform(order(lines=(line(quantity="1.1234"),)))
    naive = order().ordered_at.replace(tzinfo=None)
    with pytest.raises(NaiveTimestamp):
        transformer.transform(order(ordered_at=naive))


def test_seller_and_buyer_are_used() -> None:
    invoice = InvoiceTransformer().transform(order())
    assert invoice.seller == seller()
    assert invoice.buyer.country == buyer_de().country
