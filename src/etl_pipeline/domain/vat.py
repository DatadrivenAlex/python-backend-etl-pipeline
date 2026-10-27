"""EU VAT decisions used by the transformer.

The rate card is intentionally small and explicit. Format checks are structural
(prefix and length), not checksums and not a VIES lookup. Cross-border B2C is
charged at the seller's rate: this is not a One-Stop-Shop destination engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from etl_pipeline.domain.errors import (
    InvalidCountry,
    InvalidVatId,
    MissingSellerVatId,
    UnknownSellerJurisdiction,
    UnknownVatCategory,
)
from etl_pipeline.domain.models import Party

EU_COUNTRIES = frozenset(
    {
        "AT",
        "BE",
        "BG",
        "CY",
        "CZ",
        "DE",
        "DK",
        "EE",
        "ES",
        "FI",
        "FR",
        "GR",
        "HR",
        "HU",
        "IE",
        "IT",
        "LT",
        "LU",
        "LV",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SE",
        "SI",
        "SK",
    }
)

# Standard / reduced / super-reduced rates as Decimal fractions, not percents.
RATE_CARD: dict[str, dict[str, Decimal]] = {
    "AT": {"standard": Decimal("0.20"), "reduced": Decimal("0.10")},
    "DE": {"standard": Decimal("0.19"), "reduced": Decimal("0.07")},
    "ES": {"standard": Decimal("0.21"), "reduced": Decimal("0.10")},
    "FR": {
        "standard": Decimal("0.20"),
        "reduced": Decimal("0.10"),
        "super_reduced": Decimal("0.055"),
    },
    "GR": {"standard": Decimal("0.24"), "reduced": Decimal("0.13")},
    "IT": {"standard": Decimal("0.22"), "reduced": Decimal("0.10")},
    "NL": {"standard": Decimal("0.21"), "reduced": Decimal("0.09")},
    "PL": {"standard": Decimal("0.23"), "reduced": Decimal("0.08")},
    "RO": {"standard": Decimal("0.19"), "reduced": Decimal("0.09")},
}

_CATEGORY_CODE = {"standard": "STD", "reduced": "RED", "super_reduced": "SRED"}

# Greece's ISO country code is GR; its VAT prefix is EL.
_VAT_PATTERNS: dict[str, re.Pattern[str]] = {
    "AT": re.compile(r"^ATU\d{8}$"),
    "BE": re.compile(r"^BE[01]\d{9}$"),
    "BG": re.compile(r"^BG\d{9,10}$"),
    "CY": re.compile(r"^CY\d{8}[A-Z]$"),
    "CZ": re.compile(r"^CZ\d{8,10}$"),
    "DE": re.compile(r"^DE\d{9}$"),
    "DK": re.compile(r"^DK\d{8}$"),
    "EE": re.compile(r"^EE\d{9}$"),
    "ES": re.compile(r"^ES[A-Z0-9]\d{7}[A-Z0-9]$"),
    "FI": re.compile(r"^FI\d{8}$"),
    "FR": re.compile(r"^FR[A-HJ-NP-Z0-9]{2}\d{9}$"),
    "GR": re.compile(r"^EL\d{9}$"),
    "HR": re.compile(r"^HR\d{11}$"),
    "HU": re.compile(r"^HU\d{8}$"),
    "IE": re.compile(r"^IE[A-Z0-9]{7,9}$"),
    "IT": re.compile(r"^IT\d{11}$"),
    "LT": re.compile(r"^LT(\d{9}|\d{12})$"),
    "LU": re.compile(r"^LU\d{8}$"),
    "LV": re.compile(r"^LV\d{11}$"),
    "MT": re.compile(r"^MT\d{8}$"),
    "NL": re.compile(r"^NL\d{9}B\d{2}$"),
    "PL": re.compile(r"^PL\d{10}$"),
    "PT": re.compile(r"^PT\d{9}$"),
    "RO": re.compile(r"^RO\d{2,10}$"),
    "SE": re.compile(r"^SE\d{12}$"),
    "SI": re.compile(r"^SI\d{8}$"),
    "SK": re.compile(r"^SK\d{10}$"),
}


class VatTreatment(StrEnum):
    STANDARD = "standard"
    REDUCED = "reduced"
    SUPER_REDUCED = "super_reduced"
    REVERSE_CHARGE = "reverse_charge"
    EXPORT = "export"
    B2C_CROSS_BORDER = "b2c_cross_border"


@dataclass(frozen=True, slots=True)
class VatRate:
    code: str
    rate: Decimal
    treatment: VatTreatment


def normalize_country(value: str) -> str:
    country = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise InvalidCountry(value)
    return country


def normalize_vat_id(country: str, vat_id: str) -> str:
    """Return the canonical VAT id or raise InvalidVatId."""
    normalized = re.sub(r"\s+", "", vat_id).upper()
    pattern = _VAT_PATTERNS.get(country)
    if pattern is None or pattern.fullmatch(normalized) is None:
        raise InvalidVatId(f"VAT id {vat_id!r} does not match the {country} format")
    return normalized


class VatPolicy:
    """Resolve the rate that applies to one invoice line."""

    def resolve(self, seller: Party, buyer: Party, category: str) -> VatRate:
        seller_country = normalize_country(seller.country)
        buyer_country = normalize_country(buyer.country)
        if seller_country not in RATE_CARD:
            raise UnknownSellerJurisdiction(seller_country)
        if seller.vat_id is None or not seller.vat_id.strip():
            raise MissingSellerVatId()
        normalize_vat_id(seller_country, seller.vat_id)

        if buyer_country not in EU_COUNTRIES:
            return VatRate(code="EXPORT-0", rate=Decimal("0"), treatment=VatTreatment.EXPORT)

        cross_border = buyer_country != seller_country
        if cross_border and buyer.vat_id is not None and buyer.vat_id.strip():
            normalize_vat_id(buyer_country, buyer.vat_id)
            return VatRate(
                code="EU-RC",
                rate=Decimal("0"),
                treatment=VatTreatment.REVERSE_CHARGE,
            )

        category_key = category.strip().lower()
        rates = RATE_CARD[seller_country]
        if category_key not in rates:
            raise UnknownVatCategory(category_key, seller_country)
        treatment = _domestic_treatment(category_key)
        code = f"{seller_country}-{_CATEGORY_CODE[category_key]}"
        if cross_border:
            treatment = VatTreatment.B2C_CROSS_BORDER
            code = f"{code}-B2C"
        return VatRate(code=code, rate=rates[category_key], treatment=treatment)


def _domestic_treatment(category_key: str) -> VatTreatment:
    if category_key == "standard":
        return VatTreatment.STANDARD
    if category_key == "super_reduced":
        return VatTreatment.SUPER_REDUCED
    return VatTreatment.REDUCED
