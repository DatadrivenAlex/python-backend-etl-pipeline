"""Domain failures a caller can record as row rejections."""

from __future__ import annotations


class DomainError(Exception):
    """Business rule violation. `code` is stable for metrics and clients."""

    code = "DOMAIN_ERROR"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class EmptyOrder(DomainError):
    code = "EMPTY_ORDER"

    def __init__(self) -> None:
        super().__init__("order has no lines")


class InvalidQuantity(DomainError):
    code = "INVALID_QUANTITY"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class QuantityScale(DomainError):
    code = "QUANTITY_SCALE"

    def __init__(self, scale: int) -> None:
        super().__init__(f"quantity scale {scale} exceeds 3 decimal places")


class InvalidUnitPrice(DomainError):
    code = "INVALID_UNIT_PRICE"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class UnitPriceScale(DomainError):
    code = "UNIT_PRICE_SCALE"

    def __init__(self, scale: int) -> None:
        super().__init__(f"unit price scale {scale} exceeds 4 decimal places")


class UnsupportedCurrency(DomainError):
    code = "UNSUPPORTED_CURRENCY"

    def __init__(self, currency: str) -> None:
        super().__init__(f"currency {currency!r} is not supported")


class InvalidCountry(DomainError):
    code = "INVALID_COUNTRY"

    def __init__(self, country: str) -> None:
        super().__init__(f"country {country!r} is not an ISO 3166-1 alpha-2 code")


class UnknownSellerJurisdiction(DomainError):
    code = "UNKNOWN_SELLER_JURISDICTION"

    def __init__(self, country: str) -> None:
        super().__init__(f"no VAT rate card for seller country {country}")


class UnknownVatCategory(DomainError):
    code = "UNKNOWN_VAT_CATEGORY"

    def __init__(self, category: str, country: str) -> None:
        super().__init__(f"VAT category {category!r} is not valid in {country}")


class InvalidVatId(DomainError):
    code = "INVALID_VAT_ID"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class MissingSellerVatId(DomainError):
    code = "MISSING_SELLER_VAT_ID"

    def __init__(self) -> None:
        super().__init__("seller VAT id is required")


class InvalidParty(DomainError):
    code = "INVALID_PARTY"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class InvalidIdentifier(DomainError):
    code = "INVALID_IDENTIFIER"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class InvalidLine(DomainError):
    code = "INVALID_LINE"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class NaiveTimestamp(DomainError):
    code = "NAIVE_TIMESTAMP"

    def __init__(self) -> None:
        super().__init__("ordered_at must include a timezone offset")


class UnbalancedTotals(DomainError):
    code = "UNBALANCED_TOTALS"

    def __init__(self) -> None:
        super().__init__("invoice gross does not equal net plus VAT")


class InvariantError(DomainError):
    code = "INVARIANT"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class CurrencyMismatch(DomainError):
    code = "CURRENCY_MISMATCH"

    def __init__(self, left: str, right: str) -> None:
        super().__init__(f"cannot combine {left} with {right}")
