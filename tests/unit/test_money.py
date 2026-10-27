from decimal import Decimal

import pytest

from etl_pipeline.domain.errors import CurrencyMismatch
from etl_pipeline.domain.money import Money, sum_money, tax_amount


def test_float_is_rejected() -> None:
    with pytest.raises(TypeError):
        Money(0.1, "EUR")  # type: ignore[arg-type]


def test_half_up_not_bankers_rounding() -> None:
    # ROUND_HALF_EVEN would keep 0.02. Commercial VAT rounds half away from zero.
    assert Money(Decimal("0.025"), "EUR").quantized(2) == Money(Decimal("0.03"), "EUR")
    assert Money(Decimal("1.005"), "EUR").quantized(2) == Money(Decimal("1.01"), "EUR")
    assert Money(Decimal("1.004"), "EUR").quantized(2) == Money(Decimal("1.00"), "EUR")


def test_tax_amount_uses_the_same_rounding() -> None:
    net = Money(Decimal("1.00"), "EUR")
    assert tax_amount(net, Decimal("0.025")) == Money(Decimal("0.03"), "EUR")


def test_currency_mismatch() -> None:
    with pytest.raises(CurrencyMismatch):
        Money(Decimal("1.00"), "EUR") + Money(Decimal("1.00"), "USD")


def test_multiply_rejects_float() -> None:
    with pytest.raises(TypeError):
        Money(Decimal("2"), "EUR") * 1.5  # type: ignore[operator]


def test_sum_quantizes_to_cents() -> None:
    total = sum_money(
        [Money(Decimal("10.005"), "EUR"), Money(Decimal("0.004"), "EUR")],
        "EUR",
    )
    assert total == Money(Decimal("10.01"), "EUR")
