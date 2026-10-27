"""Exact money. Floats are rejected so binary fractions never reach a ledger."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from etl_pipeline.domain.errors import CurrencyMismatch

# Commercial invoices in this service round half away from zero (ROUND_HALF_UP).
# Banker's rounding (ROUND_HALF_EVEN) would turn 0.025 into 0.02 and surprise finance.
_ROUNDING = ROUND_HALF_UP


def quantize_decimal(value: Decimal, places: int) -> Decimal:
    if places < 0:
        raise ValueError("places must be >= 0")
    quantum = Decimal("1").scaleb(-places)
    return value.quantize(quantum, rounding=_ROUNDING)


def decimal_scale(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        return 0
    return max(0, -exponent)


@dataclass(frozen=True, slots=True)
class Money:
    """An amount in one ISO currency. Not auto-quantized, so unit prices can keep 4 dp."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if isinstance(self.amount, float):
            raise TypeError("Money rejects float; construct it from Decimal")
        if not isinstance(self.amount, Decimal):
            raise TypeError("amount must be Decimal")
        if not self.amount.is_finite():
            raise ValueError("amount must be finite")
        if (
            not isinstance(self.currency, str)
            or len(self.currency) != 3
            or not self.currency.isalpha()
            or self.currency != self.currency.upper()
        ):
            raise ValueError("currency must be a 3-letter uppercase ISO code")

    def quantized(self, places: int = 2) -> Money:
        return Money(quantize_decimal(self.amount, places), self.currency)

    def add(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __add__(self, other: object) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        return self.add(other)

    def __mul__(self, factor: object) -> Money:
        if isinstance(factor, float) or not isinstance(factor, Decimal):
            raise TypeError("multiply Money by Decimal only")
        return Money(self.amount * factor, self.currency)

    def _same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatch(self.currency, other.currency)


def sum_money(items: Iterable[Money], currency: str) -> Money:
    total = Money(Decimal("0"), currency)
    for item in items:
        total = total.add(item)
    return total.quantized(2)


def format_decimal(value: Decimal, places: int) -> str:
    return format(quantize_decimal(value, places), "f")


def tax_amount(net: Money, rate: Decimal) -> Money:
    """VAT due on an already rounded net. The rate is a fraction (`0.19`), not a percent."""
    if isinstance(rate, float) or not isinstance(rate, Decimal):
        raise TypeError("rate must be Decimal")
    return Money(net.amount * rate, net.currency).quantized(2)
