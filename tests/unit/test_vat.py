from decimal import Decimal

import pytest

from etl_pipeline.domain.errors import InvalidVatId, UnknownSellerJurisdiction, UnknownVatCategory
from etl_pipeline.domain.models import Party
from etl_pipeline.domain.vat import VatPolicy, VatTreatment


def _party(country: str, vat_id: str | None, party_id: str = "P") -> Party:
    return Party(party_id, "Name", country, vat_id)


def test_domestic_german_rates() -> None:
    policy = VatPolicy()
    seller = _party("DE", "DE123456789", "S")
    buyer = _party("de", "DE987654321", "B")
    standard = policy.resolve(seller, buyer, "standard")
    reduced = policy.resolve(seller, buyer, "reduced")
    assert standard.code == "DE-STD"
    assert standard.rate == Decimal("0.19")
    assert standard.treatment is VatTreatment.STANDARD
    assert reduced.rate == Decimal("0.07")
    assert reduced.code == "DE-RED"


def test_reverse_charge_when_buyer_vat_id_is_valid() -> None:
    decision = VatPolicy().resolve(
        _party("DE", "DE123456789", "S"),
        _party("RO", "RO12345678", "B"),
        "standard",
    )
    assert decision.code == "EU-RC"
    assert decision.rate == Decimal("0")
    assert decision.treatment is VatTreatment.REVERSE_CHARGE


def test_invalid_buyer_vat_id_is_not_guessed() -> None:
    with pytest.raises(InvalidVatId):
        VatPolicy().resolve(
            _party("DE", "DE123456789", "S"),
            _party("FR", "FR12", "B"),
            "standard",
        )


def test_cross_border_b2c_uses_seller_rate() -> None:
    decision = VatPolicy().resolve(
        _party("DE", "DE123456789", "S"),
        _party("FR", None, "B"),
        "standard",
    )
    assert decision.code == "DE-STD-B2C"
    assert decision.rate == Decimal("0.19")
    assert decision.treatment is VatTreatment.B2C_CROSS_BORDER


def test_export_outside_the_eu() -> None:
    decision = VatPolicy().resolve(
        _party("DE", "DE123456789", "S"),
        _party("US", None, "B"),
        "standard",
    )
    assert decision.code == "EXPORT-0"
    assert decision.rate == Decimal("0")
    assert decision.treatment is VatTreatment.EXPORT


def test_unknown_category_and_seller_country() -> None:
    seller = _party("DE", "DE123456789", "S")
    buyer = _party("DE", None, "B")
    with pytest.raises(UnknownVatCategory):
        VatPolicy().resolve(seller, buyer, "luxury")
    with pytest.raises(UnknownSellerJurisdiction):
        VatPolicy().resolve(_party("US", "US-1", "S"), buyer, "standard")
