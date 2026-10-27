"""Public HTTP bodies. Money is a string so JSON never turns it into a binary float."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PartyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    party_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    country: str = Field(min_length=2, max_length=2)
    vat_id: str | None = Field(default=None, max_length=20)


class OrderLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=200)
    quantity: Decimal
    unit_price: Decimal
    vat_category: str = Field(min_length=1, max_length=32)


class OrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    ordered_at: datetime
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    seller: PartyIn
    buyer: PartyIn
    lines: list[OrderLineIn] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def ordered_at_is_aware(self) -> OrderIn:
        if self.ordered_at.tzinfo is None:
            raise ValueError("ordered_at must include a timezone offset")
        return self


class LoadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_system: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,62}$")
    orders: list[OrderIn] = Field(min_length=1, max_length=1000)


class MoneyOut(BaseModel):
    amount: str
    currency: str


class RejectionOut(BaseModel):
    source_system: str
    external_id: str
    code: str
    message: str


class LoadResponse(BaseModel):
    load_id: str
    idempotency_key: str
    accepted: int
    rejected: int
    inserted: int
    updated: int
    unchanged: int
    duration_ms: int
    rejections: list[RejectionOut]


class InvoiceLineOut(BaseModel):
    line_no: int
    sku: str
    description: str
    quantity: str
    unit_net: MoneyOut
    line_net: MoneyOut
    vat_code: str
    vat_rate: str
    vat_treatment: str
    vat_amount: MoneyOut
    line_gross: MoneyOut


class PartyOut(BaseModel):
    party_id: str
    name: str
    country: str
    vat_id: str | None


class InvoiceOut(BaseModel):
    source_system: str
    external_id: str
    ordered_at: datetime
    currency: str
    seller: PartyOut
    buyer: PartyOut
    lines: list[InvoiceLineOut]
    net_total: MoneyOut
    vat_total: MoneyOut
    gross_total: MoneyOut
    content_hash: str
    version: int


class InvoiceSummaryOut(BaseModel):
    source_system: str
    external_id: str
    ordered_at: datetime
    currency: str
    net_total: MoneyOut
    vat_total: MoneyOut
    gross_total: MoneyOut
    version: int
    line_count: int
